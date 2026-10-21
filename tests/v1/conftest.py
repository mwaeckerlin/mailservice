"""Fixtures for the version-1 line: connection details, waiting, accounts.

The accounts are created through the PostfixAdmin web interface, the way
an operator creates them — the first call of setup.php also creates the
database schema postfix and dovecot read from, so nothing here seeds the
database behind the application's back.
"""
import email.mime.text
import imaplib
import os
import socket
import ssl
import time
import urllib.request
import uuid

import pytest

POSTFIX = os.environ.get("POSTFIX_HOST", "postfix")
DOVECOT = os.environ.get("DOVECOT_HOST", "dovecot")
SMTP_P = int(os.environ.get("SMTP_PORT", "25"))
IMAP_P = int(os.environ.get("IMAP_PORT", "143"))

DOMAIN = os.environ.get("MAIL_DOMAIN", "test.local")
ALICE = os.environ.get("ALICE_USER", f"alice@{DOMAIN}")
ALICE_PW = os.environ.get("ALICE_PASS", "alicepass12")
BOB = os.environ.get("BOB_USER", f"bob@{DOMAIN}")
BOB_PW = os.environ.get("BOB_PASS", "bobpass12")

PA_URL = os.environ.get("POSTFIXADMIN_URL", "http://postfixadmin-proxy:8080")
SETUP_PW = os.environ.get("SETUP_PASS", "test123")
ADMIN_EMAIL = os.environ.get("ADMIN_USER", f"admin@{DOMAIN}")
ADMIN_PW = os.environ.get("ADMIN_PASS", "Admin123pass")

SM_URL = os.environ.get("SNAPPYMAIL_URL", "http://snappymail-proxy:8080")

EXTERNAL_RCPT = os.environ.get("EXTERNAL_RCPT", "sink@extern.local")
FAKE_MAILS_DIR = os.environ.get("FAKE_MAILS_DIR", "/fake-mails")


def insecure_tls_ctx() -> ssl.SSLContext:
    """The stack's certificate is self-signed on purpose — the subject of
    these tests is the mail path, not a chain of trust."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def imap_starttls(host: str | None = None) -> imaplib.IMAP4:
    """A connected IMAP4 with STARTTLS negotiated, ready for .login()."""
    conn = imaplib.IMAP4(host or DOVECOT, IMAP_P)
    conn.starttls(ssl_context=insecure_tls_ctx())
    return conn


def wait_for_port(host: str, port: int, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return
        except OSError as exc:
            last = exc
            time.sleep(1)
    raise TimeoutError(f"{host}:{port} not reachable within {timeout}s ({last})")


def wait_for_http(url: str, timeout: int = 180) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status < 500:
                    return
        except Exception as exc:
            last = exc
        time.sleep(2)
    raise TimeoutError(f"{url} not ready after {timeout}s ({last})")


def build_message(subject: str, body: str, from_: str, to: str) -> str:
    msg = email.mime.text.MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_
    msg["To"] = to
    return msg.as_string()


@pytest.fixture(scope="session")
def wait_for_services():
    wait_for_port(POSTFIX, SMTP_P)
    wait_for_port(DOVECOT, IMAP_P)
    # setup.php, never login.php: the database starts empty, and
    # login.php answers 500 until setup.php has created the schema —
    # waiting for it would wait for a page that cannot work yet.
    wait_for_http(f"{PA_URL}/setup.php")
    wait_for_http(SM_URL)


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    return {**browser_type_launch_args,
            "args": ["--no-sandbox", "--disable-setuid-sandbox"]}


@pytest.fixture(scope="session", autouse=True)
def provision_mail_accounts(wait_for_services, browser):
    """Create the mail domain and the two mailboxes in PostfixAdmin.

    The stack shares one database between PostfixAdmin, postfix and
    dovecot, exactly as production does, and starts with an empty one:
    opening setup.php creates the schema, then the superadmin, then the
    domain and the mailboxes.
    """
    wait_for_http(f"{PA_URL}/setup.php")
    page = browser.new_page()

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

    page.goto(f"{PA_URL}/login.php", timeout=20_000)
    page.locator("[name=fUsername]").fill(ADMIN_EMAIL)
    page.locator("[name=fPassword]").fill(ADMIN_PW)
    page.locator("[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)

    page.goto(f"{PA_URL}/edit.php?table=domain", timeout=15_000)
    page.locator("[name='value[domain]']").fill(DOMAIN)
    page.locator("[type=submit]").first.click()
    page.wait_for_load_state("networkidle", timeout=10_000)

    for local_part, password in (("alice", ALICE_PW), ("bob", BOB_PW)):
        page.goto(f"{PA_URL}/edit.php?table=mailbox", timeout=15_000)
        page.locator("[name='value[local_part]']").fill(local_part)
        page.locator("select[name='value[domain]']").select_option(DOMAIN)
        page.locator("[name='value[name]']").fill(local_part.capitalize())
        page.locator("[name='value[password]']").fill(password)
        page.locator("[name='value[password2]']").fill(password)
        quota = page.locator("[name='value[quota]']")
        if quota.count():
            quota.fill("0")
        page.locator("[type=submit]").first.click()
        page.wait_for_load_state("networkidle", timeout=10_000)

    page.close()


@pytest.fixture
def unique_subject():
    return f"V1-{uuid.uuid4()}"
