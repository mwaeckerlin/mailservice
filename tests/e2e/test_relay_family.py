"""Relay-family invariants: smtp-relay, smtp-relay-tls, mailforward.

These generic postfix images are the base chain of the mailservice
postfix (smtp-relay → mailforward → postfix, smtp-relay →
smtp-relay-tls). The tests pin the behavioural contract the headless
migration must preserve:

  - the SMTP banner and EHLO answer on port 25 (the daemon actually
    boots and speaks SMTP)
  - smtp-relay's core purpose: a mail for a foreign domain is accepted
    from the internal network and REALLY relayed — MX lookup via the
    isolated resolver, delivery to fake-smtp behind extern.local —
    asserted end-to-end by reading fake-smtp's mail store
  - smtp-relay-tls offers STARTTLS with the mounted certificate and
    completes a handshake
  - mailforward's core purpose: a mail to a mapped virtual alias is
    rewritten and REALLY delivered to the target domain's MX (fake-smtp
    behind extern.local, see dns/dnsmasq.conf) — asserted end-to-end by
    reading fake-smtp's mail store
  - an unmapped recipient in the alias domain is rejected with a
    permanent 5xx (no silent drop, no open destination)
"""
import os
import pathlib
import smtplib
import time

import pytest

from conftest import DOMAIN, SMTP_P, build_message, insecure_tls_ctx

SMTP_RELAY     = os.environ.get("SMTP_RELAY_HOST",     "smtp-relay")
SMTP_RELAY_TLS = os.environ.get("SMTP_RELAY_TLS_HOST", "smtp-relay-tls")
MAILFORWARD    = os.environ.get("MAILFORWARD_HOST",    "mailforward")
FWD_ADDRESS    = os.environ.get("FWD_ADDRESS",         "forward@fwd.local")
FWD_UNMAPPED   = os.environ.get("FWD_UNMAPPED",        "nobody@fwd.local")
FAKE_MAILS_DIR = os.environ.get("FAKE_MAILS_DIR",      "/fake-mails")

HELO = f"testhost.{DOMAIN}"


def _ehlo_ok(host: str) -> smtplib.SMTP:
    conn = smtplib.SMTP(host, SMTP_P, timeout=15)
    code, _ = conn.ehlo(HELO)
    assert code == 250, f"{host}: EHLO answered {code}"
    return conn


def _find_in_fake_store(subject: str, timeout: int = 60) -> str:
    """Wait until a mail containing `subject` shows up in fake-smtp's
    mail store and return its full text ('' on timeout) — the proof
    that a relay/forward REALLY left the image under test and reached
    the target domain's MX."""
    deadline = time.time() + timeout
    store = pathlib.Path(FAKE_MAILS_DIR)
    while time.time() < deadline:
        for f in store.rglob("*"):
            if f.is_file():
                text = f.read_text(errors="replace")
                if subject in text:
                    return text
        time.sleep(2)
    return ""


def _assert_in_fake_store(subject: str, what: str) -> str:
    text = _find_in_fake_store(subject)
    if not text:
        pytest.fail(f"{what} not found in fake-smtp store {FAKE_MAILS_DIR}")
    return text


# ----------------------------------------------------------------- Tests ---

def test_smtp_relay_banner_and_ehlo():
    """smtp-relay boots and answers 220 + EHLO 250 on port 25."""
    with _ehlo_ok(SMTP_RELAY) as conn:
        assert conn.has_extn("PIPELINING"), "postfix EHLO keywords missing"


def test_smtp_relay_relays_to_external_mx(unique_subject):
    """smtp-relay's core purpose: mail for a foreign domain, submitted
    from the internal network, is accepted and relayed — real MX lookup
    for extern.local via the isolated resolver, real delivery to
    fake-smtp — not just accepted into a queue."""
    sender = f"app@{DOMAIN}"
    rcpt = "relay-sink@extern.local"
    with _ehlo_ok(SMTP_RELAY) as conn:
        result = conn.sendmail(
            sender, [rcpt], build_message(unique_subject, from_=sender, to=rcpt))
    assert result == {}, f"smtp-relay refused the relay submission: {result!r}"
    _assert_in_fake_store(unique_subject, "relayed mail")


def test_smtp_relay_milter_hook_effective(unique_subject):
    """The generic milter hook (`OPENDKIM` env, historical name) really
    feeds the mail through the wired milter: the relayed mail carries
    rspamd's verdict headers — the hook is effective, not just a
    rendered config line."""
    sender = f"app@{DOMAIN}"
    rcpt = "milter-sink@extern.local"
    with _ehlo_ok(SMTP_RELAY) as conn:
        result = conn.sendmail(
            sender, [rcpt], build_message(unique_subject, from_=sender, to=rcpt))
    assert result == {}, f"smtp-relay refused the submission: {result!r}"
    text = _assert_in_fake_store(unique_subject, "milter-scanned relayed mail")
    assert "X-Spamd-Result" in text or "X-Spam-Status" in text, (
        "relayed mail carries no rspamd verdict header — the OPENDKIM "
        "milter hook is not effective"
    )


def test_mailforward_milter_hook_effective(unique_subject):
    """Same for mailforward's `GREYLIST` hook (historical name): the
    forwarded mail must carry rspamd's verdict headers."""
    sender = f"someone@{DOMAIN}"
    with _ehlo_ok(MAILFORWARD) as conn:
        result = conn.sendmail(
            sender, [FWD_ADDRESS],
            build_message(unique_subject, from_=sender, to=FWD_ADDRESS))
    assert result == {}, f"mailforward refused the submission: {result!r}"
    text = _assert_in_fake_store(unique_subject, "milter-scanned forward")
    assert "X-Spamd-Result" in text or "X-Spam-Status" in text, (
        "forwarded mail carries no rspamd verdict header — the GREYLIST "
        "milter hook is not effective"
    )


def test_smtp_relay_tls_starttls_handshake():
    """smtp-relay-tls offers STARTTLS with the mounted cert and the
    handshake completes; EHLO still works on the encrypted channel."""
    with _ehlo_ok(SMTP_RELAY_TLS) as conn:
        assert conn.has_extn("STARTTLS"), "STARTTLS not offered"
        code, _ = conn.starttls(context=insecure_tls_ctx())
        assert code == 220, f"STARTTLS handshake failed: {code}"
        code, _ = conn.ehlo(HELO)
        assert code == 250, f"EHLO over TLS answered {code}"


def test_mailforward_banner_and_ehlo():
    """mailforward boots and answers 220 + EHLO 250 on port 25."""
    with _ehlo_ok(MAILFORWARD):
        pass


def test_mailforward_forwards_mapped_alias(unique_subject):
    """A mail to the mapped alias is accepted, rewritten via the
    virtual map and delivered to the target domain's MX (fake-smtp)."""
    sender = f"someone@{DOMAIN}"
    with _ehlo_ok(MAILFORWARD) as conn:
        result = conn.sendmail(
            sender, [FWD_ADDRESS],
            build_message(unique_subject, from_=sender, to=FWD_ADDRESS))
    assert result == {}, f"mailforward refused the mapped alias: {result!r}"
    _assert_in_fake_store(unique_subject, "forwarded mail")


def test_mailforward_rejects_unmapped_recipient(unique_subject):
    """An unmapped address in the alias domain draws a permanent 5xx —
    delivered-or-rejected, never accepted into a void."""
    sender = f"someone@{DOMAIN}"
    with _ehlo_ok(MAILFORWARD) as conn:
        code, _ = conn.mail(sender)
        assert code == 250
        code, resp = conn.rcpt(FWD_UNMAPPED)
    assert 500 <= code < 600, (
        f"unmapped virtual recipient was not rejected: {code} {resp!r}")
