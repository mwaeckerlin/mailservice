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
SM_ADMIN_USER = os.environ.get("SM_ADMIN_USER",  "admin")


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

    # Step 1: Authenticate with setup_password (PostfixAdmin 4.x two-step setup)
    page.locator("form[name=authenticate] [name=setup_password]").fill(SETUP_PW)
    page.locator("form[name=authenticate] button[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)

    # Step 2: Create superadmin (form only appears after successful authentication)
    # setup_password must be submitted again — PostfixAdmin re-authenticates per request
    page.locator("form[name=create_admin] [name=setup_password]").fill(SETUP_PW)
    page.locator("form[name=create_admin] [name=username]").fill(ADMIN_EMAIL)
    page.locator("form[name=create_admin] [name=password]").fill(ADMIN_PW)
    page.locator("form[name=create_admin] [name=password2]").fill(ADMIN_PW)
    page.locator("form[name=create_admin] [type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.close()


@pytest.fixture(scope="session")
def sm_domain_ready(browser: Browser):
    """Configure test.local domain in SnappyMail admin (once per session)."""
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


# ── PostfixAdmin tests ────────────────────────────────────────────────────────

def test_postfixadmin_setup_creates_admin(browser: Browser, pa_admin_ready):
    """After setup.php, admin can log in to PostfixAdmin."""
    page = browser.new_page()
    page.goto(f"{PA_URL}/public/login.php", timeout=20_000)
    page.locator("[name=fUsername]").fill(ADMIN_EMAIL)
    page.locator("[name=fPassword]").fill(ADMIN_PW)
    page.locator("[type=submit]").click()
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
    page.locator("[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)

    # Navigate to Create Domain
    page.goto(f"{PA_URL}/public/edit.php?table=domain", timeout=15_000)
    page.locator("[name='value[domain]']").fill("ui.local")
    page.locator("[type=submit]").first.click()
    page.wait_for_load_state("networkidle", timeout=10_000)
    # Should redirect to list or show success
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
    page.locator("[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)

    # Need to have a domain first — ensure ui.local exists by trying to create it (ignore errors)
    page.goto(f"{PA_URL}/public/edit.php?table=domain", timeout=15_000)
    page.locator("[name='value[domain]']").fill("ui.local")
    page.locator("[type=submit]").first.click()
    page.wait_for_load_state("networkidle", timeout=10_000)

    # Create mailbox
    page.goto(f"{PA_URL}/public/edit.php?table=mailbox", timeout=15_000)
    page.locator("[name='value[local_part]']").fill("webtest")
    # Select domain ui.local in the dropdown
    page.locator("select[name='value[domain]']").select_option("ui.local")
    page.locator("[name='value[name]']").fill("Web Test")
    page.locator("[name='value[password]']").fill("WebTest12")
    page.locator("[name='value[password2]']").fill("WebTest12")
    page.locator("[type=submit]").first.click()
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
    page.locator("input[name='Login']").fill(SM_ADMIN_USER)
    page.locator("input[type=password]").fill(SM_ADMIN_PW)
    page.locator("button.buttonLogin").click()
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.locator("a[href='#/domains']").click()
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

    # SnappyMail opens an "Edit Identity" popup ~1s after login when the account
    # has no saved identity yet — it overlays and blocks the compose window.
    # Save a name to dismiss it permanently (known SnappyMail behaviour).
    identity_dialog = page.locator("dialog#V-PopupsIdentity")
    try:
        identity_dialog.wait_for(state="visible", timeout=8_000)
        identity_dialog.locator("input[name='Name']").fill("Alice")
        identity_dialog.locator("button.buttonAddIdentity").click()
        identity_dialog.wait_for(state="hidden", timeout=8_000)
    except Exception:
        pass

    # Open compose window — the compose button is <a class="buttonCompose">
    page.locator("a.buttonCompose").first.click()
    page.wait_for_timeout(1_000)

    # Fill compose form — emailsTags binding replaces the original input with
    # <ul class="emailaddresses"><input></ul>; first ul = To field. The address
    # must be committed as a tag (Enter) or the Send command stays disabled.
    to_input = page.locator("ul.emailaddresses input").first
    to_input.click()
    to_input.type(BOB)
    to_input.press("Enter")

    # Subject field has name="subject"
    page.locator("input[name='subject']").fill(subject)

    # Body is a Squire WYSIWYG contenteditable div inside .textAreaParent. It can
    # report as "not visible" to Playwright (zero-size flex child until laid out),
    # so focus it via JS and send real keystrokes that Squire's handler registers.
    body_area = page.locator(".textAreaParent > .squire-wysiwyg")
    body_area.wait_for(state="attached", timeout=10_000)
    body_area.evaluate("el => el.focus()")
    page.keyboard.type("Hello Bob, this is a UI test mail.")

    # Send button is <a data-bind="command: sendCommand">
    page.locator("a[data-bind*='sendCommand']").first.click()

    # Alice's mailbox has only INBOX (no Sent folder), so on the first send
    # SnappyMail opens a system-folder picker instead of sending. Set the Sent
    # folder to "Do not use" (__UNUSE__) — sentFolder() then returns null and
    # the resend proceeds without trying to save a copy. The mail still goes out.
    folder_picker = page.locator("dialog#V-PopupsFolderSystem")
    try:
        folder_picker.wait_for(state="visible", timeout=5_000)
        folder_picker.locator("select").first.select_option("__UNUSE__")
        page.wait_for_timeout(500)
        folder_picker.locator("a.close").click()
        folder_picker.wait_for(state="hidden", timeout=5_000)
        page.locator("a[data-bind*='sendCommand']").first.click()
    except Exception:
        pass

    # Wait for the compose dialog to close — that confirms SendMessage completed.
    # (Don't rely on networkidle: it can read as idle in the gap before the send
    # request fires, and closing the page would then abort the in-flight send.)
    page.locator("dialog#V-PopupsCompose").wait_for(state="hidden", timeout=15_000)
    page.close()

    # Verify bob received it via IMAP — poll to allow for delivery latency
    messages = []
    deadline = time.time() + 30
    while time.time() < deadline:
        messages = _imap_messages(BOB, BOB_PW, subject)
        if messages:
            break
        time.sleep(2)
    assert messages, f"Bob did not receive mail with subject '{subject}'"
