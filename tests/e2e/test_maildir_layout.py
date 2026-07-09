"""Regression test: dovecot maildir on-disk layout must be <domain>/<localpart>.

Dovecot 2.4's config port changed the maildir path from the pre-2.4
`maildir:/var/mail/domains/%d/%n` (domain/localpart) to
`mail_path = /var/mail/domains/%{user}` (full email address). Existing maildirs
on disk live at `<domain>/<localpart>/`, so after the upgrade every mailbox
appeared empty — dovecot looked under `<full-email>/` instead. This test pins
the layout so the regression cannot silently return.

The test-runner mounts the shared `maildata` volume read-only at
`/var/mail/domains`, the same store dovecot writes to.
"""
import glob
import imaplib
import os

from conftest import DOVECOT, IMAP_P, ALICE, ALICE_PW, smtp_send
from test_imap import _wait_for_mail

MAIL_ROOT = "/var/mail/domains"


def test_maildir_uses_domain_localpart_layout(unique_subject):
    local_part, domain = ALICE.split("@")

    # deliver a real mail and confirm it is readable — this materialises the
    # maildir on disk at whatever path the dovecot config resolves.
    smtp_send(unique_subject, to=ALICE)
    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        conn.login(ALICE, ALICE_PW)
        assert _wait_for_mail(conn, unique_subject), "mail was not delivered to INBOX"

    domain_localpart = os.path.join(MAIL_ROOT, domain, local_part)
    full_email = os.path.join(MAIL_ROOT, ALICE)

    assert os.path.isdir(domain_localpart), (
        f"maildir not at <domain>/<localpart> ({domain_localpart}); legacy "
        f"mailboxes stored there would appear empty"
    )
    assert not os.path.isdir(full_email), (
        f"maildir at full-email path ({full_email}); legacy "
        f"<domain>/<localpart> mailboxes are orphaned"
    )
    # the delivered message physically lands under the domain/localpart maildir
    stored = glob.glob(os.path.join(domain_localpart, "new", "*")) + \
             glob.glob(os.path.join(domain_localpart, "cur", "*"))
    assert stored, f"no message file under {domain_localpart}/(new|cur)"
