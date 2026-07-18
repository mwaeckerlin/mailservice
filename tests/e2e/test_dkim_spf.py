"""DKIM signing and SPF policy tests."""
import email
import imaplib
import time

from conftest import DOVECOT, IMAP_P, ALICE, ALICE_PW, smtp_send, imap_starttls


def _wait_for_mail(conn: imaplib.IMAP4, subject: str, retries: int = 10) -> list[bytes]:
    for _ in range(retries):
        conn.select("INBOX")
        typ, data = conn.search(None, f'SUBJECT "{subject}"')
        if typ == "OK" and data[0]:
            return data[0].split()
        time.sleep(1)
    return []


def _fetch_message(conn: imaplib.IMAP4, msg_id: bytes) -> email.message.Message:
    _, raw = conn.fetch(msg_id, "(RFC822)")
    return email.message_from_bytes(raw[0][1])


# ----------------------------------------------------------------- DKIM ------

def test_dkim_signature_present(unique_subject):
    """Postfix adds a DKIM-Signature header to outgoing mail."""
    smtp_send(unique_subject)
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, unique_subject)
        assert msgs, f"Mail '{unique_subject}' not found in INBOX"
        msg = _fetch_message(conn, msgs[0])
    sig = msg.get("DKIM-Signature", "")
    assert sig, f"No DKIM-Signature header. All headers:\n{dict(msg)}"


def test_dkim_signature_fields(unique_subject):
    """DKIM-Signature header contains the correct domain and selector."""
    smtp_send(unique_subject)
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, unique_subject)
        assert msgs
        msg = _fetch_message(conn, msgs[0])
    sig = msg.get("DKIM-Signature", "")
    assert "d=test.local" in sig, f"Domain missing in DKIM-Signature: {sig}"
    assert "s=mail"       in sig, f"Selector missing in DKIM-Signature: {sig}"


# ----------------------------------------------------------------- SPF -------

def test_spf_result_in_authentication_results(unique_subject):
    """rspamd's SPF module stamps `spf=pass|fail|none|softfail|...` into the
    Authentication-Results header. v3.0.0 retired postfix-policyd-spf-perl
    (which used its own Received-SPF header) — the SPF verdict now lives in
    the same A-R header as DKIM and DMARC, RFC 8601-style.

    The test dnsmasq publishes:  v=spf1 ip4:10.0.0.0/8 ... ~all
    The test-runner connects from a 10.x.x.x address → spf=pass.
    Postfix mynetworks is restricted to 127.0.0.0/8, so the check is not
    bypassed by permit_mynetworks.
    """
    smtp_send(unique_subject)
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, unique_subject)
        assert msgs, f"Mail '{unique_subject}' not found"
        msg = _fetch_message(conn, msgs[0])
    ar = " ".join(msg.get_all("Authentication-Results", []))
    assert ar, (
        "No Authentication-Results header — rspamd may not have run "
        "against this mail. "
        f"Headers: {dict(msg)}"
    )
    assert "spf=pass" in ar.lower(), (
        "Expected spf=pass in Authentication-Results (test-runner is "
        f"inside the SPF ip4:10.0.0.0/8 allow-list). Got: {ar!r}"
    )
