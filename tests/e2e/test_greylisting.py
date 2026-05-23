"""Greylisting tests via milter-greylist.

milter-greylist delays mail from unknown (sender, recipient, client-ip) tuples.
First attempt → 4xx TEMPFAIL; after the greylist delay → 250 OK.
Test docker-compose starts postgrey with `-w 5` (5 second delay).
"""
import smtplib
import time
import imaplib
import pytest
from conftest import POSTFIX, SMTP_P, DOVECOT, IMAP_P, ALICE, ALICE_PW, DOMAIN, build_message


GREYLIST_SENDER = f"greylister@{DOMAIN}"
GREYLIST_WAIT   = 7   # seconds to wait after initial rejection


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
        with pytest.raises(smtplib.SMTPDataError) as exc:
            s.sendmail(GREYLIST_SENDER, [ALICE], msg)
        code = exc.value.smtp_code
        assert 400 <= code < 500, f"Expected 4xx greylisting response, got {code}"


def test_greylisting_retry_succeeds(unique_subject):
    """After the greylist delay, retry from the same sender/IP is accepted."""
    subject = f"grey-retry-{unique_subject}"
    msg = build_message(subject, from_=GREYLIST_SENDER)

    # First attempt — expect temporary rejection
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        try:
            s.sendmail(GREYLIST_SENDER, [ALICE], msg)
        except smtplib.SMTPDataError as e:
            assert 400 <= e.smtp_code < 500

    time.sleep(GREYLIST_WAIT)

    # Retry — must now be accepted
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        result = s.sendmail(GREYLIST_SENDER, [ALICE], msg)
    assert result == {}, f"Retry was not accepted: {result}"

    # Mail must arrive in INBOX
    assert _wait_for_mail(subject), f"Greylisted mail never arrived after retry"


def test_greylisting_known_sender_not_delayed(unique_subject):
    """Once whitelisted (after first success), subsequent mails are not delayed."""
    subject1 = f"grey-whitelist-1-{unique_subject}"
    subject2 = f"grey-whitelist-2-{unique_subject}"
    sender   = f"established@{DOMAIN}"
    msg1 = build_message(subject1, from_=sender)
    msg2 = build_message(subject2, from_=sender)

    # First mail: greylisted then retried to establish whitelist entry
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        try:
            s.sendmail(sender, [ALICE], msg1)
        except smtplib.SMTPDataError:
            pass

    time.sleep(GREYLIST_WAIT)

    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.sendmail(sender, [ALICE], msg1)   # establishes whitelist entry

    # Second mail: should now go through immediately
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        result = s.sendmail(sender, [ALICE], msg2)
    assert result == {}, "Whitelisted sender was still greylisted"
