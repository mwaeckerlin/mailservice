"""Multi-domain DKIM signing.

opendkim is started with DOMAINS="test.local other.local", so mail with
From: @other.local must be signed with the other.local key (d=other.local),
not silently unsigned and not signed as test.local. Proves the multi-domain
DOMAINS env var actually produces per-domain signatures.
"""
import email
import imaplib
import smtplib
import time

from conftest import (
    POSTFIX, SMTP_P, DOVECOT, IMAP_P, ALICE, ALICE_PW, DOMAIN, build_message,
)


OTHER_DOMAIN = "other.local"


def _wait_for_mail(conn: imaplib.IMAP4, subject: str, retries: int = 10):
    for _ in range(retries):
        conn.select("INBOX")
        typ, data = conn.search(None, f'SUBJECT "{subject}"')
        if typ == "OK" and data[0]:
            return data[0].split()
        time.sleep(1)
    return []


def test_multidomain_sign_from_second_domain(unique_subject):
    """A mail with From: @other.local gets a DKIM-Signature with d=other.local.

    Sender is on the second signing domain (other.local); opendkim looks up
    its SigningTable, matches *@other.local → other.local key, and signs
    with d=other.local.
    """
    sender = f"otheralice@{OTHER_DOMAIN}"
    subject = unique_subject
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.sendmail(sender, [ALICE],
                   build_message(subject, from_=sender, to=ALICE))

    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, subject)
        assert msgs, f"Mail '{subject}' not delivered"
        _, raw = conn.fetch(msgs[0], "(RFC822)")
        msg = email.message_from_bytes(raw[0][1])

    sig = msg.get("DKIM-Signature", "")
    assert sig, (
        f"No DKIM-Signature header on a mail From: {sender} — multi-domain "
        f"signing is not working. All headers:\n{dict(msg)}"
    )
    assert f"d={OTHER_DOMAIN}" in sig, (
        f"DKIM-Signature has wrong domain — expected d={OTHER_DOMAIN}, "
        f"got: {sig}"
    )
    assert "s=mail" in sig, f"Selector missing in DKIM-Signature: {sig}"


def test_multidomain_sign_from_first_domain_still_works(unique_subject):
    """Sanity: the first signing domain (test.local) is not broken by adding
    a second domain — regression guard against a shrinking KeyTable.
    """
    # Fixed sender (whitelisted in tests/e2e/greylist.conf) so the greylist
    # milter doesn't tempfail the RCPT on the first attempt.
    sender = f"dkimregress@{DOMAIN}"
    subject = unique_subject
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.sendmail(sender, [ALICE],
                   build_message(subject, from_=sender, to=ALICE))

    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, subject)
        assert msgs
        _, raw = conn.fetch(msgs[0], "(RFC822)")
        msg = email.message_from_bytes(raw[0][1])

    sig = msg.get("DKIM-Signature", "")
    assert f"d={DOMAIN}" in sig, (
        f"First-domain signing broke after adding second domain; got: {sig}"
    )
