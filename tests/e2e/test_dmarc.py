"""DMARC enforcement on incoming mail.

Marc's semantic: «Sender publiziert DKIM in DNS + keine Signatur ⇒ Fehler.»
opendkim itself cannot decide this (no signature means no selector to look
up), so this is opendmarc's job: it evaluates the sender's `_dmarc` record,
combines it with opendkim's dkim= verdict (via Authentication-Results) and
its own SPF check, and rejects on hard DMARC fail when the sender publishes
`p=reject`.

Test scenarios (both routed through the DEFAULT postfix — `DKIM_ENFORCE=no`
— to prove opendmarc alone enforces `p=reject`):

  1. Sender publishes p=reject, sends UNSIGNED     → reject (SPF -all,
     no DKIM ⇒ DMARC hard fail)
  2. Sender publishes p=reject, sends CORRECTLY   → accept (DKIM passes
     and is aligned with From: domain ⇒ DMARC pass)

The `dmarc-strict.local` domain is set up in `dns/dnsmasq.conf` with
`v=spf1 -all` and `_dmarc.dmarc-strict.local  p=reject`; the same DKIM
test key that external.local uses is also published there.
"""
import email
import imaplib
import smtplib
import time
import uuid

import dkim
import pytest

from conftest import (
    POSTFIX, POSTFIX_LOG, SMTP_P, DOVECOT, IMAP_P, ALICE, ALICE_PW,
)


STRICT_DOMAIN   = "dmarc-strict.local"
STRICT_SENDER   = f"strict@{STRICT_DOMAIN}"
STRICT_SELECTOR = "mail"
STRICT_KEY_PATH = "/testkeys/external.local.mail.key"  # same test key


def _build_raw(subject: str, from_: str, to: str = ALICE) -> bytes:
    msg_id = f"<{uuid.uuid4()}@{STRICT_DOMAIN}>"
    return (
        f"From: {from_}\r\n"
        f"To: {to}\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: {msg_id}\r\n"
        f"Date: Mon, 14 Jul 2026 12:00:00 +0000\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"dmarc test body\r\n"
    ).encode("utf-8")


def _sign(raw: bytes, domain: str, selector: str = STRICT_SELECTOR) -> bytes:
    with open(STRICT_KEY_PATH, "rb") as f:
        key = f.read()
    sig = dkim.sign(
        message   = raw,
        selector  = selector.encode(),
        domain    = domain.encode(),
        privkey   = key,
        include_headers = [b"From", b"To", b"Subject"],
    )
    return sig + raw


def _send(raw: bytes, to: str = ALICE, sender: str = STRICT_SENDER,
          host: str = POSTFIX) -> tuple[bool, str]:
    try:
        with smtplib.SMTP(host, SMTP_P, timeout=15) as s:
            s.ehlo(f"testhost.{STRICT_DOMAIN}")
            s.mail(sender)
            s.rcpt(to)
            code, resp = s.data(raw)
            return (200 <= code < 400, f"{code} {resp!r}")
    except smtplib.SMTPResponseException as e:
        return (False, f"{e.smtp_code} {e.smtp_error!r}")


def _wait_for_mail(subject: str, retries: int = 5):
    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        conn.login(ALICE, ALICE_PW)
        for _ in range(retries):
            conn.select("INBOX")
            typ, data = conn.search(None, f'SUBJECT "{subject}"')
            if typ == "OK" and data[0]:
                _, raw = conn.fetch(data[0].split()[0], "(RFC822)")
                return email.message_from_bytes(raw[0][1])
            time.sleep(1)
    return None


@pytest.fixture
def subj():
    return f"E2E-DMARC-{uuid.uuid4()}"


def test_dmarc_rejects_unsigned_when_p_reject(subj):
    """Sender publishes `_dmarc … p=reject` and sends unsigned mail →
    rejected at SMTP time, not delivered. Routed through the DEFAULT
    postfix (DKIM_ENFORCE=no) — opendmarc alone must enforce this."""
    raw = _build_raw(subj, from_=STRICT_SENDER)  # NOT signed
    accepted, resp = _send(raw)
    assert not accepted, (
        f"Unsigned mail from a p=reject sender was ACCEPTED — opendmarc "
        f"is not enforcing p=reject. resp: {resp}"
    )
    assert _wait_for_mail(subj) is None, (
        "Unsigned p=reject mail was refused at SMTP time but still "
        "ended up in INBOX"
    )


def test_dmarc_p_none_accepts_unsigned(subj):
    """Sender publishes `_dmarc … p=none` and sends unsigned mail →
    accepted. p=none is monitor-only, opendmarc must not reject.
    Complements the p=reject-rejects-unsigned case."""
    NONE_SENDER = "monitor@dmarc-none.local"
    raw = _build_raw(subj, from_=NONE_SENDER)  # unsigned
    accepted, resp = _send(raw, sender=NONE_SENDER)
    assert accepted, (
        f"Unsigned mail from a p=none sender was REJECTED — opendmarc must "
        f"only reject on p=reject, not on any DMARC record. resp: {resp}"
    )
    assert _wait_for_mail(subj) is not None, (
        "p=none unsigned mail was accepted at SMTP time but did not "
        "arrive in INBOX"
    )


def test_dmarc_no_record_accepts_unsigned(subj):
    """Sender has NO `_dmarc` record at all and sends unsigned mail →
    accepted. Without DMARC there is nothing to enforce; DKIM_ENFORCE=no
    on the default postfix must let this through."""
    # nodkim.local has no DKIM key AND no _dmarc record → the perfect
    # "sender has nothing published" case.
    NO_DMARC_SENDER = "plain@nodkim.local"
    raw = _build_raw(subj, from_=NO_DMARC_SENDER)  # unsigned
    accepted, resp = _send(raw, sender=NO_DMARC_SENDER)
    assert accepted, (
        f"Unsigned mail from a sender with no DMARC record was REJECTED: {resp}"
    )
    assert _wait_for_mail(subj) is not None, (
        "no-DMARC unsigned mail was accepted at SMTP time but did not "
        "arrive in INBOX"
    )


def test_dmarc_log_mode_delivers_p_reject_fail_with_disposition_none(subj):
    """Same p=reject-fail scenario as `test_dmarc_rejects_unsigned_when_p_reject`,
    but routed through postfix-log (`DKIM_DMARC=log`). opendmarc must
    deliver and stamp `dmarc=fail (p=reject dis=none)` — proof that log
    mode gives an admin the DMARC verdict without any legitimate mail
    ever being bounced."""
    raw = _build_raw(subj, from_=STRICT_SENDER)  # unsigned
    accepted, resp = _send(raw, sender=STRICT_SENDER, host=POSTFIX_LOG)
    assert accepted, (
        f"Log-mode postfix rejected an unsigned p=reject mail: {resp}"
    )
    msg = _wait_for_mail(subj)
    assert msg is not None, "Log-mode postfix accepted at SMTP but did not deliver"
    ar = " ".join(msg.get_all("Authentication-Results", []))
    assert "dmarc=fail" in ar.lower(), (
        f"Log-mode should stamp dmarc=fail on a p=reject unsigned mail. "
        f"Authentication-Results: {ar!r}"
    )
    assert "dis=none" in ar.lower(), (
        f"Log-mode should record disposition=none (never rejects). "
        f"Authentication-Results: {ar!r}"
    )


def test_dmarc_accepts_correctly_signed_when_p_reject(subj):
    """Same p=reject sender, but this time DKIM-signed with the matching
    key. DKIM passes and aligns with the From: domain → DMARC pass →
    accepted and delivered."""
    raw = _sign(_build_raw(subj, from_=STRICT_SENDER), domain=STRICT_DOMAIN)
    accepted, resp = _send(raw)
    assert accepted, (
        f"Correctly signed mail from a p=reject sender was REJECTED — "
        f"DKIM alignment should satisfy DMARC. resp: {resp}"
    )
    msg = _wait_for_mail(subj)
    assert msg is not None, (
        "Correctly signed p=reject mail was accepted at SMTP time but "
        "did not arrive in INBOX"
    )
    ar = " ".join(msg.get_all("Authentication-Results", []))
    assert "dmarc=pass" in ar.lower(), (
        f"Correctly signed p=reject mail did not stamp dmarc=pass. "
        f"Authentication-Results: {ar!r}"
    )
