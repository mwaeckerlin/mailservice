"""The version-1 line, end to end, on the published images.

Four things decide whether the line carries Marc's mail: a mailbox logs
in, mail from outside arrives in it, an authenticated client sends mail
out to a foreign MX, and the webmail shows the delivered mail.
"""
import os
import smtplib
import time

import pytest

from conftest import (ALICE, ALICE_PW, DOMAIN, EXTERNAL_RCPT, FAKE_MAILS_DIR,
                      POSTFIX, SMTP_P, SM_URL, build_message, imap_starttls,
                      insecure_tls_ctx)

HELO = "test-runner.test.local"
"""The name every session of this suite greets with.

It resolves in the stack's own resolver. Without it smtplib
greets with the address literal of the container, on which the
SPF policy service of the 1 line fails with SERVFAIL, and
postfix then answers 450 to every recipient.
"""

EXTERNAL_SENDER = "outsider@extern.local"


def _fetch_subjects(conn, mailbox: str = "INBOX") -> list[str]:
    conn.select(mailbox)
    typ, data = conn.search(None, "ALL")
    assert typ == "OK", f"IMAP search failed: {typ}"
    subjects = []
    for num in data[0].split():
        typ, msg = conn.fetch(num, "(BODY[HEADER.FIELDS (SUBJECT)])")
        if typ == "OK" and msg and msg[0]:
            subjects.append(msg[0][1].decode(errors="replace"))
    return subjects


def _wait_for_subject(subject: str, timeout: int = 90) -> bool:
    """Poll the mailbox until the delivered mail shows up. Delivery runs
    through the queue, so the moment of the 250 is not the moment it is
    readable."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with imap_starttls() as conn:
            conn.login(ALICE, ALICE_PW)
            if any(subject in s for s in _fetch_subjects(conn)):
                return True
        time.sleep(3)
    return False


def test_mailbox_login(provision_mail_accounts):
    """The account an operator created in PostfixAdmin logs in over
    IMAP — the path every mail client of Marc's users takes."""
    with imap_starttls() as conn:
        typ, _ = conn.login(ALICE, ALICE_PW)
        assert typ == "OK"
        typ, _ = conn.select("INBOX")
        assert typ == "OK"


def test_inbound_mail_reaches_the_mailbox(provision_mail_accounts,
                                          unique_subject):
    """Mail from a foreign sender reaches the mailbox, and greylisting
    does not delay a client of the internal networks — the invariant the
    greylist configuration of this line exists for."""
    raw = build_message(unique_subject, "inbound body",
                        EXTERNAL_SENDER, ALICE)
    with smtplib.SMTP(POSTFIX, SMTP_P, timeout=30,
                      local_hostname=HELO) as smtp:
        refused = smtp.sendmail(EXTERNAL_SENDER, [ALICE], raw)
        assert refused == {}, f"recipient refused: {refused}"

    assert _wait_for_subject(unique_subject), (
        f"{unique_subject} never arrived in {ALICE}")


def test_authenticated_submission_leaves_for_the_foreign_mx(
        provision_mail_accounts, unique_subject):
    """An authenticated mailbox sends out: postfix accepts over TLS,
    resolves the MX of the foreign domain and delivers there. The proof
    is the mail in the foreign server's store, with its sender, its
    recipient and its body."""
    raw = build_message(unique_subject, "outbound body",
                        ALICE, EXTERNAL_RCPT)
    with smtplib.SMTP(POSTFIX, SMTP_P, timeout=30,
                      local_hostname=HELO) as smtp:
        smtp.ehlo(HELO)
        # This line offers SASL only over TLS (smtpd_tls_auth_only), so
        # the handshake comes first.
        smtp.starttls(context=insecure_tls_ctx())
        smtp.ehlo(HELO)
        smtp.login(ALICE, ALICE_PW)
        refused = smtp.sendmail(ALICE, [EXTERNAL_RCPT], raw)
        assert refused == {}, f"recipient refused: {refused}"

    deadline = time.time() + 90
    found = None
    while time.time() < deadline and found is None:
        for root, _dirs, files in os.walk(FAKE_MAILS_DIR):
            for name in files:
                path = os.path.join(root, name)
                try:
                    with open(path, "r", errors="replace") as fh:
                        content = fh.read()
                except OSError:
                    continue
                if unique_subject in content:
                    found = content
                    break
            if found:
                break
        if found is None:
            time.sleep(3)

    assert found is not None, (
        f"{unique_subject} never reached the foreign MX store "
        f"{FAKE_MAILS_DIR}")
    assert ALICE in found, "the sender is missing from the delivered mail"
    assert EXTERNAL_RCPT in found, "the recipient is missing"
    assert "outbound body" in found, "the body is missing"


def test_webmail_shows_the_delivered_mail(provision_mail_accounts, page,
                                          unique_subject):
    """The webmail logs the mailbox in and shows a mail that was
    delivered over SMTP — the screen Marc's users actually look at."""
    raw = build_message(unique_subject, "webmail body",
                        EXTERNAL_SENDER, ALICE)
    with smtplib.SMTP(POSTFIX, SMTP_P, timeout=30,
                      local_hostname=HELO) as smtp:
        smtp.sendmail(EXTERNAL_SENDER, [ALICE], raw)
    assert _wait_for_subject(unique_subject), (
        "the mail for the webmail test never arrived over IMAP")

    page.goto(SM_URL, timeout=40_000)
    page.wait_for_load_state("networkidle", timeout=20_000)
    page.locator("input[name='Email']").fill(ALICE)
    page.locator("input[name='Password']").fill(ALICE_PW)
    page.locator("button.buttonLogin").click()

    # The subject on the screen is the whole proof: it can only be there
    # when the login succeeded, the webmail reached dovecot and read the
    # mailbox the mail was delivered into. Nothing structural is
    # asserted, so a changed layout cannot make this pass or fail.
    page.wait_for_selector(f"text={unique_subject}", timeout=90_000)
