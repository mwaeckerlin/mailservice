"""Incoming DKIM verification — sign-side and enforce-side both covered.

Uses `dkimpy` to simulate an external sender @external.local. The matching
public key is published in dns/dnsmasq.conf at mail._domainkey.external.local;
the private key is committed at tests/e2e/testkeys/external.local.mail.key
(TEST key only — never used in production).

The verification is done by rspamd's DKIM module and stamped into the
`Authentication-Results:` header exactly like an RFC-8601-compliant
downstream would expect (`dkim=pass|fail|permerror|none`). The matrix
across the three `DKIM_DMARC` modes each e2e postfix routes through:

  postfix (permissive):
    1a. Correct signature                → accept, dkim=pass
    2a. No signature                     → accept
    5a. Bad signature                    → reject
  postfix-strict (reject):
    1b. Correct signature                → accept, dkim=pass
    3.  No signature                     → reject
    4.  Bad signature                    → reject
  postfix-log (log):
    1c. Correct signature                → accept, dkim=pass
    L1. Bad signature                    → accept, dkim=fail  (never rejects)
    L2. No signature                     → accept, dkim=none  (never rejects)

Not directly tested here but in place: an unknown-key DKIM signature
(the public key `<selector>._domainkey.<domain>` is missing in DNS)
maps to `dkim=permerror` under rspamd; the DMARC module then rejects
if the sender publishes `p=reject`. The Docker embedded resolver
rewrites the container-local dnsmasq's authoritative NXDOMAIN into
SERVFAIL, which rspamd (like opendkim before it) treats as a temporary
failure — the reject path only fires against a real internet resolver
where NXDOMAIN passes through unchanged. That mechanism is covered
indirectly by test_verify_bad_signature_always_rejected_even_without_enforce
(proves rspamd runs verify against RFC1918 senders and honours the
reject action) and by test_dmarc_rejects_unsigned_when_p_reject (proves
the second-layer DMARC catches a broken chain even if DKIM alone did
not conclude).
"""
import email
import imaplib
import smtplib
import time
import uuid

import dkim
import pytest

from conftest import (
    POSTFIX, POSTFIX_STRICT, POSTFIX_LOG, SMTP_P, DOVECOT, IMAP_P,
    ALICE, ALICE_PW, send_raw, imap_starttls,
)


EXT_DOMAIN     = "external.local"
EXT_SELECTOR   = "mail"
EXT_KEY_PATH   = "/testkeys/external.local.mail.key"
EXT_SENDER     = f"remote@{EXT_DOMAIN}"


# --------------------------------------------------------- helpers -----------

def _build_raw(subject: str, to: str = ALICE, body: str = "verify body") -> bytes:
    msg_id = f"<{uuid.uuid4()}@{EXT_DOMAIN}>"
    return (
        f"From: {EXT_SENDER}\r\n"
        f"To: {to}\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: {msg_id}\r\n"
        f"Date: Mon, 14 Jul 2026 12:00:00 +0000\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"{body}\r\n"
    ).encode("utf-8")


def _sign(raw: bytes, tamper: bool = False, selector: str = EXT_SELECTOR) -> bytes:
    """Sign a raw RFC5322 message with the external.local test key.

    tamper=True flips a byte in the signature so verification fails but the
    DKIM-Signature header is otherwise well-formed (`On-BadSignature` path).
    selector='nonexistent' produces a signature that references a DKIM key
    not published in DNS (`On-KeyNotFound` path).
    """
    with open(EXT_KEY_PATH, "rb") as f:
        key = f.read()
    sig = dkim.sign(
        message   = raw,
        selector  = selector.encode(),
        domain    = EXT_DOMAIN.encode(),
        privkey   = key,
        include_headers = [b"From", b"To", b"Subject"],
    )
    if tamper:
        # Flip a character in the b= (signature body) field so verification
        # fails but the DKIM-Signature header is otherwise well-formed.
        sig = sig.replace(b"b=", b"b=X", 1)
    return sig + raw


def _send(host: str, raw: bytes, to: str = ALICE,
          sender_override: str | None = None) -> tuple[bool, str]:
    """Return (accepted, error_text). accepted=False for 5xx during
    DATA; 4xx greylist tempfails are retried by send_raw like a real
    MTA would."""
    sender = sender_override or EXT_SENDER
    return send_raw(host, sender, to, raw, helo=f"testhost.{EXT_DOMAIN}")


def _wait_for_mail(subject: str, retries: int = 10):
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


# --------------------------------------------------------- fixtures ----------

@pytest.fixture
def subj():
    return f"E2E-DKIMV-{uuid.uuid4()}"


# --------------------------------------------------------- tests -------------

def test_verify_correct_signature_accepted(subj):
    """Case 1: correctly signed mail → accept, delivered, Authentication-Results
    contains dkim=pass. Routed through postfix-strict so opendkim actually
    runs the verify path (default postfix treats RFC1918 senders like the
    test-runner as internal and skips verification)."""
    raw = _sign(_build_raw(subj))
    accepted, resp = _send(POSTFIX_STRICT, raw)
    assert accepted, f"Correctly signed mail was rejected: {resp}"

    msg = _wait_for_mail(subj)
    assert msg is not None, "Correctly signed mail was not delivered"

    ar = " ".join(msg.get_all("Authentication-Results", []))
    assert "dkim=pass" in ar.lower(), (
        f"Correctly signed mail did not verify as dkim=pass. "
        f"Authentication-Results: {ar!r}"
    )


def test_verify_missing_signature_accepted_when_not_enforced(subj):
    """Case 2: unsigned mail + DKIM_DMARC=permissive → accept, delivered.
    Uses the default postfix (rspamd DKIM_DMARC=permissive); permissive
    mode never bounces an unsigned mail."""
    raw = _build_raw(subj)  # NOT signed
    accepted, resp = _send(POSTFIX, raw)
    assert accepted, (
        f"Unsigned mail was rejected by non-enforce postfix: {resp}"
    )
    assert _wait_for_mail(subj) is not None, (
        "Unsigned mail was not delivered by non-enforce postfix"
    )


def test_verify_missing_signature_rejected_when_enforced(subj):
    """Case 3: unsigned mail + DKIM_DMARC=reject → rejected at SMTP time,
    NOT delivered to alice's INBOX.

    postfix's aggressive `smtpd_hard_error_limit=1` collapses the milter's
    550/5.7.0 into a 421 disconnect at the client, so we assert on the
    observable outcomes (SMTP not-accepted AND mail did not arrive) rather
    than the specific 5xx code."""
    raw = _build_raw(subj)  # NOT signed
    accepted, resp = _send(POSTFIX_STRICT, raw)
    assert not accepted, (
        f"Unsigned mail was ACCEPTED by enforce postfix: {resp}"
    )
    assert _wait_for_mail(subj, retries=3) is None, (
        "Unsigned mail was rejected at SMTP time but still ended up in INBOX"
    )


def test_verify_bad_signature_rejected_when_enforced(subj):
    """Case 4: tampered signature + DKIM_DMARC=reject → rejected at SMTP
    time, NOT delivered to alice's INBOX."""
    raw = _sign(_build_raw(subj), tamper=True)
    accepted, resp = _send(POSTFIX_STRICT, raw)
    assert not accepted, (
        f"Tampered-signature mail was ACCEPTED by enforce postfix: {resp}"
    )
    assert _wait_for_mail(subj, retries=3) is None, (
        "Tampered-signature mail was rejected at SMTP time but still "
        "ended up in INBOX"
    )


def test_verify_correct_signature_accepted_by_default_postfix(subj):
    """Sanity: a correctly signed mail routed through the default postfix
    (rspamd DKIM_DMARC=permissive) is accepted and stamped dkim=pass.
    Complements test_verify_correct_signature_accepted which uses the
    strict postfix."""
    raw = _sign(_build_raw(subj))
    accepted, resp = _send(POSTFIX, raw)
    assert accepted, f"Correctly signed mail was rejected on default postfix: {resp}"
    msg = _wait_for_mail(subj)
    assert msg is not None, "Correctly signed mail did not arrive"
    ar = " ".join(msg.get_all("Authentication-Results", []))
    assert "dkim=pass" in ar.lower(), (
        f"Correctly signed mail did not verify as dkim=pass. A-R: {ar!r}"
    )


def test_verify_bad_signature_always_rejected_even_without_enforce(subj):
    """Case 5: tampered signature routed through the DEFAULT postfix
    (rspamd DKIM_DMARC=permissive) is STILL rejected — DKIM in DNS is
    never optional once a sender publishes it; a bad signature is
    always a bounce even in permissive mode."""
    raw = _sign(_build_raw(subj), tamper=True)
    accepted, resp = _send(POSTFIX, raw)
    assert not accepted, (
        f"Tampered signature was ACCEPTED by permissive-mode postfix — "
        f"rspamd's R_DKIM_REJECT action is not being applied. resp: {resp}"
    )
    assert _wait_for_mail(subj, retries=3) is None, (
        "Tampered signature was rejected at SMTP time but still ended up in "
        "INBOX"
    )


# ------------------------------------------------------ log-mode cases -----

def test_verify_bad_signature_delivered_in_log_mode(subj):
    """Log mode never rejects. A tampered signature routed through
    postfix-log is accepted, delivered, and stamped `dkim=fail` in the
    Authentication-Results header — the whole point of log mode is that
    an admin sees the verdict without any legitimate mail being bounced."""
    raw = _sign(_build_raw(subj), tamper=True)
    accepted, resp = _send(POSTFIX_LOG, raw)
    assert accepted, f"Log-mode postfix rejected a bad signature: {resp}"

    msg = _wait_for_mail(subj)
    assert msg is not None, "Log-mode postfix accepted at SMTP but did not deliver"
    ar = " ".join(msg.get_all("Authentication-Results", []))
    assert "dkim=fail" in ar.lower(), (
        f"Log-mode should stamp dkim=fail on a tampered signature. "
        f"Authentication-Results: {ar!r}"
    )


def test_verify_missing_signature_delivered_in_log_mode(subj):
    """Log mode delivers unsigned mail and stamps `dkim=none` — never
    rejects, even if the sender is expected to sign. Also proves the
    A-R stamping is always on in log mode so an admin sees the missing
    signature explicitly."""
    raw = _build_raw(subj)  # unsigned
    accepted, resp = _send(POSTFIX_LOG, raw)
    assert accepted, f"Log-mode postfix rejected an unsigned mail: {resp}"

    msg = _wait_for_mail(subj)
    assert msg is not None, "Log-mode postfix accepted at SMTP but did not deliver"
    ar = " ".join(msg.get_all("Authentication-Results", []))
    # rspamd stamps `dkim=none` for messages without a DKIM-Signature
    # header at all, so a monitoring admin can grep for it in delivered
    # mail during a `log`-mode roll-out.
    assert "dkim=none" in ar.lower(), (
        f"Log-mode should stamp dkim=none on an unsigned mail. "
        f"Authentication-Results: {ar!r}"
    )


# Note: unknown-key DKIM (public key missing in DNS) is NOT directly
# tested here — the Docker embedded resolver rewrites the container-local
# dnsmasq's NXDOMAIN into SERVFAIL, which rspamd treats as a temporary
# failure and does not turn into a permanent reject. In real production
# (Docker Swarm forwarding to the host / internet resolver) NXDOMAIN
# passes through unchanged and rspamd's `R_DKIM_PERMERROR` fires as
# intended. The nodkim.local zone in dns/dnsmasq.conf is kept committed
# as a hook for a future test if the e2e stack is ever wired to a
# shell-side resolver instead of Docker's embedded one.
