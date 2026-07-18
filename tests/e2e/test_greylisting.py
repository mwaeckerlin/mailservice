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

The delay/retry mechanics of the greylist action itself (4xx then
accept) only ever apply to mid-score mail; no deterministic payload
exists for that score band (GTUBE forces reject, clean mail scores
~0), so that path is covered by rspamd upstream, not e2e.
"""
import imaplib
import smtplib
import ssl
import time

from conftest import (
    POSTFIX, SMTP_P, DOVECOT, IMAP_P, ALICE, ALICE_PW, BOB, DOMAIN,
    build_message, imap_starttls,
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
