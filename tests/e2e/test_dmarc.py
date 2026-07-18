"""DMARC enforcement on incoming mail (v3.0.0 — via rspamd).

Semantic: «Sender publishes DKIM/SPF in DNS + neither aligns ⇒ error.»
Handled by rspamd's DMARC module: it evaluates the sender's `_dmarc`
record, combines the SPF and DKIM verdicts, and — when the mode is
`permissive` or `reject` — rejects at SMTP time on hard DMARC fail
where the sender publishes `p=reject`. In `log` mode the verdict is
stamped into the Authentication-Results header and the mail is
delivered anyway.

Test scenarios (routed through the DEFAULT postfix — rspamd in
permissive mode — to prove DMARC enforcement fires even when DKIM
alone would have accepted):

  1. Sender publishes p=reject, sends UNSIGNED     → reject (SPF -all,
     no DKIM ⇒ DMARC hard fail)
  2. Sender publishes p=reject, sends CORRECTLY    → accept (DKIM passes
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
    send_raw, imap_starttls,
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
    """4xx greylist tempfails are retried by send_raw like a real MTA."""
    return send_raw(host, sender, to, raw, helo=f"testhost.{STRICT_DOMAIN}")


def _wait_for_mail(subject: str, retries: int = 5):
    with imap_starttls() as conn:
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
    postfix (rspamd DKIM_DMARC=permissive) — rspamd's DMARC module
    alone must enforce this, independent of whether DKIM would have
    let the mail through."""
    raw = _build_raw(subj, from_=STRICT_SENDER)  # NOT signed
    accepted, resp = _send(raw)
    assert not accepted, (
        f"Unsigned mail from a p=reject sender was ACCEPTED — rspamd's "
        f"DMARC module is not enforcing p=reject. resp: {resp}"
    )
    assert _wait_for_mail(subj) is None, (
        "Unsigned p=reject mail was refused at SMTP time but still "
        "ended up in INBOX"
    )


def test_dmarc_p_none_accepts_unsigned(subj):
    """Sender publishes `_dmarc … p=none` and sends unsigned mail →
    accepted. p=none is monitor-only; rspamd's DMARC module must not
    reject. Complements the p=reject-rejects-unsigned case."""
    NONE_SENDER = "monitor@dmarc-none.local"
    raw = _build_raw(subj, from_=NONE_SENDER)  # unsigned
    accepted, resp = _send(raw, sender=NONE_SENDER)
    assert accepted, (
        f"Unsigned mail from a p=none sender was REJECTED — rspamd's "
        f"DMARC module must only reject on p=reject, not on any DMARC "
        f"record at all. resp: {resp}"
    )
    assert _wait_for_mail(subj) is not None, (
        "p=none unsigned mail was accepted at SMTP time but did not "
        "arrive in INBOX"
    )


def test_dmarc_no_record_accepts_unsigned(subj):
    """Sender has NO `_dmarc` record at all and sends unsigned mail →
    accepted. Without DMARC there is nothing to enforce; rspamd in
    permissive mode must let this through."""
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


def test_dmarc_log_mode_delivers_p_reject_fail(subj):
    """Same p=reject-fail scenario as `test_dmarc_rejects_unsigned_when_p_reject`,
    but routed through postfix-log (rspamd `DKIM_DMARC=log`). rspamd
    must deliver and stamp `dmarc=fail` in the Authentication-Results
    header — proof that log mode gives an admin the DMARC verdict
    without any legitimate mail ever being bounced."""
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
