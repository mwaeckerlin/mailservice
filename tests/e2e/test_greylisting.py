"""Greylisting tests via milter-greylist.

milter-greylist delays mail from unknown (sender, recipient, client-ip) tuples.
First attempt → 4xx TEMPFAIL; after the greylist delay → 250 OK.
Test docker-compose starts postgrey with `-w 5` (5 second delay).
Rejection happens at RCPT phase (SMTPRecipientsRefused with 4xx code).

Each test uses a DISTINCT sender address so tests don't share greylist state.
"""
import smtplib
import time
import imaplib
import pytest
from conftest import POSTFIX, SMTP_P, DOVECOT, IMAP_P, ALICE, ALICE_PW, DOMAIN, build_message


GREYLIST_SENDER       = f"greylister@{DOMAIN}"         # used only by test_greylisting_first_attempt_rejected
GREYLIST_SENDER_RETRY = f"greylister-retry@{DOMAIN}"   # used only by test_greylisting_retry_succeeds
GREYLIST_WAIT         = 15  # seconds: must exceed greylist delay (5s) + milter overhead

# Milter rejects at RCPT phase; collect both possible exception types
_SMTP_TEMP_ERROR = (smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError)


def _get_error_code(exc: Exception) -> int:
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return list(exc.recipients.values())[0][0]
    return exc.smtp_code


def _wait_for_mail(subject: str, retries: int = 15) -> bool:
    for _ in range(retries):
        with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
            conn.login(ALICE, ALICE_PW)
            conn.select("INBOX")
            _, data = conn.search(None, f'SUBJECT "{subject}"')
            if data[0]:
                return True
        time.sleep(1)
    return False


def test_greylisting_first_attempt_rejected(unique_subject):
    """First delivery attempt from a new sender is temporarily rejected (4xx)."""
    subject = f"grey-first-{unique_subject}"
    msg = build_message(subject, from_=GREYLIST_SENDER)
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        with pytest.raises(_SMTP_TEMP_ERROR) as exc:
            s.sendmail(GREYLIST_SENDER, [ALICE], msg)
        code = _get_error_code(exc.value)
        assert 400 <= code < 500, f"Expected 4xx greylisting response, got {code}"


def test_greylisting_retry_succeeds(unique_subject):
    """After the greylist delay, retry from the same sender/IP is accepted."""
    subject = f"grey-retry-{unique_subject}"
    msg = build_message(subject, from_=GREYLIST_SENDER_RETRY)

    # First attempt — expect temporary rejection
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        try:
            s.sendmail(GREYLIST_SENDER_RETRY, [ALICE], msg)
        except _SMTP_TEMP_ERROR as e:
            assert 400 <= _get_error_code(e) < 500

    time.sleep(GREYLIST_WAIT)

    # Retry — must now be accepted
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        result = s.sendmail(GREYLIST_SENDER_RETRY, [ALICE], msg)
    assert result == {}, f"Retry was not accepted: {result}"

    # Mail must arrive in INBOX
    assert _wait_for_mail(subject), f"Greylisted mail never arrived after retry"


def test_greylisting_known_sender_not_delayed(unique_subject):
    """Once a triplet passes greylisting, subsequent mails are auto-whitelisted.

    milter-greylist -A -a 1: after the first successful retry, an auto-whitelist
    entry (duration 1 day) is created.  The very next message from the same
    (client_ip, sender, recipient) must be accepted without any delay.
    """
    sender   = f"established@{DOMAIN}"
    subject1 = f"grey-whitelist-1-{unique_subject}"
    subject2 = f"grey-whitelist-2-{unique_subject}"

    # First mail: greylisted — expect 4xx (or accept silently if timing varies)
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        try:
            s.sendmail(sender, [ALICE], build_message(subject1, from_=sender))
        except _SMTP_TEMP_ERROR:
            pass

    time.sleep(GREYLIST_WAIT)

    # Retry: must pass greylisting and create the auto-whitelist entry
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.sendmail(sender, [ALICE], build_message(subject1, from_=sender))

    # Second distinct mail: auto-whitelist must accept it without delay
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        result = s.sendmail(sender, [ALICE], build_message(subject2, from_=sender))
    assert result == {}, f"Auto-whitelisted sender was still greylisted: {result}"
