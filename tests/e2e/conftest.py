"""Shared fixtures: connection details + wait-for-service helpers."""
import os
import socket
import ssl
import time
import imaplib
import poplib
import smtplib
import email.mime.text
import urllib.request
import uuid

import pytest


# dovecot forbids cleartext auth by default (auth_allow_cleartext=no), so
# every login must run over TLS. The e2e certs-init container provides a
# self-signed cert, so a non-verifying context is used for the handshake.
def insecure_tls_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def imap_starttls(host: str | None = None):
    """A connected IMAP4 with STARTTLS already negotiated — ready for
    .login(). Use instead of imaplib.IMAP4(...) everywhere auth follows.
    Defaults to the main dovecot; pass a host for the mode-specific
    services (dovecot-quota, dovecot-mark, dovecot-folder)."""
    conn = imaplib.IMAP4(host or DOVECOT, IMAP_P)
    conn.starttls(ssl_context=insecure_tls_ctx())
    return conn


def pop3_stls():
    """A connected POP3 with STLS already negotiated — ready for USER/PASS."""
    conn = poplib.POP3(DOVECOT, POP3_P)
    conn.stls(context=insecure_tls_ctx())
    return conn


# ----------------------------------------------------------------- Config ---

POSTFIX        = os.environ.get("POSTFIX_HOST",         "postfix")
POSTFIX_STRICT = os.environ.get("POSTFIX_STRICT_HOST",  "postfix-strict")
POSTFIX_LOG    = os.environ.get("POSTFIX_LOG_HOST",     "postfix-log")
POSTFIX_NOCERT = os.environ.get("POSTFIX_NOCERT_HOST",  "postfix-nocert")
POSTFIX_NOCERT_CLEAR = os.environ.get("POSTFIX_NOCERT_CLEAR_HOST",
                                      "postfix-nocert-clear")
POSTFIX_CHECKLOCAL = os.environ.get("POSTFIX_CHECKLOCAL_HOST",
                                    "postfix-checklocal")
POSTFIX_TLSREQ = os.environ.get("POSTFIX_TLSREQ_HOST",  "postfix-tlsreq")
DOVECOT        = os.environ.get("DOVECOT_HOST",         "dovecot")
DOVECOT_QUOTA  = os.environ.get("DOVECOT_QUOTA_HOST",   "dovecot-quota")
DOVECOT_MARK   = os.environ.get("DOVECOT_MARK_HOST",    "dovecot-mark")
DOVECOT_FOLDER = os.environ.get("DOVECOT_FOLDER_HOST",  "dovecot-folder")
DOVECOT_CLEAR  = os.environ.get("DOVECOT_CLEARTEXT_HOST", "dovecot-cleartext")
DOVECOT_PASSSCHEME = os.environ.get("DOVECOT_PASSSCHEME_HOST",
                                    "dovecot-passscheme")
RSPAMD         = os.environ.get("RSPAMD_HOST",          "rspamd")
RSPAMD_STRICT  = os.environ.get("RSPAMD_STRICT_HOST",   "rspamd-strict")
RSPAMD_LOG     = os.environ.get("RSPAMD_LOG_HOST",      "rspamd-log")
SMTP_P    = int(os.environ.get("SMTP_PORT",     "25"))
SUBM_P    = int(os.environ.get("SUBMISSION_PORT", "587"))
SMTPS_P   = int(os.environ.get("SMTPS_PORT",    "465"))
IMAP_P    = int(os.environ.get("IMAP_PORT",    "143"))
POP3_P    = int(os.environ.get("POP3_PORT",    "110"))
SIEVE_P   = int(os.environ.get("SIEVE_PORT", "4190"))
RSPAMD_P    = int(os.environ.get("RSPAMD_PORT",     "11332"))
RSPAMD_CP   = int(os.environ.get("RSPAMD_CTL_PORT", "11334"))
DOMAIN    = os.environ.get("MAIL_DOMAIN",   "test.local")
ALICE     = os.environ.get("ALICE_USER",    f"alice@{DOMAIN}")
ALICE_PW  = os.environ.get("ALICE_PASS",    "alicepass12")
BOB       = os.environ.get("BOB_USER",      f"bob@{DOMAIN}")
BOB_PW    = os.environ.get("BOB_PASS",      "bobpass12")
# small-quota mailbox for the quota-enforcement tests (dovecot-quota)
CHARLIE   = os.environ.get("CHARLIE_USER",  f"charlie@{DOMAIN}")
CHARLIE_PW = os.environ.get("CHARLIE_PASS", "charliepass12")
CHARLIE_QUOTA_MB = 1
SENDER    = f"sender@{DOMAIN}"

# PostfixAdmin access (used to provision the mail domain and users)
PA_URL      = os.environ.get("POSTFIXADMIN_URL", "http://postfixadmin-proxy:8080")
SETUP_PW    = os.environ.get("SETUP_PASS",   "test123")
ADMIN_EMAIL = os.environ.get("ADMIN_USER",   f"admin@{DOMAIN}")
ADMIN_PW    = os.environ.get("ADMIN_PASS",   "Admin123pass")

# SnappyMail access (webmail UI tests)
SM_URL        = os.environ.get("SNAPPYMAIL_URL", "http://snappymail-proxy:8080")
SM_ADMIN_USER = os.environ.get("SM_ADMIN_USER",  "admin")
SM_ADMIN_PW   = os.environ.get("SM_ADMIN_PASS",  "12345")


# ----------------------------------------------------------- Helpers -------

def wait_for_port(host: str, port: int, timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return
        except OSError:
            time.sleep(1)
    raise TimeoutError(f"{host}:{port} did not become ready within {timeout}s")


def wait_for_http(url: str, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status < 500:
                    return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"{url} not ready after {timeout}s")


def build_message(subject: str, body: str = "test body",
                  from_: str = SENDER, to: str = ALICE) -> str:
    msg = email.mime.text.MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = from_
    msg["To"]      = to
    msg["Message-ID"] = f"<{uuid.uuid4()}@{DOMAIN}>"
    return msg.as_string()


def lmtp_deliver(host: str, rcpt: str, raw: bytes,
                 sender: str = SENDER) -> tuple[int, str]:
    """Deliver a mail to a dovecot service over LMTP (port 24) and return
    the (code, text) the server gives after DATA — the exact interface
    postfix uses for final delivery. Uses smtplib.LMTP, which speaks LHLO
    and handles the multi-line greeting correctly."""
    helo = f"tester.{DOMAIN}"
    with smtplib.LMTP(host, 24, local_hostname=helo, timeout=20) as s:
        s.ehlo(helo)                                 # LHLO
        s.mail(sender)
        code, resp = s.rcpt(rcpt)
        if code >= 400:
            return code, resp.decode(errors="replace")
        code, resp = s.data(raw)                     # final per-recipient reply
        return code, resp.decode(errors="replace")


# rspamd greylisting is score-based: a mail with mildly-suspicious
# signals (the test HELO alone scores 3.0) can cross the greylist
# threshold and get a 451. A real MTA queues and retries — the test
# sender does the same. The e2e stack runs RSPAMD_GREYLIST_TIMEOUT=5s.
GREYLIST_RETRY_DELAY = 6


def _tempfail_code(exc: Exception):
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return list(exc.recipients.values())[0][0]
    return getattr(exc, "smtp_code", None)


def send_raw(host: str, sender: str, to: str, raw: bytes,
             helo: str | None = None, retries: int = 2):
    """Low-level mail/rcpt/data submission returning (accepted, resp).

    4xx tempfails (greylisting) are retried after the greylist delay,
    like any real MTA; a permanent 5xx (or acceptance) returns
    immediately. DATA is never attempted after a failed RCPT — that
    would trip postfix's smtpd_hard_error_limit into a 421 that masks
    the actual verdict.
    """
    last = (False, "no attempt made")
    for _ in range(retries + 1):
        tempfail = False
        try:
            with smtplib.SMTP(host, SMTP_P, timeout=15) as s:
                s.ehlo(helo or f"testhost.{DOMAIN}")
                code, resp = s.mail(sender)
                if code < 400:
                    code, resp = s.rcpt(to)
                if code < 400:
                    code, resp = s.data(raw)
                last = (200 <= code < 400, f"{code} {resp!r}")
                tempfail = 400 <= code < 500
        except smtplib.SMTPResponseException as e:
            last = (False, f"{e.smtp_code} {e.smtp_error!r}")
            tempfail = 400 <= e.smtp_code < 500
        if not tempfail:
            return last
        time.sleep(GREYLIST_RETRY_DELAY)
    return last


def smtp_send(subject: str, to: str = ALICE,
              from_: str = SENDER, body: str = "test",
              retries: int = 2) -> str:
    """Send a mail and return the subject (for IMAP search). Retries
    4xx tempfails (greylisting) after the greylist delay, like any
    real MTA; permanent errors raise immediately."""
    last = None
    for _ in range(retries + 1):
        try:
            with smtplib.SMTP(POSTFIX, SMTP_P) as s:
                s.ehlo(f"testhost.{DOMAIN}")
                s.sendmail(from_, [to], build_message(subject, body, from_, to))
            return subject
        except (smtplib.SMTPResponseException,
                smtplib.SMTPRecipientsRefused) as e:
            code = _tempfail_code(e)
            if code is None or not 400 <= code < 500:
                raise
            last = e
            time.sleep(GREYLIST_RETRY_DELAY)
    raise last


# --------------------------------------------------------- Fixtures --------

@pytest.fixture(scope="session", autouse=True)
def wait_for_services():
    wait_for_port(POSTFIX,        SMTP_P)
    wait_for_port(POSTFIX_STRICT, SMTP_P)
    wait_for_port(POSTFIX_LOG,    SMTP_P)
    wait_for_port(POSTFIX_NOCERT, SMTP_P)
    wait_for_port(POSTFIX_NOCERT_CLEAR, SMTP_P)
    wait_for_port(POSTFIX_CHECKLOCAL, SMTP_P)
    wait_for_port(POSTFIX_TLSREQ, SMTP_P)
    wait_for_port(DOVECOT, IMAP_P)
    wait_for_port(DOVECOT_QUOTA, IMAP_P)
    wait_for_port(DOVECOT_MARK, IMAP_P)
    wait_for_port(DOVECOT_FOLDER, IMAP_P)
    wait_for_port(DOVECOT_CLEAR, IMAP_P)
    wait_for_port(DOVECOT_PASSSCHEME, IMAP_P)
    wait_for_port(DOVECOT, POP3_P)
    wait_for_port(DOVECOT, SIEVE_P)
    # rspamd(-strict|-log): controller port; healthchecks in compose
    # already gate postfix startup on rspamd readiness, but tests use
    # the controller directly (bayes-learn, scan API) so wait too.
    wait_for_port(RSPAMD,        RSPAMD_CP)
    wait_for_port(RSPAMD_STRICT, RSPAMD_CP)
    wait_for_port(RSPAMD_LOG,    RSPAMD_CP)
    time.sleep(3)


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    return {**browser_type_launch_args, "args": ["--no-sandbox", "--disable-setuid-sandbox"]}


@pytest.fixture(scope="session", autouse=True)
def provision_mail_accounts(wait_for_services, browser):
    """Provision the mail domain and users through PostfixAdmin.

    The stack uses a single shared database (PostfixAdmin + Postfix + Dovecot),
    with no pre-seeded accounts — so every protocol and webmail test depends on
    this fixture creating the domain and the alice/bob mailboxes first. The
    first hit to setup.php also creates the database schema the mail servers
    read from.
    """
    wait_for_http(f"{PA_URL}/setup.php")
    page = browser.new_page()

    # setup.php — authenticate, then create the superadmin (two-step flow)
    page.goto(f"{PA_URL}/setup.php", timeout=30_000)
    page.locator("form[name=authenticate] [name=setup_password]").fill(SETUP_PW)
    page.locator("form[name=authenticate] button[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)
    if page.locator("form[name=create_admin]").count():
        page.locator("form[name=create_admin] [name=setup_password]").fill(SETUP_PW)
        page.locator("form[name=create_admin] [name=username]").fill(ADMIN_EMAIL)
        page.locator("form[name=create_admin] [name=password]").fill(ADMIN_PW)
        page.locator("form[name=create_admin] [name=password2]").fill(ADMIN_PW)
        page.locator("form[name=create_admin] [type=submit]").click()
        page.wait_for_load_state("networkidle", timeout=15_000)

    # log in as the superadmin
    page.goto(f"{PA_URL}/login.php", timeout=20_000)
    page.locator("[name=fUsername]").fill(ADMIN_EMAIL)
    page.locator("[name=fPassword]").fill(ADMIN_PW)
    page.locator("[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)

    # create the mail domain
    page.goto(f"{PA_URL}/edit.php?table=domain", timeout=15_000)
    page.locator("[name='value[domain]']").fill(DOMAIN)
    page.locator("[type=submit]").first.click()
    page.wait_for_load_state("networkidle", timeout=10_000)

    # create the mailboxes (passwords must satisfy PostfixAdmin's policy:
    # >=5 chars, >=3 letters, >=2 digits). alice/bob are unlimited;
    # charlie has a small quota for the quota-enforcement tests.
    for local_part, password, quota_mb in (
        ("alice", ALICE_PW, 0),
        ("bob", BOB_PW, 0),
        ("charlie", CHARLIE_PW, CHARLIE_QUOTA_MB),
    ):
        page.goto(f"{PA_URL}/edit.php?table=mailbox", timeout=15_000)
        page.locator("[name='value[local_part]']").fill(local_part)
        page.locator("select[name='value[domain]']").select_option(DOMAIN)
        page.locator("[name='value[name]']").fill(local_part.capitalize())
        page.locator("[name='value[password]']").fill(password)
        page.locator("[name='value[password2]']").fill(password)
        quota_field = page.locator("[name='value[quota]']")
        if quota_field.count():
            quota_field.fill(str(quota_mb))
        page.locator("[type=submit]").first.click()
        page.wait_for_load_state("networkidle", timeout=10_000)

    page.close()


@pytest.fixture(scope="session")
def sm_domain_ready(provision_mail_accounts, browser):
    """Configure the test.local domain in SnappyMail admin (once per
    session) — shared by the webmail UI tests (test_webui.py) and the
    OpenPGP flow (test_openpgp.py)."""
    page = browser.new_page()
    page.goto(f"{SM_URL}/?admin", timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=20_000)

    # Admin login form — Login field has required attribute, must be filled
    page.locator("input[name='Login']").fill(SM_ADMIN_USER)
    page.locator("input[type=password]").fill(SM_ADMIN_PW)
    page.locator("button.buttonLogin").click()
    page.wait_for_load_state("networkidle", timeout=15_000)

    # Navigate to Domains tab via href (more reliable than text lookup)
    page.locator("a[href='#/domains']").click()
    page.wait_for_load_state("networkidle", timeout=10_000)

    # Add Domain is an <a> element (not a button)
    page.locator("a[data-bind*='createDomain']").first.click()
    page.wait_for_timeout(500)

    # Fill IMAP/SMTP hosts BEFORE the domain Name to avoid the imapHostFocus
    # auto-fill (which sets the host to the domain name when host is empty)
    page.locator("input[name='IMAP[host]']").fill(DOVECOT)
    page.locator("input[name='IMAP[port]']").fill("143")

    # Switch to SMTP tab, then fill SMTP settings. Focusing the *empty* SMTP host
    # triggers SnappyMail's smtpHostFocus binding, which mirrors the IMAP host
    # into it (imap→smtp). A single fill then races and yields "dovecotpostfix".
    # Fill once to make it non-empty (disabling the auto-fill), then set it again.
    page.locator("label[for='tab-smtp']").click()
    smtp_host = page.locator("input[name='SMTP[host]']")
    smtp_host.fill("postfix")
    smtp_host.fill("postfix")
    page.locator("input[name='SMTP[port]']").fill("25")

    # Fill domain Name last — hosts are already set so auto-fill won't overwrite
    page.locator("input[name='Name']").fill(DOMAIN)

    # Save is also an <a> element (not a button)
    page.locator("footer a[data-bind*='createOrAddCommand']").click()
    page.wait_for_load_state("networkidle", timeout=10_000)
    page.close()


@pytest.fixture
def imap_alice():
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        yield conn


@pytest.fixture
def unique_subject():
    return f"E2E-{uuid.uuid4()}"
