"""Per-mailbox quota (DOVECOT_QUOTA=yes) — exercised against the
`dovecot-quota` service, which reads the per-user limit from the
PostfixAdmin `mailbox.quota` column via the sql userdb.

charlie has a 1 MB quota; alice is unlimited. The tests prove:
  1. the sql userdb authenticates (login works at all),
  2. an over-quota IMAP APPEND is refused (enforcement is real),
  3. an over-quota LMTP delivery tempfails with a 4xx — the production
     path: postfix defers and the sender retries, never a silent drop,
  4. an unlimited mailbox is unaffected.
"""
import imaplib
import ssl
import uuid

from conftest import (
    DOVECOT_QUOTA, IMAP_P, ALICE, CHARLIE, CHARLIE_PW, build_message,
    lmtp_deliver,
)

# comfortably over charlie's 1 MB quota (and over it whatever unit the
# stored value ends up in), grace is 0 so the first overage already defers
BIG_BODY = "x" * (2 * 1024 * 1024)


def _insecure_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _imap_login(user: str, password: str) -> imaplib.IMAP4:
    conn = imaplib.IMAP4(DOVECOT_QUOTA, IMAP_P)
    conn.starttls(ssl_context=_insecure_ctx())
    conn.login(user, password)
    return conn


def test_quota_sql_userdb_login_works():
    """The sql userdb (DOVECOT_QUOTA=yes) still authenticates a user —
    the userdb refactor did not break login."""
    conn = _imap_login(CHARLIE, CHARLIE_PW)
    try:
        typ, _ = conn.select("INBOX")
        assert typ == "OK"
    finally:
        conn.logout()


def test_quota_append_over_limit_refused():
    """An IMAP APPEND that exceeds charlie's quota is refused — quota
    enforcement is active, not merely tracked."""
    msg = build_message(f"E2E-QUOTA-append-{uuid.uuid4()}", body=BIG_BODY,
                        to=CHARLIE).encode()
    conn = _imap_login(CHARLIE, CHARLIE_PW)
    try:
        typ, data = conn.append("INBOX", None, None, msg)
    finally:
        conn.logout()
    text = f"{typ} {data}"
    assert typ != "OK", f"over-quota APPEND was accepted: {text}"
    assert "quota" in text.lower(), (
        f"APPEND failed but not for quota reasons: {text}"
    )


def test_quota_lmtp_over_limit_tempfails():
    """An over-quota LMTP delivery returns a 4xx temporary failure — the
    production path (postfix defers, sender retries), never a bounce or a
    silent drop. quota_full_tempfail=yes turns the enforced over-quota
    into a tempfail rather than a 5xx."""
    raw = build_message(f"E2E-QUOTA-lmtp-{uuid.uuid4()}", body=BIG_BODY,
                        to=CHARLIE).encode()
    code, text = lmtp_deliver(DOVECOT_QUOTA, CHARLIE, raw)
    assert 400 <= code < 500, (
        f"over-quota LMTP delivery was not a 4xx tempfail: {code} {text}"
    )


def test_quota_unlimited_mailbox_unaffected():
    """A mailbox without a quota (alice) accepts an equally large LMTP
    delivery — the limit applies only to mailboxes that set one."""
    raw = build_message(f"E2E-QUOTA-ok-{uuid.uuid4()}", body=BIG_BODY,
                        to=ALICE).encode()
    code, text = lmtp_deliver(DOVECOT_QUOTA, ALICE, raw)
    assert 200 <= code < 300, (
        f"unlimited mailbox rejected a large delivery: {code} {text}"
    )
