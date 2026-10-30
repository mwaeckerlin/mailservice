"""The simplest possible proof that Sieve runs at delivery time.

Everything else about filters builds on this one fact: a script the user
stored and activated is executed when a message is delivered. Where it is
not, every filter silently does nothing, every mail lands in INBOX, and
the symptom is indistinguishable from a wrong rule.
"""
import smtplib

import pytest

from conftest import (ALICE, ALICE_PW, DOVECOT, POSTFIX, SMTP_P,
                      build_message, imap_starttls)
from helpers.managesieve import ManageSieveClient, ManageSieveError

SIEVE_PORT = 4190
FOLDER = "SieveRuns"
HELO = "test-runner.test.local"
"""The name every session of this suite greets with.

It resolves in the stack's own resolver. Without it smtplib
greets with the address literal of the container, on which the
SPF policy service of the 1 line fails with SERVFAIL, and
postfix then answers 450 to every recipient.
"""

SENDER = "someone@extern.local"

TRIVIAL_SCRIPT = f"""require ["fileinto"];
fileinto "{FOLDER}";
"""


@pytest.fixture
def existing_folder():
    """The target folder exists before the mail arrives — the normal case
    of a user who made the folder in the webmail first."""
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        conn.create(FOLDER)
    return FOLDER


@pytest.fixture
def trivial_script_active():
    with ManageSieveClient(DOVECOT, SIEVE_PORT) as ms:
        ms.authenticate(ALICE, ALICE_PW)
        ms.put_script("runs", TRIVIAL_SCRIPT)
        ms.set_active("runs")
        assert "runs" in ms.list_scripts(), "the script was not stored"
    yield
    with ManageSieveClient(DOVECOT, SIEVE_PORT) as ms:
        ms.authenticate(ALICE, ALICE_PW)
        try:
            ms.set_active("")
            ms.delete_script("runs")
        except ManageSieveError:
            pass


def test_an_active_script_is_executed_at_delivery(provision_mail_accounts,
                                                  existing_folder,
                                                  trivial_script_active,
                                                  unique_subject):
    """An unconditional `fileinto` puts every incoming message into the
    named folder. If the message is in INBOX instead, the delivery path
    runs no user script at all."""
    from test_sieve_filters import _find_in

    raw = build_message(unique_subject, "does sieve run", SENDER, ALICE)
    with smtplib.SMTP(POSTFIX, SMTP_P, timeout=30,
                      local_hostname=HELO) as smtp:
        refused = smtp.sendmail(SENDER, [ALICE], raw)
    assert refused == {}, f"recipient refused: {refused}"

    in_folder = _find_in(FOLDER, unique_subject, 90)
    in_inbox = _find_in("INBOX", unique_subject, 5)
    assert in_folder, (
        f"the active script did not file the message; in INBOX: {in_inbox}"
        " — a message in INBOX means the delivery path executed no user"
        " sieve script")
