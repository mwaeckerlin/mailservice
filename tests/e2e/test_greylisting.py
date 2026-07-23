"""Greylisting (v3.0.0 — rspamd greylist module, score-based).

Semantic change vs. v2.x: postgrey/milter-greylist delayed EVERY
unknown (sender, recipient, client-ip) triplet with a 4xx. rspamd's
greylist module is score-based — only mail whose spam score crosses
the greylist action threshold (RSPAMD_GREYLIST_SCORE, default 5) is
delayed; clean mail from an unknown sender is delivered on the first
attempt. This is deliberate and matches the project philosophy
(«reliability over filtering», never delay legitimate first-time
senders).

Contracts pinned here:

  1. Clean mail from an unknown sender is NOT greylisted — accepted
     and delivered on the very first attempt. (Regression guard
     against re-introducing unconditional postgrey-style delays.)
  2. SASL-authenticated submissions are never greylisted, whatever
     their content. Mail philosophy: a client only hands the mail to
     postfix; postfix owns delivery — a tempfail would surface a 451
     in the webmail and the mail would never reach the queue. Pinned
     by rspamd/greylist.conf `check_authed = false`.
  3. The greylist action itself: mail in the doubtful score band
     (greylist threshold 5 <= score < reject 15) is tempfailed with a
     4xx on the first attempt and ACCEPTED on the retry of the same
     message — the RFC-compliant defer/retry dance. The deterministic
     mid-score payload combines rules that fire reliably in this
     stack: a pre-existing spam flag (`SPAM_FLAG`, 5.0 — rspamd
     scores forged verdict headers), the e2e HELO heuristics
     (`HFILTER_HELO_5`, 3.0) and a missing Date header
     (`MISSING_DATE`, 1.0) — ~9 points, comfortably inside the band.
"""
import imaplib
import smtplib
import ssl
import time

from conftest import (
    POSTFIX, POSTFIX_CHECKLOCAL, SMTP_P, DOVECOT, IMAP_P, ALICE, ALICE_PW,
    BOB, DOMAIN, GREYLIST_RETRY_DELAY, build_message, imap_starttls,
)


def _insecure_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _wait_for_mail(subject: str, retries: int = 15) -> bool:
    for _ in range(retries):
        with imap_starttls() as conn:
            conn.login(ALICE, ALICE_PW)
            conn.select("INBOX")
            _, data = conn.search(None, f'SUBJECT "{subject}"')
            if data[0]:
                return True
        time.sleep(1)
    return False


def test_clean_unknown_sender_not_greylisted(unique_subject):
    """A clean mail from a never-seen sender is accepted on the FIRST
    attempt and delivered. Under postgrey this would have been a 4xx;
    rspamd's score-based greylisting must not delay clean mail."""
    sender = f"first-time-{unique_subject.lower()}@{DOMAIN}"
    subject = f"grey-clean-{unique_subject}"
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        result = s.sendmail(sender, [ALICE],
                            build_message(subject, from_=sender))
    assert result == {}, (
        f"Clean first-time sender was tempfailed/rejected: {result!r} — "
        f"score-based greylisting must not delay clean mail."
    )
    assert _wait_for_mail(subject), (
        "Clean first-attempt mail was accepted at SMTP time but never "
        "arrived in INBOX"
    )


def test_midscore_mail_greylisted_then_accepted(unique_subject):
    """The greylist defer/retry path end-to-end: a mid-score mail from a
    fresh triplet draws a 4xx on the first attempt; retrying the SAME
    message after the greylist timeout (e2e: RSPAMD_GREYLIST_TIMEOUT=5s)
    is accepted and the mail is delivered to INBOX — tempfail is a
    deferral, never a loss."""
    sender = f"grey-mid-{unique_subject.lower()}@{DOMAIN}"
    subject = f"grey-mid-{unique_subject}"
    # deterministic mid-score payload (~9 points, see module docstring):
    # forged spam flag + e2e HELO heuristics + missing Date header
    raw = (f"X-Spam-Flag: YES\r\n"
           + build_message(subject, from_=sender)).encode()

    def _attempt() -> int:
        try:
            with smtplib.SMTP(POSTFIX, SMTP_P, timeout=15) as s:
                s.ehlo(f"testhost.{DOMAIN}")
                s.mail(sender)
                s.rcpt(ALICE)
                code, _ = s.data(raw)
                return code
        except smtplib.SMTPResponseException as e:
            return e.smtp_code

    first = _attempt()
    assert 400 <= first < 500, (
        f"mid-score mail was not greylisted on the first attempt "
        f"(got {first}) — the defer path of the greylist action is dead"
    )

    time.sleep(GREYLIST_RETRY_DELAY)
    second = _attempt()
    assert 200 <= second < 300, (
        f"greylisted mail was not accepted on the retry (got {second}) — "
        f"a greylist tempfail must be a deferral, not a permanent loss"
    )
    assert _wait_for_mail(subject), (
        "greylisted-then-accepted mail never arrived in INBOX"
    )


def test_check_local_greylists_local_clients(unique_subject):
    """RSPAMD_CHECK_LOCAL=true removes the local-client greylist bypass:
    on the check-local stack the test-runner's network IS inside
    local_addrs, and a mid-score mail still draws the 4xx (then passes
    on retry). Pins the opt-in's effect; the default bypass direction
    cannot be reproduced in this stack (the headless containers offer
    no way to originate mail from inside local_addrs of the main
    instance), which is documented here as the technical limit."""
    sender = f"grey-local-{unique_subject.lower()}@{DOMAIN}"
    raw = (f"X-Spam-Flag: YES\r\n"
           + build_message(f"grey-local-{unique_subject}",
                           from_=sender)).encode()

    def _attempt() -> int:
        try:
            with smtplib.SMTP(POSTFIX_CHECKLOCAL, SMTP_P, timeout=15) as s:
                s.ehlo(f"testhost.{DOMAIN}")
                s.mail(sender)
                s.rcpt(ALICE)
                code, _ = s.data(raw)
                return code
        except smtplib.SMTPResponseException as e:
            return e.smtp_code

    first = _attempt()
    assert 400 <= first < 500, (
        f"check-local stack did not greylist a local client's mid-score "
        f"mail (got {first}) — RSPAMD_CHECK_LOCAL is not effective"
    )
    time.sleep(GREYLIST_RETRY_DELAY)
    second = _attempt()
    assert 200 <= second < 300, (
        f"greylisted mail was not accepted on retry (got {second})"
    )


def test_authenticated_submission_not_greylisted(unique_subject):
    """SASL-authenticated submission must NEVER be greylisted.

    Pinned by rspamd/greylist.conf `check_authed = false` (the same
    guarantee the retired milter-greylist config gave via
    `racl whitelist auth`)."""
    sender  = f"auth-{unique_subject.lower()}@{DOMAIN}"
    subject = f"grey-auth-{unique_subject}"
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        # postfix offers SASL only over TLS (smtpd_tls_auth_only), so
        # authenticate over STARTTLS like a real submission client.
        s.starttls(context=_insecure_ctx())
        s.ehlo(f"testhost.{DOMAIN}")
        s.login(ALICE, ALICE_PW)
        result = s.sendmail(sender, [BOB], build_message(subject, from_=sender, to=BOB))
    assert result == {}, f"Authenticated submission was greylisted: {result!r}"
