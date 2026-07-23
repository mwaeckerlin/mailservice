"""Alias delivery — PostfixAdmin alias → shared DB → postfix virtual
alias map → dovecot INBOX.

Aliases are a core admin feature (README «Domain and mailbox
administration») wired through `mysql_virtual_alias_maps.cf`, but no
other test exercises that map. This suite creates an alias through the
real PostfixAdmin web UI (like the domain/mailbox provisioning fixture),
then proves a mail addressed to the alias is accepted on the MX and
arrives in the target mailbox — the full admin-UI → DB → postfix →
delivery chain.

The negative side (an address in neither the mailbox nor the alias map
draws a 5xx) is pinned by test_smtp.py::test_smtp_unknown_local_recipient_rejected.
"""
import time

import pytest
from playwright.sync_api import Browser

from conftest import (
    ALICE, ALICE_PW, DOMAIN, PA_URL, ADMIN_EMAIL, ADMIN_PW,
    smtp_send, imap_starttls,
)

ALIAS = f"sales@{DOMAIN}"


@pytest.fixture(scope="session")
def alias_provisioned(provision_mail_accounts, browser: Browser):
    """Create the sales@ → alice@ alias through the PostfixAdmin UI."""
    page = browser.new_page()
    page.goto(f"{PA_URL}/login.php", timeout=20_000)
    page.locator("[name=fUsername]").fill(ADMIN_EMAIL)
    page.locator("[name=fPassword]").fill(ADMIN_PW)
    page.locator("[type=submit]").click()
    page.wait_for_load_state("networkidle", timeout=15_000)

    page.goto(f"{PA_URL}/edit.php?table=alias", timeout=15_000)
    page.locator("[name='value[localpart]']").fill("sales")
    page.locator("select[name='value[domain]']").select_option(DOMAIN)
    page.locator("[name='value[goto]']").fill(ALICE)
    page.locator("[type=submit]").first.click()
    page.wait_for_load_state("networkidle", timeout=10_000)

    # verify creation in the virtual list — a silently failed form
    # submit must not let the delivery test run against nothing
    page.goto(f"{PA_URL}/list-virtual.php?domain={DOMAIN}", timeout=15_000)
    assert ALIAS in page.content(), (
        f"alias {ALIAS} not visible in PostfixAdmin after creation"
    )
    page.close()


def test_alias_delivers_to_target_mailbox(alias_provisioned, unique_subject):
    """Mail to the alias is accepted by the MX and lands in the target
    user's INBOX, with the alias (not the mailbox) in the To header."""
    smtp_send(unique_subject, to=ALIAS)
    deadline = time.time() + 30
    while time.time() < deadline:
        with imap_starttls() as conn:
            conn.login(ALICE, ALICE_PW)
            conn.select("INBOX")
            _, data = conn.search(None, f'SUBJECT "{unique_subject}"')
            if data[0]:
                _, raw = conn.fetch(data[0].split()[0], "(RFC822)")
                assert ALIAS in raw[0][1].decode(errors="replace"), (
                    "delivered mail lost the alias To address"
                )
                return
        time.sleep(1)
    pytest.fail(f"mail to alias {ALIAS} never reached {ALICE}'s INBOX")
