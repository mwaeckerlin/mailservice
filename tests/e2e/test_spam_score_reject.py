"""Antispam scoring — GTUBE payload must push the score above the reject
threshold and produce an SMTP 5xx.

The Generic Test for Unsolicited Bulk Email (GTUBE) is the antispam
equivalent of EICAR: a 68-character string that every spam filter
recognises and scores at 1000 by convention. It exists exactly for
this kind of end-to-end verification — a real spam message would be
much harder to reproducibly manufacture.

If this test ever passes «mail accepted», rspamd's scoring pipeline is
broken (GTUBE plugin disabled, actions.conf misconfigured, milter not
wired, …). The `permissive` postfix (rspamd DKIM_DMARC=permissive) is
the right entry point: a legitimate spammer never uses SASL-auth, so
we rely on the RFC1918-external-from-the-postfix-POV codepath.
"""
import smtplib
import uuid

from conftest import POSTFIX, SMTP_P, DOMAIN, ALICE, send_raw


GTUBE = (
    "XJS*C4JDBQADN1.NSBN3*2IDNEN*GTUBE-STANDARD-ANTI-UBE-TEST-EMAIL*C.34X"
)


def _send_gtube(subject: str) -> tuple[bool, str]:
    sender = f"spammer@{DOMAIN}"
    raw = (
        f"From: {sender}\r\n"
        f"To: {ALICE}\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: <{uuid.uuid4()}@{DOMAIN}>\r\n"
        f"Date: Fri, 17 Jul 2026 12:00:00 +0000\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=us-ascii\r\n"
        f"\r\n"
        f"{GTUBE}\r\n"
    ).encode("ascii")
    return send_raw(POSTFIX, sender, ALICE, raw)


def test_gtube_spam_rejected():
    """Sending the GTUBE payload must produce a 5xx from postfix at
    DATA time. Any 2xx here means rspamd's scoring pipeline is broken
    or the reject-threshold action is not wired to the milter."""
    subject = f"E2E-GTUBE-{uuid.uuid4()}"
    accepted, resp = _send_gtube(subject)
    # postfix's aggressive `smtpd_hard_error_limit=1` collapses the
    # milter's 5xx into a `421 too many errors` towards the client, so
    # only the observable outcome (not accepted) is asserted — the
    # specific code/reason varies with the error-limit bookkeeping.
    assert not accepted, (
        f"GTUBE spam payload was ACCEPTED — rspamd's scoring pipeline "
        f"is not enforcing the reject action. SMTP resp: {resp!r}"
    )


def test_clean_mail_not_rejected():
    """A trivially clean mail (short, plain, no spam signals) from the
    same permissive postfix must reach INBOX. Sanity guard against a
    misconfiguration where the reject threshold is 0 and everything
    gets 5xx."""
    subject = f"E2E-CLEAN-{uuid.uuid4()}"
    sender = f"human@{DOMAIN}"
    raw = (
        f"From: {sender}\r\n"
        f"To: {ALICE}\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: <{uuid.uuid4()}@{DOMAIN}>\r\n"
        f"Date: Fri, 17 Jul 2026 12:00:00 +0000\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=us-ascii\r\n"
        f"\r\n"
        f"Hi Alice, just a short note.\r\n"
    ).encode("ascii")
    with smtplib.SMTP(POSTFIX, SMTP_P, timeout=15) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        result = s.sendmail(sender, [ALICE], raw)
    assert result == {}, (
        f"Clean mail was rejected by the permissive postfix — reject "
        f"threshold is likely misconfigured too low. sendmail rc: {result!r}"
    )
