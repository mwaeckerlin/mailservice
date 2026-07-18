"""SMTP delivery and rejection tests."""
import smtplib
import ssl
import pytest
from conftest import POSTFIX, SMTP_P, ALICE, ALICE_PW, BOB, SENDER, DOMAIN, build_message


def _insecure_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def test_smtp_delivery_to_local_user(unique_subject):
    """Mail to a local mailbox is accepted (250 OK)."""
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        result = s.sendmail(SENDER, [ALICE], build_message(unique_subject))
    assert result == {}, f"Unexpected rejections: {result}"


def test_smtp_delivery_to_second_user(unique_subject):
    """Delivery works for all configured local users."""
    subject = unique_subject + "-bob"
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        result = s.sendmail(SENDER, [BOB], build_message(subject, to=BOB))
    assert result == {}


def test_smtp_relay_rejected_for_external():
    """Relaying to an external domain without auth must be rejected."""
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        with pytest.raises(smtplib.SMTPRecipientsRefused):
            s.sendmail(SENDER, ["victim@external.example"], build_message("relay-test", to="victim@external.example"))


def test_smtp_unknown_local_recipient_rejected():
    """Mail to a non-existent local address must be rejected."""
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        with pytest.raises(smtplib.SMTPRecipientsRefused):
            s.sendmail(SENDER, [f"nobody@{DOMAIN}"], build_message("no-user-test", to=f"nobody@{DOMAIN}"))


def test_smtp_sasl_auth_accepted(unique_subject):
    """Authenticated submission is accepted — over STARTTLS, because
    postfix offers SASL only on an encrypted channel
    (smtpd_tls_auth_only=yes once TLS is configured). This is the real
    webmail/MUA submission path."""
    subject = unique_subject + "-auth"
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.starttls(context=_insecure_ctx())
        s.ehlo(f"testhost.{DOMAIN}")
        s.login(ALICE, ALICE_PW)
        result = s.sendmail(ALICE, [BOB], build_message(subject, from_=ALICE, to=BOB))
    assert result == {}


def test_smtp_sasl_wrong_password_rejected():
    """Authentication with wrong password must fail (over STARTTLS)."""
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.starttls(context=_insecure_ctx())
        s.ehlo(f"testhost.{DOMAIN}")
        with pytest.raises(smtplib.SMTPAuthenticationError):
            s.login(ALICE, "wrongpassword")


def test_smtp_plaintext_auth_refused_without_tls():
    """SASL AUTH must NOT be offered on the unencrypted channel — a
    client must not be able to send credentials in the clear
    (smtpd_tls_auth_only). Pins the secure behaviour that the two tests
    above rely on."""
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        assert not s.has_extn("auth"), (
            "postfix advertised AUTH before STARTTLS — credentials could "
            "be sent in the clear"
        )
