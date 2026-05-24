"""
Frontend UI tests: PostfixAdmin admin workflow + SnappyMail user workflow.

PostfixAdmin tests:
  setup → admin login → create domain → create mailbox

SnappyMail tests (uses alice/bob from the existing minimal DB):
  admin domain config → user login → read mail → compose and send
"""

import imaplib
import os
import time
import urllib.request
import uuid

import pytest
from playwright.sync_api import Browser, Page, expect

# ── Config ───────────────────────────────────────────────────────────────────

PA_URL      = os.environ.get("POSTFIXADMIN_URL", "http://postfixadmin-proxy:8080")
SM_URL      = os.environ.get("SNAPPYMAIL_URL",   "http://snappymail-proxy:8080")
DOVECOT     = os.environ.get("DOVECOT_HOST",     "dovecot")
IMAP_P      = int(os.environ.get("IMAP_PORT",    "143"))
ALICE       = os.environ.get("ALICE_USER",       "alice@test.local")
ALICE_PW    = os.environ.get("ALICE_PASS",       "alicepass")
BOB         = os.environ.get("BOB_USER",         "bob@test.local")
BOB_PW      = os.environ.get("BOB_PASS",         "bobpass")
DOMAIN      = os.environ.get("MAIL_DOMAIN",      "test.local")
ADMIN_EMAIL = os.environ.get("ADMIN_USER",       "admin@test.local")
ADMIN_PW    = os.environ.get("ADMIN_PASS",       "Admin123pass")
SETUP_PW    = os.environ.get("SETUP_PASS",       "test123")
SM_ADMIN_PW = os.environ.get("SM_ADMIN_PASS",    "12345")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wait_http(url: str, timeout: int = 120) -> None:
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


def _imap_messages(user: str, password: str, subject_substr: str) -> list[str]:
    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        conn.login(user, password)
        conn.select("INBOX")
        _, data = conn.search(None, f'SUBJECT "{subject_substr}"')
        ids = data[0].split()
        results = []
        for mid in ids:
            _, msg = conn.fetch(mid, "(RFC822)")
            results.append(msg[0][1].decode(errors="replace"))
        return results


# ── Session fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def wait_for_ui_services():
    _wait_http(f"{PA_URL}/public/setup.php")
    _wait_http(f"{SM_URL}/")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    return {**browser_type_launch_args, "args": ["--no-sandbox", "--disable-setuid-sandbox"]}


@pytest.fixture(scope="session")
def pa_admin_ready(browser: Browser):
    """Create PostfixAdmin superadmin via setup.php (once per session)."""
    page = browser.new_page()
    page.goto(f"{PA_URL}/public/setup.php", timeout=30_000)
    page.locator("[name=setup_password]").fill(SETUP_PW)
    page.locator("[name=username]").fill(ADMIN_EMAIL)
    page.locator("[name=password]").fill(ADMIN_PW)
    page.locator("[name=password2]").fill(ADMIN_PW)
    page.locator("input[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.close()


@pytest.fixture(scope="session")
def sm_domain_ready(browser: Browser):
    """Configure test.local domain in SnappyMail admin (once per session)."""
    page = browser.new_page()
    page.goto(f"{SM_URL}/?admin", timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=20_000)

    # Admin login form
    page.locator("input[type=password]").fill(SM_ADMIN_PW)
    page.locator("button[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)

    # Navigate to Domains tab
    page.get_by_text("Domains", exact=False).first.click()
    page.wait_for_load_state("networkidle", timeout=10_000)

    # Add domain — click the + / Add button
    add_btn = page.locator("button").filter(has_text="+").or_(
        page.get_by_role("button", name="Add domain")
    ).first
    add_btn.click()
    page.wait_for_timeout(500)

    # Domain name
    page.get_by_label("Domain", exact=False).first.fill(DOMAIN)

    # IMAP settings
    page.locator("input[id*='imap'][id*='host'], input[name*='IMAP'][name*='Host'], "
                 "input[placeholder*='imap' i]").first.fill(DOVECOT)
    page.locator("input[id*='imap'][id*='port'], input[name*='IMAP'][name*='Port']").first.fill("143")

    # SMTP settings
    page.locator("input[id*='smtp'][id*='host'], input[name*='SMTP'][name*='Host'], "
                 "input[placeholder*='smtp' i]").first.fill("postfix")
    page.locator("input[id*='smtp'][id*='port'], input[name*='SMTP'][name*='Port']").first.fill("25")

    # Save
    page.get_by_role("button", name="Save").click()
    page.wait_for_load_state("networkidle", timeout=10_000)
    page.close()


# ── PostfixAdmin tests ────────────────────────────────────────────────────────

def test_postfixadmin_setup_creates_admin(browser: Browser, pa_admin_ready):
    """After setup.php, admin can log in to PostfixAdmin."""
    page = browser.new_page()
    page.goto(f"{PA_URL}/public/login.php", timeout=20_000)
    page.locator("[name=fUsername]").fill(ADMIN_EMAIL)
    page.locator("[name=fPassword]").fill(ADMIN_PW)
    page.locator("input[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)
    # Successful login: URL changes away from login.php
    assert "login" not in page.url, f"Login failed, still at {page.url}"
    page.close()


def test_postfixadmin_create_domain(browser: Browser, pa_admin_ready):
    """Admin can add a new domain in PostfixAdmin."""
    page = browser.new_page()
    # Login
    page.goto(f"{PA_URL}/public/login.php", timeout=20_000)
    page.locator("[name=fUsername]").fill(ADMIN_EMAIL)
    page.locator("[name=fPassword]").fill(ADMIN_PW)
    page.locator("input[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)

    # Navigate to Create Domain
    page.goto(f"{PA_URL}/public/create-domain.php", timeout=15_000)
    page.locator("[name=fDomain]").fill("ui.local")
    page.locator("input[type=submit]").first.click()
    page.wait_for_load_state("networkidle", timeout=10_000)
    # Should redirect to list-domain.php or show success
    assert "error" not in page.content().lower() or "ui.local" in page.content(), \
        "Domain creation may have failed"
    page.close()


def test_postfixadmin_create_mailbox(browser: Browser, pa_admin_ready):
    """Admin can add a mailbox in PostfixAdmin."""
    page = browser.new_page()
    # Login
    page.goto(f"{PA_URL}/public/login.php", timeout=20_000)
    page.locator("[name=fUsername]").fill(ADMIN_EMAIL)
    page.locator("[name=fPassword]").fill(ADMIN_PW)
    page.locator("input[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)

    # Need to have a domain first — ensure ui.local exists by trying to create it (ignore errors)
    page.goto(f"{PA_URL}/public/create-domain.php", timeout=15_000)
    page.locator("[name=fDomain]").fill("ui.local")
    page.locator("input[type=submit]").first.click()
    page.wait_for_load_state("networkidle", timeout=10_000)

    # Create mailbox
    page.goto(f"{PA_URL}/public/create-mailbox.php", timeout=15_000)
    page.locator("[name=fUsername]").fill("webtest")
    # Select domain ui.local in the dropdown
    page.locator("select[name=fDomain]").select_option("ui.local")
    page.locator("[name=fName]").fill("Web Test")
    page.locator("[name=fPassword]").fill("WebTest12")
    page.locator("[name=fPassword2]").fill("WebTest12")
    page.locator("input[type=submit]").first.click()
    page.wait_for_load_state("networkidle", timeout=10_000)
    assert "error" not in page.content().lower() or "webtest" in page.content(), \
        "Mailbox creation may have failed"
    page.close()


# ── SnappyMail tests ──────────────────────────────────────────────────────────

def test_snappymail_admin_configures_domain(browser: Browser, sm_domain_ready):
    """After admin setup, test.local domain is listed in SnappyMail admin."""
    page = browser.new_page()
    page.goto(f"{SM_URL}/?admin", timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=20_000)
    page.locator("input[type=password]").fill(SM_ADMIN_PW)
    page.locator("button[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.get_by_text("Domains", exact=False).first.click()
    page.wait_for_load_state("networkidle", timeout=10_000)
    expect(page.get_by_text(DOMAIN, exact=False)).to_be_visible(timeout=10_000)
    page.close()


def test_snappymail_user_login(browser: Browser, sm_domain_ready):
    """Alice can log in to SnappyMail."""
    page = browser.new_page()
    page.goto(SM_URL, timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=20_000)

    page.get_by_placeholder("Email", exact=False).fill(ALICE)
    page.locator("input[type=password]").fill(ALICE_PW)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_load_state("networkidle", timeout=20_000)

    # Inbox should be visible — look for INBOX or mail list
    expect(
        page.get_by_text("INBOX", exact=False).or_(
            page.locator(".rl-content, .sm-content, [data-screen='MessageList']")
        ).first
    ).to_be_visible(timeout=20_000)
    page.close()


def test_snappymail_read_mail(browser: Browser, sm_domain_ready):
    """Alice receives a mail sent via SMTP and can read it in SnappyMail."""
    import smtplib
    import email.mime.text

    subject = f"SM-Read-{uuid.uuid4().hex[:8]}"
    POSTFIX = os.environ.get("POSTFIX_HOST", "postfix")
    SMTP_P  = int(os.environ.get("SMTP_PORT", "25"))

    # Send mail to alice via SMTP
    msg = email.mime.text.MIMEText("Test mail for SnappyMail read test")
    msg["Subject"] = subject
    msg["From"] = f"sender@{DOMAIN}"
    msg["To"] = ALICE
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.sendmail(f"sender@{DOMAIN}", [ALICE], msg.as_string())

    # Allow delivery
    time.sleep(3)

    page = browser.new_page()
    page.goto(SM_URL, timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=20_000)

    page.get_by_placeholder("Email", exact=False).fill(ALICE)
    page.locator("input[type=password]").fill(ALICE_PW)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_load_state("networkidle", timeout=20_000)

    # Mail list should show the subject
    expect(page.get_by_text(subject, exact=False)).to_be_visible(timeout=30_000)
    page.close()


def test_snappymail_send_mail(browser: Browser, sm_domain_ready):
    """Alice composes and sends a mail to bob via SnappyMail; bob receives it."""
    subject = f"SM-Send-{uuid.uuid4().hex[:8]}"

    page = browser.new_page()
    page.goto(SM_URL, timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=20_000)

    # Login as alice
    page.get_by_placeholder("Email", exact=False).fill(ALICE)
    page.locator("input[type=password]").fill(ALICE_PW)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_load_state("networkidle", timeout=20_000)

    # Open compose window — click New Mail / Compose button
    compose_btn = page.get_by_role("button", name="New message").or_(
        page.get_by_role("button", name="Compose")
    ).or_(
        page.locator("a[title*='Compose' i], button[title*='Compose' i], "
                     "a[title*='New' i], button[title*='New' i]")
    ).first
    compose_btn.click()
    page.wait_for_timeout(1000)

    # Fill compose form
    page.get_by_placeholder("To", exact=False).or_(
        page.locator("[name=To], [data-name=To]")
    ).first.fill(BOB)
    page.keyboard.press("Tab")

    page.get_by_placeholder("Subject", exact=False).or_(
        page.locator("[name=Subject], [data-name=Subject]")
    ).first.fill(subject)

    # Body — click on compose area and type
    body_area = page.locator(
        ".ck-editor__editable, .compose-body, [contenteditable='true']"
    ).first
    body_area.click()
    body_area.type("Hello Bob, this is a UI test mail.")

    # Send
    page.get_by_role("button", name="Send").click()
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.close()

    # Verify bob received it via IMAP
    time.sleep(5)
    messages = _imap_messages(BOB, BOB_PW, subject)
    assert messages, f"Bob did not receive mail with subject '{subject}'"
