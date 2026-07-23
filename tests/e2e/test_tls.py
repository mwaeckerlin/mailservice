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
import email
import imaplib
import poplib
import smtplib
import ssl
import time
import uuid

from conftest import (
    POSTFIX, POSTFIX_NOCERT, POSTFIX_NOCERT_CLEAR, POSTFIX_TLSREQ,
    SMTP_P, SUBM_P, SMTPS_P,
    DOVECOT, DOVECOT_CLEAR, IMAP_P, POP3_P, ALICE, ALICE_PW, BOB, BOB_PW,
    DOMAIN, build_message, smtp_send, imap_starttls,
)

IMAPS_P = 993
POP3S_P = 995


def _insecure_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _wait_for_mail(conn: imaplib.IMAP4, subject: str, retries: int = 12):
    for _ in range(retries):
        conn.select("INBOX")
        typ, data = conn.search(None, f'SUBJECT "{subject}"')
        if typ == "OK" and data[0]:
            return data[0].split()
        time.sleep(1)
    return []


def _fetch(conn: imaplib.IMAP4, msg_id: bytes) -> email.message.Message:
    _, raw = conn.fetch(msg_id, "(RFC822)")
    return email.message_from_bytes(raw[0][1])


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


def test_submission_587_requires_auth():
    """The dedicated submission service (587) accepts an authenticated
    STARTTLS submission but refuses an UNauthenticated one — the MX role
    (anonymous, port 25) and the submission role are cleanly separated."""
    # authenticated submission over STARTTLS succeeds
    subject = f"E2E-SUBM-{uuid.uuid4()}"
    with smtplib.SMTP(POSTFIX, SUBM_P, timeout=15) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        assert s.has_extn("starttls"), "submission 587 did not offer STARTTLS"
        s.starttls(context=_insecure_ctx())
        s.ehlo(f"testhost.{DOMAIN}")
        s.login(ALICE, ALICE_PW)
        result = s.sendmail(
            ALICE, [BOB], build_message(subject, from_=ALICE, to=BOB)
        )
    assert result == {}, f"authenticated submission on 587 failed: {result!r}"

    # an UNauthenticated submission of the same shape must be rejected
    with smtplib.SMTP(POSTFIX, SUBM_P, timeout=15) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.starttls(context=_insecure_ctx())
        s.ehlo(f"testhost.{DOMAIN}")
        code, resp = s.docmd("MAIL", f"FROM:<{ALICE}>")
        if code < 400:
            code, resp = s.docmd("RCPT", f"TO:<{BOB}>")
        assert code >= 500, (
            f"submission 587 accepted an unauthenticated sender: {code} {resp!r}"
        )


def test_submission_587_refuses_cleartext_auth():
    """Submission enforces TLS: AUTH must not be offered before STARTTLS,
    so a password can never be sent in the clear on 587."""
    with smtplib.SMTP(POSTFIX, SUBM_P, timeout=15) as s:
        code, _ = s.ehlo(f"testhost.{DOMAIN}")
        assert code == 250
        assert not s.has_extn("auth"), (
            "submission 587 advertised AUTH before STARTTLS — cleartext "
            "credentials possible"
        )


def test_smtps_465_wrappermode_submission():
    """The implicit-TLS submission service (465, smtps) authenticates and
    accepts mail over a TLS-from-connect channel (RFC 8314)."""
    subject = f"E2E-SMTPS-{uuid.uuid4()}"
    with smtplib.SMTP_SSL(POSTFIX, SMTPS_P, context=_insecure_ctx(),
                          timeout=15) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.login(ALICE, ALICE_PW)
        result = s.sendmail(
            ALICE, [BOB], build_message(subject, from_=ALICE, to=BOB)
        )
    assert result == {}, f"smtps submission on 465 failed: {result!r}"


def test_transport_security_header_plaintext():
    """A mail received over a plaintext hop carries
    `X-Transport-Security: none` — rspamd stamps the last-hop transport
    from the postfix TLS macros. This is what makes cleartext delivery
    visible (the webmail marks it)."""
    subject = smtp_send(f"E2E-XTS-none-{uuid.uuid4()}")  # plaintext, port 25
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, subject)
        assert msgs, f"mail '{subject}' not delivered"
        msg = _fetch(conn, msgs[0])
    xts = msg.get("X-Transport-Security", "")
    assert xts.strip().lower() == "none", (
        f"expected X-Transport-Security: none for a cleartext hop, got "
        f"{xts!r}. All headers:\n{dict(msg)}"
    )


def test_transport_security_header_not_forgeable():
    """A sender-supplied X-Transport-Security header is stripped and
    replaced with the real last-hop value — otherwise a cleartext mail
    could claim `TLSv1.3` and hide from the webmail marker."""
    subject = f"E2E-XTS-forge-{uuid.uuid4()}"
    msg = build_message(subject)
    # inject a forged header at the top of the message
    forged = f"X-Transport-Security: TLSv1.3 (cipher FORGED)\r\n{msg}"
    for _ in range(3):
        try:
            with smtplib.SMTP(POSTFIX, SMTP_P, timeout=15) as s:
                s.ehlo(f"testhost.{DOMAIN}")
                code, resp = s.mail("outsider@external.local")
                if code < 400:
                    code, resp = s.rcpt(ALICE)
                if code < 400:
                    code, resp = s.data(forged.encode())
            if code < 400:
                break
        except smtplib.SMTPResponseException:
            pass
        time.sleep(6)
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        msgs = _wait_for_mail(conn, subject)
        assert msgs, f"mail '{subject}' not delivered"
        msg_obj = _fetch(conn, msgs[0])
    values = msg_obj.get_all("X-Transport-Security", [])
    assert "FORGED" not in " ".join(values), (
        f"forged X-Transport-Security survived: {values!r}"
    )
    assert values and values[-1].strip().lower() == "none", (
        f"expected the real header value 'none', got {values!r}"
    )


def test_transport_security_header_tls():
    """A mail submitted over STARTTLS carries a TLS version in
    `X-Transport-Security` — proving the header reflects real transport."""
    subject = f"E2E-XTS-tls-{uuid.uuid4()}"
    with smtplib.SMTP(POSTFIX, SUBM_P, timeout=15) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.starttls(context=_insecure_ctx())
        s.ehlo(f"testhost.{DOMAIN}")
        s.login(ALICE, ALICE_PW)
        s.sendmail(ALICE, [BOB], build_message(subject, from_=ALICE, to=BOB))
    with imap_starttls() as conn:
        conn.login(BOB, BOB_PW)
        msgs = _wait_for_mail(conn, subject)
        assert msgs, f"mail '{subject}' not delivered to bob"
        msg = _fetch(conn, msgs[0])
    xts = msg.get("X-Transport-Security", "")
    assert "TLS" in xts.upper(), (
        f"expected a TLS version in X-Transport-Security, got {xts!r}. "
        f"All headers:\n{dict(msg)}"
    )


def test_tls_required_rejects_cleartext():
    """With SMTPD_TLS_REQUIRED=yes the MX rejects a plaintext delivery
    (no STARTTLS) — the opt-in reject mode. A `MAIL FROM` before STARTTLS
    must get a permanent 5xx («Must issue a STARTTLS command first»)."""
    with smtplib.SMTP(POSTFIX_TLSREQ, SMTP_P, timeout=15) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        code, resp = s.docmd("MAIL", f"FROM:<outsider@external.local>")
        assert code >= 500, (
            f"TLS-required MX accepted a cleartext MAIL FROM: {code} {resp!r}"
        )


def test_tls_required_accepts_over_tls():
    """The same TLS-required MX still accepts a delivery once the client
    upgrades to STARTTLS — proving the reject is about transport, not a
    general outage."""
    with smtplib.SMTP(POSTFIX_TLSREQ, SMTP_P, timeout=15) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        assert s.has_extn("starttls"), "TLS-required MX did not offer STARTTLS"
        s.starttls(context=_insecure_ctx())
        code, _ = s.ehlo(f"testhost.{DOMAIN}")
        assert code == 250
        code, resp = s.docmd("MAIL", f"FROM:<outsider@external.local>")
        assert code < 400, (
            f"TLS-required MX rejected a MAIL FROM over TLS: {code} {resp!r}"
        )


def test_imaps_login_on_993():
    """dovecot accepts an implicit-TLS IMAPS login on 993."""
    with imaplib.IMAP4_SSL(DOVECOT, IMAPS_P, ssl_context=_insecure_ctx()) as conn:
        typ, _ = conn.login(ALICE, ALICE_PW)
        assert typ == "OK", "IMAPS login on 993 failed"
        typ, _ = conn.select("INBOX")
        assert typ == "OK"


def test_cleartext_auth_optin_smtp():
    """POSTFIX_ALLOW_CLEARTEXT_AUTH=yes on a certless stack: the
    documented deliberate softening actually opens SASL without TLS —
    AUTH is advertised and a login with valid credentials succeeds on
    the opt-in service (the secure default refuses both, pinned by
    test_smtp_auth_disabled_without_cert)."""
    with smtplib.SMTP(POSTFIX_NOCERT_CLEAR, SMTP_P, timeout=15) as s:
        code, _ = s.ehlo(f"testhost.{DOMAIN}")
        assert code == 250
        assert s.has_extn("auth"), (
            "opt-in service does not advertise AUTH without TLS — "
            "POSTFIX_ALLOW_CLEARTEXT_AUTH is not effective"
        )
        s.login(ALICE, ALICE_PW)


def test_cleartext_optin_imap_login():
    """DOVECOT_ALLOW_CLEARTEXT=yes on a certless stack: the documented
    deliberate softening actually opens the cleartext path — an IMAP
    login WITHOUT any TLS succeeds on the opt-in service (the same login
    is refused on the main dovecot, pinned by
    test_imap.py::test_imap_cleartext_login_refused_without_tls)."""
    with imaplib.IMAP4(DOVECOT_CLEAR, IMAP_P) as conn:
        typ, _ = conn.login(ALICE, ALICE_PW)
        assert typ == "OK", "cleartext opt-in IMAP login failed"
        typ, _ = conn.select("INBOX")
        assert typ == "OK"


def test_cleartext_optin_pop3_login():
    """Same opt-in on POP3: USER/PASS without STLS succeeds on the
    cleartext service (refused on the main dovecot, pinned by
    test_pop3.py::test_pop3_cleartext_login_refused_without_stls)."""
    conn = poplib.POP3(DOVECOT_CLEAR, POP3_P)
    try:
        assert conn.user(ALICE).startswith(b"+OK")
        assert conn.pass_(ALICE_PW).startswith(b"+OK")
    finally:
        conn.quit()


def test_pop3s_login_on_995():
    """dovecot accepts an implicit-TLS POP3S login on 995 — the published
    wrapper-mode counterpart to IMAPS (the STARTTLS path on 110 is
    covered by test_pop3.py)."""
    conn = poplib.POP3_SSL(DOVECOT, POP3S_P, context=_insecure_ctx())
    try:
        assert conn.user(ALICE).startswith(b"+OK")
        assert conn.pass_(ALICE_PW).startswith(b"+OK")
    finally:
        conn.quit()


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
