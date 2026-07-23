"""IMAP delivery and folder tests."""
import imaplib
import time
import pytest
from conftest import (
    DOVECOT, DOVECOT_PASSSCHEME, IMAP_P, ALICE, ALICE_PW, BOB, BOB_PW,
    DOMAIN, smtp_send, imap_starttls,
)


def test_default_pass_scheme_effective():
    """DEFAULT_PASS_SCHEME really controls how stored hashes are read —
    the legacy-migration scenario: a database row carrying a bare
    (schemeless) password in the configured scheme must authenticate.
    The dedicated dovecot-passscheme service runs with
    DEFAULT_PASS_SCHEME=PLAIN (its own instance — on a shared one the
    scheme would break the crypt-hashed regular accounts); the row is
    inserted the way an imported legacy database would carry it. The
    wrong-password case proves the check is real."""
    import pymysql
    dave, dave_pw = f"dave@{DOMAIN}", "davepass12"
    conn = pymysql.connect(host="postfixadmin-db", user="postfixadmin",
                           password="testpass", database="postfixadmin")
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM mailbox WHERE username=%s", (dave,))
            cur.execute(
                "INSERT INTO mailbox (username, password, name, maildir,"
                " quota, local_part, domain, created, modified, active)"
                " VALUES (%s, %s, %s, %s, 0, %s, %s, NOW(), NOW(), 1)",
                (dave, dave_pw, "Dave", f"{DOMAIN}/dave/", "dave", DOMAIN))
        conn.commit()
    finally:
        conn.close()

    with imaplib.IMAP4(DOVECOT_PASSSCHEME, IMAP_P) as c:
        typ, _ = c.login(dave, dave_pw)
        assert typ == "OK", (
            "PLAIN-scheme legacy password did not authenticate — "
            "DEFAULT_PASS_SCHEME is not effective"
        )
    with imaplib.IMAP4(DOVECOT_PASSSCHEME, IMAP_P) as c:
        with pytest.raises(imaplib.IMAP4.error):
            c.login(dave, "wrongpass99")


def _wait_for_mail(conn: imaplib.IMAP4, subject: str,
                   mailbox: str = "INBOX", retries: int = 10) -> list[bytes]:
    for _ in range(retries):
        conn.select(mailbox)
        typ, data = conn.search(None, f'SUBJECT "{subject}"')
        if typ == "OK" and data[0]:
            return data[0].split()
        time.sleep(1)
    return []


def test_imap_login():
    with imap_starttls() as conn:
        typ, _ = conn.login(ALICE, ALICE_PW)
        assert typ == "OK"


def test_imap_wrong_password_rejected():
    with imap_starttls() as conn:
        with pytest.raises(imaplib.IMAP4.error):
            conn.login(ALICE, "wrongpassword")


def test_imap_cleartext_login_refused_without_tls():
    """Security invariant (auth_allow_cleartext=no): on the unencrypted
    channel dovecot advertises LOGINDISABLED and refuses LOGIN, so a
    password can never travel in the clear — even with valid credentials."""
    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        assert "LOGINDISABLED" in conn.capabilities, (
            "dovecot did not advertise LOGINDISABLED on the plain channel "
            "— cleartext auth appears to be allowed"
        )
        with pytest.raises(imaplib.IMAP4.error):
            conn.login(ALICE, ALICE_PW)


def test_imap_mail_delivered_to_inbox(unique_subject):
    """Mail sent via SMTP appears in the recipient's INBOX."""
    smtp_send(unique_subject)
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, unique_subject)
    assert msgs, f"Mail with subject '{unique_subject}' not found in INBOX"


def test_imap_fetch_message_body(unique_subject):
    """Fetched message body matches what was sent."""
    body = f"unique-body-{unique_subject}"
    smtp_send(unique_subject, body=body)
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, unique_subject)
        assert msgs
        _, raw = conn.fetch(msgs[0], "(RFC822)")
        assert body.encode() in raw[0][1]


def test_imap_folder_create_and_delete(imap_alice):
    folder = "TestFolder-E2E"
    imap_alice.create(folder)
    typ, folders = imap_alice.list()
    names = b" ".join(folders).decode()
    assert folder in names
    imap_alice.delete(folder)


def test_imap_capability(imap_alice):
    typ, caps = imap_alice.capability()
    assert typ == "OK"
    assert b"IMAP4rev1" in b" ".join(caps)


def test_imap_independent_mailboxes(unique_subject):
    """Mail delivered to alice is NOT visible in bob's INBOX."""
    smtp_send(unique_subject)
    time.sleep(3)
    with imap_starttls() as conn:
        conn.login(BOB, BOB_PW)
        conn.select("INBOX")
        typ, data = conn.search(None, f'SUBJECT "{unique_subject}"')
        assert not data[0], "Mail leaked into wrong mailbox"
