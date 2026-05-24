"""DKIM signing and SPF policy tests."""
import email
import imaplib
import time

import pytest

from conftest import DOVECOT, IMAP_P, ALICE, ALICE_PW, OPENDKIM, smtp_send


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

@pytest.mark.skipif(not OPENDKIM, reason="opendkim not configured (OPENDKIM_HOST unset)")
def test_dkim_signature_present(unique_subject):
    """Postfix adds a DKIM-Signature header when opendkim is configured."""
    smtp_send(unique_subject)
    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, unique_subject)
        assert msgs, f"Mail '{unique_subject}' not found in INBOX"
        msg = _fetch_message(conn, msgs[0])
    sig = msg.get("DKIM-Signature", "")
    assert sig, f"No DKIM-Signature header. All headers:\n{dict(msg)}"


@pytest.mark.skipif(not OPENDKIM, reason="opendkim not configured (OPENDKIM_HOST unset)")
def test_dkim_signature_fields(unique_subject):
    """DKIM-Signature header contains the correct domain and selector."""
    smtp_send(unique_subject)
    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, unique_subject)
        assert msgs
        msg = _fetch_message(conn, msgs[0])
    sig = msg.get("DKIM-Signature", "")
    assert "d=test.local" in sig, f"Domain missing in DKIM-Signature: {sig}"
    assert "s=mail"       in sig, f"Selector missing in DKIM-Signature: {sig}"


# ----------------------------------------------------------------- SPF -------

def test_spf_pass_header_present(unique_subject):
    """policyd-spf prepends Received-SPF: Pass for senders in the SPF record.

    The test dnsmasq publishes: v=spf1 ip4:10.0.0.0/8 ... ~all
    The test-runner connects from a 10.x.x.x address → SPF result: Pass.
    Postfix mynetworks is restricted to 127.0.0.0/8 so the policy check
    is not bypassed by permit_mynetworks.
    """
    smtp_send(unique_subject)
    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, unique_subject)
        assert msgs, f"Mail '{unique_subject}' not found"
        msg = _fetch_message(conn, msgs[0])
    spf = msg.get("Received-SPF", "")
    assert spf, (
        "No Received-SPF header found — policyd-spf may not be active or "
        "permit_mynetworks may be bypassing the check.\n"
        f"All headers: {dict(msg)}"
    )
    assert spf.lower().startswith("pass"), (
        f"Expected SPF Pass, got: {spf}"
    )
