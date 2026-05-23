"""Sieve filter tests via ManageSieve (RFC 5804 / Dovecot Pigeonhole).

Tests:
- ManageSieve login / logout
- Upload, list, activate, delete scripts
- Filter mails into a custom folder by Subject header
- Multiple rules in one script
"""
import imaplib
import time
import pytest
from conftest import (
    DOVECOT, SIEVE_P, IMAP_P,
    ALICE, ALICE_PW,
    smtp_send,
)
from helpers.managesieve import ManageSieveClient, ManageSieveError


SCRIPT_NAME = "e2e-test-script"

SIEVE_FILEINTO = """\
require ["fileinto"];
if header :contains "Subject" "SIEVE-SORT" {
    fileinto "SieveTest";
    stop;
}
"""

SIEVE_MULTI = """\
require ["fileinto"];
if header :contains "Subject" "SIEVE-IMPORTANT" {
    fileinto "Important";
    stop;
}
if header :contains "Subject" "SIEVE-SPAM" {
    fileinto "Junk";
    stop;
}
"""


def _imap_search(subject: str, mailbox: str, retries: int = 15) -> bool:
    for _ in range(retries):
        with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
            conn.login(ALICE, ALICE_PW)
            conn.select(mailbox)
            _, data = conn.search(None, f'SUBJECT "{subject}"')
            if data[0]:
                return True
        time.sleep(1)
    return False


@pytest.fixture(autouse=True)
def cleanup_script():
    """Remove the test script before and after each test."""
    def _delete():
        try:
            with ManageSieveClient(DOVECOT, SIEVE_P) as ms:
                ms.authenticate(ALICE, ALICE_PW)
                if SCRIPT_NAME in ms.list_scripts():
                    ms.set_active("")
                    ms.delete_script(SCRIPT_NAME)
        except Exception:
            pass
    _delete()
    yield
    _delete()


# ----------------------------------------------------------------- Tests ---

def test_managesieve_login():
    with ManageSieveClient(DOVECOT, SIEVE_P) as ms:
        ms.authenticate(ALICE, ALICE_PW)


def test_managesieve_wrong_password():
    with ManageSieveClient(DOVECOT, SIEVE_P) as ms:
        with pytest.raises(ManageSieveError):
            ms.authenticate(ALICE, "wrongpass")


def test_managesieve_put_and_list():
    with ManageSieveClient(DOVECOT, SIEVE_P) as ms:
        ms.authenticate(ALICE, ALICE_PW)
        ms.put_script(SCRIPT_NAME, SIEVE_FILEINTO)
        scripts = ms.list_scripts()
    assert SCRIPT_NAME in scripts


def test_managesieve_set_active():
    with ManageSieveClient(DOVECOT, SIEVE_P) as ms:
        ms.authenticate(ALICE, ALICE_PW)
        ms.put_script(SCRIPT_NAME, SIEVE_FILEINTO)
        ms.set_active(SCRIPT_NAME)
        # deactivate again
        ms.set_active("")


def test_managesieve_delete():
    with ManageSieveClient(DOVECOT, SIEVE_P) as ms:
        ms.authenticate(ALICE, ALICE_PW)
        ms.put_script(SCRIPT_NAME, SIEVE_FILEINTO)
        ms.delete_script(SCRIPT_NAME)
        assert SCRIPT_NAME not in ms.list_scripts()


def test_sieve_fileinto_filter(unique_subject):
    """Mails matching the Sieve rule are delivered to the target folder."""
    subject = f"SIEVE-SORT {unique_subject}"

    # Ensure target folder exists
    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        conn.login(ALICE, ALICE_PW)
        conn.create("SieveTest")

    # Upload and activate the script
    with ManageSieveClient(DOVECOT, SIEVE_P) as ms:
        ms.authenticate(ALICE, ALICE_PW)
        ms.put_script(SCRIPT_NAME, SIEVE_FILEINTO)
        ms.set_active(SCRIPT_NAME)

    smtp_send(subject)

    assert _imap_search(subject, "SieveTest"), \
        f"Mail not found in SieveTest folder after Sieve filter"

    # Must NOT be in INBOX
    assert not _imap_search(subject, "INBOX"), \
        "Sieve-filtered mail still appeared in INBOX"


def test_sieve_non_matching_mail_to_inbox(unique_subject):
    """Mails not matching any rule land in INBOX as usual."""
    subject = f"PLAIN-MAIL {unique_subject}"

    with ManageSieveClient(DOVECOT, SIEVE_P) as ms:
        ms.authenticate(ALICE, ALICE_PW)
        ms.put_script(SCRIPT_NAME, SIEVE_FILEINTO)
        ms.set_active(SCRIPT_NAME)

    smtp_send(subject)

    assert _imap_search(subject, "INBOX"), \
        "Non-matching mail did not arrive in INBOX"


def test_sieve_multiple_rules(unique_subject):
    """Multiple rules in one script route mails to the correct folders."""
    subj_imp  = f"SIEVE-IMPORTANT {unique_subject}"
    subj_spam = f"SIEVE-SPAM {unique_subject}"

    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        conn.login(ALICE, ALICE_PW)
        conn.create("Important")
        conn.create("Junk")

    with ManageSieveClient(DOVECOT, SIEVE_P) as ms:
        ms.authenticate(ALICE, ALICE_PW)
        ms.put_script(SCRIPT_NAME, SIEVE_MULTI)
        ms.set_active(SCRIPT_NAME)

    smtp_send(subj_imp)
    smtp_send(subj_spam)

    assert _imap_search(subj_imp,  "Important"), "Important mail not routed correctly"
    assert _imap_search(subj_spam, "Junk"),      "Spam mail not routed correctly"
