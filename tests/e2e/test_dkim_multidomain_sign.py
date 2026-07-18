"""Multi-domain DKIM signing (v3.0.0 — via rspamd).

rspamd is started with DOMAINS="test.local other.local", so mail with
From: @other.local must be signed with the other.local key
(d=other.local), not silently unsigned and not signed as test.local.
Proves rspamd's dkim_signing multi-map picks the per-domain key.
"""
import email
import imaplib
import time

from conftest import (
    DOVECOT, IMAP_P, ALICE, ALICE_PW, DOMAIN, smtp_send, imap_starttls,
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

    Sender is on the second signing domain (other.local); rspamd's
    dkim_signing module resolves the From: domain against
    /var/lib/rspamd/dkim/<domain>.<selector>.key and signs with the
    per-domain key.
    """
    sender = f"otheralice@{OTHER_DOMAIN}"
    subject = unique_subject
    smtp_send(subject, from_=sender, to=ALICE)

    with imap_starttls() as conn:
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
    a second domain — regression guard against a per-domain key lookup
    that only sees one entry.
    """
    # Clean mail is never greylisted under rspamd's score-based
    # greylisting, so no sender whitelisting is needed here (v2 needed
    # an entry in the old milter-greylist config for this sender).
    sender = f"dkimregress@{DOMAIN}"
    subject = unique_subject
    smtp_send(subject, from_=sender, to=ALICE)

    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, subject)
        assert msgs
        _, raw = conn.fetch(msgs[0], "(RFC822)")
        msg = email.message_from_bytes(raw[0][1])

    sig = msg.get("DKIM-Signature", "")
    assert f"d={DOMAIN}" in sig, (
        f"First-domain signing broke after adding second domain; got: {sig}"
    )
