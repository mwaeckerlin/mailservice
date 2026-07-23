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

from conftest import imap_starttls, smtp_send

# ── Config ───────────────────────────────────────────────────────────────────

PA_URL      = os.environ.get("POSTFIXADMIN_URL", "http://postfixadmin-proxy:8080")
SM_URL      = os.environ.get("SNAPPYMAIL_URL",   "http://snappymail-proxy:8080")
DOVECOT     = os.environ.get("DOVECOT_HOST",     "dovecot")
IMAP_P      = int(os.environ.get("IMAP_PORT",    "143"))
ALICE       = os.environ.get("ALICE_USER",       "alice@test.local")
ALICE_PW    = os.environ.get("ALICE_PASS",       "alicepass12")
BOB         = os.environ.get("BOB_USER",         "bob@test.local")
BOB_PW      = os.environ.get("BOB_PASS",         "bobpass12")
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
    with imap_starttls() as conn:
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
    _wait_http(f"{PA_URL}/setup.php")
    _wait_http(f"{SM_URL}/")


# sm_domain_ready (SnappyMail domain provisioning) lives in conftest.py —
# shared with test_openpgp.py.


# ── PostfixAdmin tests ────────────────────────────────────────────────────────

def _pa_login(page):
    """Log in to PostfixAdmin as the superadmin."""
    page.goto(f"{PA_URL}/login.php", timeout=20_000)
    page.locator("[name=fUsername]").fill(ADMIN_EMAIL)
    page.locator("[name=fPassword]").fill(ADMIN_PW)
    page.locator("[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)


def test_postfixadmin_setup_creates_admin(browser: Browser, provision_mail_accounts):
    """After setup.php, the admin can log in to PostfixAdmin."""
    page = browser.new_page()
    _pa_login(page)
    # Successful login: URL changes away from login.php
    assert "login" not in page.url, f"Login failed, still at {page.url}"
    page.close()


def test_postfixadmin_mail_users_created(browser: Browser, provision_mail_accounts):
    """The mail users provisioned through PostfixAdmin are listed for the domain.

    This is the account-provisioning test the rest of the suite relies on: the
    alice/bob mailboxes are created via the PostfixAdmin UI (in the
    `provision_mail_accounts` fixture) into the single shared database that
    Postfix and Dovecot also use.
    """
    page = browser.new_page()
    _pa_login(page)
    page.goto(f"{PA_URL}/list-virtual.php?domain={DOMAIN}", timeout=15_000)
    page.wait_for_load_state("networkidle", timeout=10_000)
    content = page.content()
    assert ALICE in content, f"{ALICE} not listed in PostfixAdmin for {DOMAIN}"
    assert BOB in content, f"{BOB} not listed in PostfixAdmin for {DOMAIN}"
    page.close()


def test_postfixadmin_branding_rendered(browser: Browser,
                                        provision_mail_accounts):
    """The branding knobs (FOOTER_TEXT / FOOTER_LINK) are rendered into
    the UI — the env→config passthrough is effective, not just stored."""
    page = browser.new_page()
    page.goto(f"{PA_URL}/login.php", timeout=20_000)
    expect(page.get_by_text("E2E Footer Contract").first).to_be_visible(
        timeout=10_000)
    link = page.locator("a[href='https://example.test/footer']")
    expect(link.first).to_be_attached(timeout=5_000)
    page.close()


def test_postfixadmin_default_aliases_created(browser: Browser,
                                              provision_mail_accounts):
    """Creating a domain provisions the DEFAULT_ALIASES standard
    addresses (abuse/hostmaster/postmaster/webmaster) — required
    role accounts exist without manual work."""
    page = browser.new_page()
    _pa_login(page)
    page.goto(f"{PA_URL}/list-virtual.php?domain={DOMAIN}", timeout=15_000)
    content = page.content()
    for alias in ("abuse", "hostmaster", "postmaster", "webmaster"):
        assert f"{alias}@{DOMAIN}" in content, (
            f"default alias {alias}@{DOMAIN} was not created with the domain"
        )
    page.close()


def test_postfixadmin_create_mailbox(browser: Browser, provision_mail_accounts):
    """Admin can add a further mailbox through the PostfixAdmin UI."""
    page = browser.new_page()
    _pa_login(page)

    # Create an additional throwaway mailbox in the existing mail domain
    page.goto(f"{PA_URL}/edit.php?table=mailbox", timeout=15_000)
    page.locator("[name='value[local_part]']").fill("webtest")
    page.locator("select[name='value[domain]']").select_option(DOMAIN)
    page.locator("[name='value[name]']").fill("Web Test")
    page.locator("[name='value[password]']").fill("WebTest12")
    page.locator("[name='value[password2]']").fill("WebTest12")
    page.locator("[type=submit]").first.click()
    page.wait_for_load_state("networkidle", timeout=10_000)

    # Verify the mailbox really exists: it must be listed for the domain.
    page.goto(f"{PA_URL}/list-virtual.php?domain={DOMAIN}", timeout=15_000)
    page.wait_for_load_state("networkidle", timeout=10_000)
    assert f"webtest@{DOMAIN}" in page.content(), \
        f"webtest@{DOMAIN} not listed after mailbox creation"
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


def test_snappymail_transport_security_banner(browser: Browser, sm_domain_ready):
    """A mail delivered over a plaintext hop carries
    `X-Transport-Security: none`; the transport-security plugin shows a
    red «UNENCRYPTED» banner when the message is opened in the webmail.
    Proves the whole chain: postfix macro → rspamd header → SnappyMail
    plugin → visible marker."""
    # plaintext SMTP on port 25 → the message is stamped
    # X-Transport-Security: none by rspamd. smtp_send retries the
    # score-based greylisting 451 like a real MTA.
    subject = smtp_send(f"SM-XTS-{uuid.uuid4().hex[:8]}", to=ALICE)
    time.sleep(3)

    page = browser.new_page()
    page.goto(SM_URL, timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=20_000)
    page.get_by_placeholder("Email", exact=False).fill(ALICE)
    page.locator("input[type=password]").fill(ALICE_PW)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_load_state("networkidle", timeout=20_000)

    # open the message from the list
    row = page.get_by_text(subject, exact=False)
    expect(row.first).to_be_visible(timeout=30_000)
    row.first.click()

    # the plugin injects #transport-security-banner into the message view
    banner = page.locator("#transport-security-banner")
    expect(banner).to_be_visible(timeout=20_000)
    assert "UNENCRYPTED" in (banner.inner_text() or ""), (
        f"transport-security banner text unexpected: {banner.inner_text()!r}"
    )
    assert "transport-insecure" in (
        banner.get_attribute("class") or ""), (
        "banner is not styled as insecure (red)"
    )
    page.close()


def test_snappymail_transport_security_no_banner_for_tls(browser: Browser, sm_domain_ready):
    """A mail submitted over STARTTLS carries `X-Transport-Security:
    TLSv1.x`; the plugin shows NO banner. This proves the plugin reads
    the real header value — otherwise (if the server-side fetch always
    returned empty) even a TLS mail would be flagged."""
    import smtplib
    import ssl

    from conftest import build_message

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    subject = f"SM-XTS-ok-{uuid.uuid4().hex[:8]}"
    POSTFIX = os.environ.get("POSTFIX_HOST", "postfix")
    SUBM_P  = int(os.environ.get("SUBMISSION_PORT", "587"))

    # authenticated STARTTLS submission (not greylisted for own users) →
    # rspamd stamps a real TLS version into X-Transport-Security
    with smtplib.SMTP(POSTFIX, SUBM_P, timeout=15) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.starttls(context=ctx)
        s.ehlo(f"testhost.{DOMAIN}")
        s.login(ALICE, ALICE_PW)
        s.sendmail(ALICE, [ALICE],
                   build_message(subject, from_=ALICE, to=ALICE))
    time.sleep(3)

    page = browser.new_page()
    page.goto(SM_URL, timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=20_000)
    page.get_by_placeholder("Email", exact=False).fill(ALICE)
    page.locator("input[type=password]").fill(ALICE_PW)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_load_state("networkidle", timeout=20_000)

    row = page.get_by_text(subject, exact=False)
    expect(row.first).to_be_visible(timeout=30_000)
    row.first.click()

    # give the plugin the same chance to run as in the positive test,
    # then assert it did NOT flag this TLS-transported mail
    page.wait_for_timeout(4_000)
    assert page.locator("#transport-security-banner").count() == 0, (
        "plugin flagged a TLS-transported mail — it is not reading the "
        "real X-Transport-Security value"
    )
    page.close()
