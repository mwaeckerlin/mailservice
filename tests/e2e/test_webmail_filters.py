"""Sieve filters managed exclusively through the SnappyMail frontend.

Everything these tests do to a filter goes through the browser: open the
filter settings, add a script, add a filter with its condition and its
action, save, activate. Nothing is uploaded over ManageSieve. What is
measured afterwards is the effect on real mail — the message is sent over
SMTP and looked up over IMAP — and the script the frontend stored, read
back over ManageSieve as evidence of what the form wrote.

The locators address the knockout bindings (`data-bind`) instead of the
button labels, because the labels are translated and the bindings are not.
The condition and action identifiers come from the frontend's own model:
`dev/Sieve/Model/FilterCondition.js` (field `From`/`Subject`, type
`Contains`/`Regex`) and `dev/Sieve/Model/Filter.js` (action `MoveTo`).
"""
import email.mime.text
import os
import time
import uuid

import pytest
from playwright.sync_api import Browser, Page, expect

from conftest import imap_starttls, send_raw
from helpers.managesieve import ManageSieveClient

SM_URL = os.environ.get("SNAPPYMAIL_URL", "http://snappymail-proxy:8080")
POSTFIX = os.environ.get("POSTFIX_HOST", "postfix")
DOVECOT = os.environ.get("DOVECOT_HOST", "dovecot")
SIEVE_P = int(os.environ.get("SIEVE_PORT", "4190"))
ALICE = os.environ.get("ALICE_USER", "alice@test.local")
ALICE_PW = os.environ.get("ALICE_PASS", "alicepass12")
DOMAIN = os.environ.get("MAIL_DOMAIN", "test.local")

FOLDER = "WebmailFilter"
ZALANDO = f"info@service-mail.zalando.{DOMAIN}"
SHOUTING_SUBJECT = "GRATIS IPHONE JETZT GEWINNEN"

SCRIPT = "rainloop.user"
"""The only script whose filters SnappyMail shows as a form.

`dev/Sieve/Model/Script.js` allows the filter list for the name
`rainloop.user` alone; under any other name the popup offers the raw
editor and no «Add a Filter» button. A user who manages his filters in
the form writes exactly this script.
"""

TIMEOUT = 20_000


# ── driving the frontend ─────────────────────────────────────────────────

def _login(browser: Browser) -> Page:
    page = browser.new_page()
    page.goto(SM_URL, timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=TIMEOUT)
    page.get_by_placeholder("Email", exact=False).fill(ALICE)
    page.locator("input[type=password]").fill(ALICE_PW)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_load_state("networkidle", timeout=TIMEOUT)
    return page


def _open_filter_settings(page: Page) -> None:
    page.goto(f"{SM_URL}/#/settings/filters", timeout=TIMEOUT)
    page.wait_for_load_state("networkidle", timeout=TIMEOUT)
    expect(page.locator("[data-bind*='addScript']").first).to_be_visible(
        timeout=TIMEOUT)


def _add_filter_through_the_form(page: Page, *, script_name: str,
                                 field: str, condition_type: str,
                                 value: str, folder: str) -> None:
    """Add a script with one filter and save it, all in the browser.

    The popup decides once, while it opens, whether it shows the filter
    list or the raw editor (`Sieve/View/Script.js` beforeShow), and a
    script that does not exist yet carries no name at all. So the script
    is created empty first, under the one name whose filters the webmail
    shows as a form, and the filter is added when it is opened again.

    Both popups carry the same `value: name` input, so the name is
    filled while only the script popup is open, and every locator of the
    filter popup is scoped to its form.
    """
    page.locator("[data-bind*='addScript']").first.click()
    name_input = page.locator("input[data-bind='value: name']:visible").first
    expect(name_input).to_be_visible(timeout=TIMEOUT)
    name_input.fill(script_name)
    page.locator("a.buttonSave:visible").last.click()
    page.wait_for_load_state("networkidle", timeout=TIMEOUT)
    page.locator("a.close:visible").last.click()

    # the row of the stored script, which opens it with its filter list
    script_row = page.locator(f"td.script-name[title='{script_name}']").first
    expect(script_row).to_be_visible(timeout=TIMEOUT)
    script_row.click()

    add_filter = page.locator("a[data-bind*='addFilter']").first
    expect(add_filter).to_be_visible(timeout=TIMEOUT)
    add_filter.click()

    # The filter popup opens with no condition at all; the first one is
    # added through its own button (PopupsFilter.html).
    form = page.locator("#sieve-script-filter")
    expect(form).to_be_visible(timeout=TIMEOUT)
    # A filter without a name does not save (`Sieve/Model/Filter.js`
    # verify()), and its popup then stays over the script's own.
    form.locator("input[data-bind='value: name']").first.fill(
        f"{field} {condition_type}")
    form.locator("[data-bind*='addCondition']").first.click()
    form.locator("select[data-bind*='value: field']").first.select_option(field)
    form.locator("select[data-bind*='value: type']").first.select_option(
        condition_type)
    form.locator("input[data-bind='value: value']").first.fill(value)

    form.locator("select[data-bind*='value: actionType']").first.select_option(
        "MoveTo")
    form.locator(
        "select[data-bind*='selectedFolderValue']").first.select_option(folder)

    # the filter form saves on submit
    page.locator("button.buttonSave[form='sieve-script-filter']").first.click()
    page.wait_for_timeout(500)

    # and then the script itself — an anchor, not a button. Saving
    # leaves the popup open (`Sieve/View/Script.js`: the close() after a
    # successful save is commented out), and it covers the list below.
    page.locator("a.buttonSave:visible").last.click()
    page.wait_for_load_state("networkidle", timeout=TIMEOUT)
    page.locator("a.close:visible").last.click()
    expect(page.locator("#V-PopupsSieveScript")).to_be_hidden(timeout=TIMEOUT)


def _activate_script(page: Page, script_name: str) -> None:
    # The row of a script with filters shows the label «Simple», and
    # carries its name in the title attribute alone
    # (SettingsFilters.html).
    row = page.locator("tr.script-item").filter(
        has=page.locator(f"td.script-name[title='{script_name}']")).first
    row.locator("[data-bind*='enableScript']").first.click()
    page.wait_for_load_state("networkidle", timeout=TIMEOUT)


def _stored_script() -> str:
    """What the frontend actually wrote, read back over ManageSieve."""
    with ManageSieveClient(DOVECOT, SIEVE_P) as ms:
        ms.authenticate(ALICE, ALICE_PW)
        active = [n for n in ms.list_scripts()]
        assert active, "the frontend stored no script at all"
        return "\n".join(ms.get_script(n) for n in active)


# ── mail ─────────────────────────────────────────────────────────────────

def _send(subject: str, sender: str) -> None:
    """Hand the mail to postfix, retrying a greylist tempfail like any
    real MTA (`send_raw` of the conftest: the test HELO alone scores
    3.0, which can cross the greylist threshold)."""
    msg = email.mime.text.MIMEText("webmail filter test")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ALICE
    accepted, resp = send_raw(POSTFIX, sender, ALICE,
                              msg.as_string().encode())
    assert accepted, f"postfix did not accept {subject}: {resp}"


def _found_in(folder: str, subject: str, retries: int = 20) -> bool:
    for _ in range(retries):
        with imap_starttls() as conn:
            conn.login(ALICE, ALICE_PW)
            if conn.select(folder)[0] == "OK":
                _, data = conn.search(None, f'SUBJECT "{subject}"')
                if data[0]:
                    return True
        time.sleep(2)
    return False


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def clean_filters():
    """No script of a previous test may survive into this one."""
    def _wipe():
        with ManageSieveClient(DOVECOT, SIEVE_P) as ms:
            ms.authenticate(ALICE, ALICE_PW)
            ms.set_active("")
            for name in ms.list_scripts():
                ms.delete_script(name)
    _wipe()
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        conn.create(FOLDER)
    yield
    _wipe()


# ── tests ────────────────────────────────────────────────────────────────

def test_webmail_filter_files_mail_into_its_folder(browser: Browser,
                                                   sm_domain_ready,
                                                   clean_filters):
    """A filter built in the frontend — sender contains, move to folder —
    routes a real mail into that folder."""
    subject = f"WMF-{uuid.uuid4().hex[:8]}"
    page = _login(browser)
    _open_filter_settings(page)
    _add_filter_through_the_form(page, script_name=SCRIPT,
                                 field="From", condition_type="Contains",
                                 value="zalando", folder=FOLDER)
    _activate_script(page, SCRIPT)
    page.close()

    _send(subject, ZALANDO)

    assert _found_in(FOLDER, subject), (
        f"the filter built in the webmail did not file {subject} into "
        f"{FOLDER}")


def test_webmail_stores_the_filter_as_a_sieve_script(browser: Browser,
                                                     sm_domain_ready,
                                                     clean_filters):
    """The frontend writes a Sieve script, and the server keeps it: the
    condition and the action of the form are both in it."""
    page = _login(browser)
    _open_filter_settings(page)
    _add_filter_through_the_form(page, script_name=SCRIPT,
                                 field="From", condition_type="Contains",
                                 value="zalando", folder=FOLDER)
    page.close()

    script = _stored_script()
    assert "zalando" in script, f"the condition is missing: {script}"
    assert "fileinto" in script, f"the action is missing: {script}"
    assert FOLDER in script, f"the target folder is missing: {script}"


def test_webmail_regex_filter_is_written_without_a_comparator(
        browser: Browser, sm_domain_ready, clean_filters):
    """The form offers `Regex` as a condition type but writes no
    `:comparator`, so the stored rule compares case-insensitively. A
    character class meant for subjects without a lowercase letter
    therefore matches nothing, and the mail is not filed."""
    subject = f"{SHOUTING_SUBJECT} {uuid.uuid4().hex[:8]}".upper()
    page = _login(browser)
    _open_filter_settings(page)
    _add_filter_through_the_form(page, script_name=SCRIPT,
                                 field="Subject", condition_type="Regex",
                                 value="^[^a-z]+$", folder=FOLDER)
    _activate_script(page, SCRIPT)
    page.close()

    script = _stored_script()
    assert ":regex" in script, f"the form wrote no regex test: {script}"
    assert "comparator" not in script, (
        "the form now writes a comparator — the note in .claude/CLAUDE.md "
        f"and the hand-maintained rule are stale: {script}")

    _send(subject, f"sender@{DOMAIN}")

    assert not _found_in(FOLDER, subject, retries=5), (
        "the folded regex matched a shouting subject; Pigeonhole changed "
        "its comparator default")
    assert _found_in("INBOX", subject), (
        "the mail reached neither the folder nor INBOX")
