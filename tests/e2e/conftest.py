"""Shared fixtures: connection details + wait-for-service helpers."""
import os
import socket
import time
import imaplib
import smtplib
import email.mime.text
import urllib.request
import uuid

import pytest


# ----------------------------------------------------------------- Config ---

POSTFIX   = os.environ.get("POSTFIX_HOST",  "postfix")
DOVECOT   = os.environ.get("DOVECOT_HOST",  "dovecot")
OPENDKIM  = os.environ.get("OPENDKIM_HOST", "")
SMTP_P    = int(os.environ.get("SMTP_PORT",     "25"))
IMAP_P    = int(os.environ.get("IMAP_PORT",    "143"))
POP3_P    = int(os.environ.get("POP3_PORT",    "110"))
SIEVE_P   = int(os.environ.get("SIEVE_PORT", "4190"))
OPENDKIM_P = int(os.environ.get("OPENDKIM_PORT", "10026"))
DOMAIN    = os.environ.get("MAIL_DOMAIN",   "test.local")
ALICE     = os.environ.get("ALICE_USER",    f"alice@{DOMAIN}")
ALICE_PW  = os.environ.get("ALICE_PASS",    "alicepass12")
BOB       = os.environ.get("BOB_USER",      f"bob@{DOMAIN}")
BOB_PW    = os.environ.get("BOB_PASS",      "bobpass12")
SENDER    = f"sender@{DOMAIN}"

# PostfixAdmin access (used to provision the mail domain and users)
PA_URL      = os.environ.get("POSTFIXADMIN_URL", "http://postfixadmin-proxy:8080")
SETUP_PW    = os.environ.get("SETUP_PASS",   "test123")
ADMIN_EMAIL = os.environ.get("ADMIN_USER",   f"admin@{DOMAIN}")
ADMIN_PW    = os.environ.get("ADMIN_PASS",   "Admin123pass")


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


def smtp_send(subject: str, to: str = ALICE,
              from_: str = SENDER, body: str = "test") -> str:
    """Send a mail and return the subject (for IMAP search)."""
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.sendmail(from_, [to], build_message(subject, body, from_, to))
    return subject


# --------------------------------------------------------- Fixtures --------

@pytest.fixture(scope="session", autouse=True)
def wait_for_services():
    wait_for_port(POSTFIX, SMTP_P)
    wait_for_port(DOVECOT, IMAP_P)
    wait_for_port(DOVECOT, POP3_P)
    wait_for_port(DOVECOT, SIEVE_P)
    # opendkim: guaranteed healthy by docker-compose before postfix starts;
    # test-runner does not need direct access to port 10026.
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
    # >=5 chars, >=3 letters, >=2 digits)
    for local_part, password in (("alice", ALICE_PW), ("bob", BOB_PW)):
        page.goto(f"{PA_URL}/edit.php?table=mailbox", timeout=15_000)
        page.locator("[name='value[local_part]']").fill(local_part)
        page.locator("select[name='value[domain]']").select_option(DOMAIN)
        page.locator("[name='value[name]']").fill(local_part.capitalize())
        page.locator("[name='value[password]']").fill(password)
        page.locator("[name='value[password2]']").fill(password)
        page.locator("[type=submit]").first.click()
        page.wait_for_load_state("networkidle", timeout=10_000)

    page.close()


@pytest.fixture
def imap_alice():
    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        conn.login(ALICE, ALICE_PW)
        yield conn


@pytest.fixture
def unique_subject():
    return f"E2E-{uuid.uuid4()}"
