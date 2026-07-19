"""TLS coverage — exercises the cert-present → TLS-enabled wiring.

The e2e `certs-init` container drops a throw-away self-signed cert into
the `letsencrypt` volume at the exact path postfix/dovecot look for
(`/etc/letsencrypt/live/test.local/`). That flips on:
  - STARTTLS on the SMTP port (postfix init: smtpd_use_tls=yes),
  - IMAPS on 993 and STARTTLS on 143 (dovecot init: ssl=yes).

These are the production TLS paths that a plaintext stack cannot show.
The cert is self-signed, so every TLS handshake here uses a
non-verifying context (`CERT_NONE`) — we test that TLS is offered,
negotiates, and carries auth/mail, not that a public CA signed it (real
Let's Encrypt issuance is out of scope for a local e2e).
"""
import base64
import imaplib
import smtplib
import ssl
import uuid

from conftest import (
    POSTFIX, POSTFIX_NOCERT, SMTP_P, DOVECOT, IMAP_P, ALICE, ALICE_PW,
    BOB, DOMAIN, build_message,
)

IMAPS_P = 993


def _insecure_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def test_smtp_starttls_offered_and_negotiates():
    """postfix advertises STARTTLS on the SMTP port and the handshake
    completes — proves the cert-present branch of init enabled TLS."""
    with smtplib.SMTP(POSTFIX, SMTP_P, timeout=15) as s:
        code, _ = s.ehlo(f"testhost.{DOMAIN}")
        assert code == 250
        assert s.has_extn("starttls"), (
            "postfix did not advertise STARTTLS — TLS wiring not active "
            "(cert missing?)"
        )
        s.starttls(context=_insecure_ctx())
        # a second EHLO over the now-encrypted channel must still work
        code, _ = s.ehlo(f"testhost.{DOMAIN}")
        assert code == 250


def test_submission_auth_over_starttls():
    """A client authenticates and submits a mail over STARTTLS. This is
    the real webmail/MUA submission path (SASL only offered after TLS)."""
    subject = f"E2E-TLS-{uuid.uuid4()}"
    with smtplib.SMTP(POSTFIX, SMTP_P, timeout=15) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.starttls(context=_insecure_ctx())
        s.ehlo(f"testhost.{DOMAIN}")
        s.login(ALICE, ALICE_PW)
        result = s.sendmail(
            ALICE, [BOB], build_message(subject, from_=ALICE, to=BOB)
        )
    assert result == {}, f"Authenticated STARTTLS submission failed: {result!r}"


def test_smtp_auth_disabled_without_cert():
    """Without a TLS certificate postfix must not offer SASL at all —
    there is no STARTTLS, so any authentication would put the password
    on the wire in the clear. Pins the no-cert branch of the postfix
    init (stack invariant «passwords never travel unencrypted»; same
    behaviour as dovecot, where a certless stack has no usable login).
    Valid credentials prove the refusal is the TLS requirement, not a
    password failure. Deliberate cleartext deployments must opt in via
    POSTFIX_ALLOW_CLEARTEXT_AUTH=yes."""
    with smtplib.SMTP(POSTFIX_NOCERT, SMTP_P, timeout=15) as s:
        code, _ = s.ehlo(f"testhost.{DOMAIN}")
        assert code == 250
        assert not s.has_extn("starttls"), (
            "postfix-nocert advertised STARTTLS — test stack wired a cert?"
        )
        assert not s.has_extn("auth"), (
            "postfix advertised AUTH without TLS — credentials could be "
            "sent in the clear"
        )
        # even a forced AUTH attempt with VALID credentials must be
        # refused server-side (5xx), not just hidden from EHLO
        token = base64.b64encode(f"\0{ALICE}\0{ALICE_PW}".encode()).decode()
        code, resp = s.docmd("AUTH", "PLAIN " + token)
        assert code >= 500, (
            f"cleartext AUTH was not refused: {code} {resp!r}"
        )


def test_imaps_login_on_993():
    """dovecot accepts an implicit-TLS IMAPS login on 993."""
    with imaplib.IMAP4_SSL(DOVECOT, IMAPS_P, ssl_context=_insecure_ctx()) as conn:
        typ, _ = conn.login(ALICE, ALICE_PW)
        assert typ == "OK", "IMAPS login on 993 failed"
        typ, _ = conn.select("INBOX")
        assert typ == "OK"


def test_imap_starttls_on_143():
    """dovecot offers STARTTLS on the plain IMAP port and login works
    over the upgraded channel."""
    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        assert "STARTTLS" in conn.capabilities, (
            "dovecot did not advertise STARTTLS on 143"
        )
        conn.starttls(ssl_context=_insecure_ctx())
        typ, _ = conn.login(ALICE, ALICE_PW)
        assert typ == "OK", "IMAP login after STARTTLS failed"
