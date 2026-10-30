"""The filter rules the webmail writes must run on this line.

The webmail stores its rules as a Sieve script over ManageSieve. Two
things are pinned here: the server accepts the script shape the webmail
generates, and a `:regex` condition compares the way Sieve prescribes —
case-insensitively unless the script names `i;octet`. Under that default
a subject is folded to one case before the expression sees it, so
«contains no lowercase letter» can no longer be expressed: the rule
either matches everything or nothing, and both are wrong.
"""
import smtplib
import time

import pytest

from conftest import (ALICE, ALICE_PW, DOVECOT, POSTFIX, SMTP_P,
                      build_message, imap_starttls)
from helpers.managesieve import ManageSieveClient, ManageSieveError

SIEVE_PORT = 4190
TARGET_FOLDER = "einkauf.zalando"
ZALANDO_SENDER = "info@service-mail.zalando.ch"

# The shape the webmail generates: the require line it always writes, a
# rule that rejects a subject without a single lowercase letter, and a
# rule that files one sender into a subfolder. `%s` takes the comparator
# option, which the webmail's own form cannot produce.
WEBMAIL_SCRIPT = """require ["fileinto","regex","reject"];

if header :contains ["From"] "gitlab.com"
{
    fileinto "INBOX";
    stop;
}

if anyof(
    header :contains ["From"] "aliexpress",
    header :regex %s["Subject"] "^[^a-z]+$"
)
{
    reject "Your Message has been identified as SPAM.";
    stop;
}

if header :contains ["From"] "%s"
{
    fileinto "%s";
    stop;
}
"""

AS_THE_FORM_WRITES_IT = WEBMAIL_SCRIPT % (
    "", ZALANDO_SENDER, TARGET_FOLDER)
WITH_THE_CASE_SENSITIVE_COMPARATOR = WEBMAIL_SCRIPT % (
    ':comparator "i;octet" ', ZALANDO_SENDER, TARGET_FOLDER)

SHOUTING_SUBJECT = "GRATIS IPHONE JETZT GEWINNEN !!!"
ORDINARY_SUBJECT = "Deine Bestellung ist unterwegs"


@pytest.fixture
def upload_script():
    """Make a script the active one for alice, and clean up after."""
    def _upload(script: str):
        with ManageSieveClient(DOVECOT, SIEVE_PORT) as client:
            client.authenticate(ALICE, ALICE_PW)
            client.put_script("webmail", script)
            client.set_active("webmail")
    yield _upload
    with ManageSieveClient(DOVECOT, SIEVE_PORT) as client:
        client.authenticate(ALICE, ALICE_PW)
        try:
            client.set_active("")
            client.delete_script("webmail")
        except ManageSieveError:
            pass


@pytest.fixture
def target_folder():
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        conn.create(TARGET_FOLDER)
    return TARGET_FOLDER


def _send_from_zalando(subject: str, marker: str):
    raw = build_message(subject, marker, ZALANDO_SENDER, ALICE)
    with smtplib.SMTP(POSTFIX, SMTP_P, timeout=30) as smtp:
        refused = smtp.sendmail(ZALANDO_SENDER, [ALICE], raw)
    assert refused == {}, f"recipient refused: {refused}"


def _find_in(folder: str, marker: str, timeout: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with imap_starttls() as conn:
            conn.login(ALICE, ALICE_PW)
            typ, _ = conn.select(folder)
            if typ == "OK":
                typ, data = conn.search(None, "ALL")
                if typ == "OK":
                    for num in data[0].split():
                        typ, msg = conn.fetch(num, "(RFC822)")
                        if typ == "OK" and msg and msg[0] and \
                                marker in msg[0][1].decode(errors="replace"):
                            return True
        time.sleep(3)
    return False


def test_webmail_filter_script_compiles(provision_mail_accounts):
    """The server accepts the script the webmail writes. A refused script
    disables every rule at once, so this is the first thing to measure
    when «one filter does not work». The `regex` extension needs no
    `sieve_extensions` entry — Pigeonhole carries it by default."""
    with ManageSieveClient(DOVECOT, SIEVE_PORT) as client:
        client.authenticate(ALICE, ALICE_PW)
        try:
            client.put_script("compile-check", AS_THE_FORM_WRITES_IT)
        except ManageSieveError as exc:
            pytest.fail(
                f"the server refused the webmail's own script: {exc}")
        client.delete_script("compile-check")


def test_regex_without_a_comparator_never_matches(provision_mail_accounts,
                                                  upload_script,
                                                  target_folder,
                                                  unique_subject):
    """Without `:comparator` the folding puts the capitals into the
    negated class as well, so `^[^a-z]+$` matches no subject at all —
    a shouting one included. The rule is dead and the mail walks on to
    the next rule."""
    upload_script(AS_THE_FORM_WRITES_IT)
    _send_from_zalando(SHOUTING_SUBJECT, unique_subject)

    assert _find_in(target_folder, unique_subject, 90), (
        "the negated class now matches a shouting subject — if Pigeonhole "
        "changed its folding, the comparator note in .claude/CLAUDE.md is "
        "stale")


def test_regex_with_i_octet_separates_the_cases(provision_mail_accounts,
                                                upload_script,
                                                target_folder,
                                                unique_subject):
    """Naming `i;octet` makes the negated class mean what it says: the
    shouting subject is rejected and stored nowhere, the ordinary one
    passes the spam rule and reaches the folder of the sender rule."""
    upload_script(WITH_THE_CASE_SENSITIVE_COMPARATOR)

    shouting = f"{unique_subject}-SHOUTING"
    _send_from_zalando(SHOUTING_SUBJECT, shouting)
    _send_from_zalando(ORDINARY_SUBJECT, unique_subject)

    assert _find_in(target_folder, unique_subject, 90), (
        f"{unique_subject} did not reach {target_folder}")
    assert not _find_in(target_folder, shouting, 10), (
        "the shouting mail was rejected, so nothing may be stored")
    assert not _find_in("INBOX", shouting, 10), (
        "the shouting mail was rejected, so nothing may be stored")
