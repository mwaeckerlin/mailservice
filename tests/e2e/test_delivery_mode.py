"""SPAM_DELIVERY_MODE end-to-end (v3.0.0).

The e2e stack runs dovecot with the project default
`SPAM_DELIVERY_MODE=reject`. This test suite verifies that under the
default:

  1. Clean mail lands in INBOX (sanity — the reject-mode delivery
     path does nothing surprising to normal mail).
  2. GTUBE lands in NEITHER INBOX NOR Junk (rspamd rejected it at
     SMTP time, so it never reached the delivery path — the exact
     mailservice project contract).

`mark` and `folder` modes are covered by the mailservice `.claude/
CLAUDE.md` design philosophy but are not the e2e default; the sieve
generation logic for both modes is unit-tested by the dovecot
submodule itself. Running the full e2e in either mode is a matter
of overriding one env var in docker-compose (see the SPAM_DELIVERY_MODE
comment in `docker-compose.yml`).
"""
import imaplib
import time
import uuid

from conftest import (
    POSTFIX, DOVECOT, IMAP_P, ALICE, ALICE_PW, DOMAIN, smtp_send, send_raw,
    imap_starttls,
)


GTUBE = (
    "XJS*C4JDBQADN1.NSBN3*2IDNEN*GTUBE-STANDARD-ANTI-UBE-TEST-EMAIL*C.34X"
)


def _all_folders(conn: imaplib.IMAP4) -> list[str]:
    typ, data = conn.list()
    assert typ == "OK"
    names = []
    for line in data:
        parts = line.decode().rsplit(" ", 1)
        names.append(parts[-1].strip('"'))
    return names


def _search_in(conn: imaplib.IMAP4, folder: str, subject: str) -> list:
    typ, _ = conn.select(folder)
    if typ != "OK":
        return []
    typ, data = conn.search(None, f'SUBJECT "{subject}"')
    return data[0].split() if typ == "OK" and data[0] else []


def test_clean_mail_lands_in_inbox_default_reject_mode(unique_subject):
    """Sanity guard: with SPAM_DELIVERY_MODE=reject (project default),
    a clean mail hits INBOX and does not appear in Junk."""
    smtp_send(unique_subject)
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        # wait for delivery
        for _ in range(15):
            inbox_hits = _search_in(conn, "INBOX", unique_subject)
            if inbox_hits:
                break
            time.sleep(1)
        assert inbox_hits, f"Clean mail {unique_subject} did not arrive in INBOX"

        junk_hits = _search_in(conn, "Junk", unique_subject)
        assert not junk_hits, (
            f"Clean mail {unique_subject} incorrectly delivered to Junk "
            f"under SPAM_DELIVERY_MODE=reject (Junk delivery is only "
            f"active in folder-mode)."
        )


def test_gtube_reaches_neither_inbox_nor_junk(unique_subject):
    """Under SPAM_DELIVERY_MODE=reject, a spam payload gets a 5xx at
    SMTP time — it can therefore reach NEITHER folder. This is the
    core mailservice contract: two outcomes, delivered or SMTP-
    rejected, no silent quarantine, no Junk-folder shortcut."""
    sender = f"gtube-{uuid.uuid4().hex[:8]}@{DOMAIN}"
    raw = (
        f"From: {sender}\r\n"
        f"To: {ALICE}\r\n"
        f"Subject: {unique_subject}\r\n"
        f"Message-ID: <{uuid.uuid4()}@{DOMAIN}>\r\n"
        f"Date: Fri, 17 Jul 2026 12:00:00 +0000\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=us-ascii\r\n"
        f"\r\n"
        f"{GTUBE}\r\n"
    ).encode("ascii")
    accepted, resp = send_raw(POSTFIX, sender, ALICE, raw)
    assert not accepted, (
        f"GTUBE was accepted — reject-mode contract broken: {resp!r}"
    )

    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        # short wait — nothing should ever appear, but give a moment
        # so an accidental delivery would surface.
        time.sleep(2)
        for folder in _all_folders(conn):
            assert not _search_in(conn, folder, unique_subject), (
                f"GTUBE mail {unique_subject} landed in {folder!r} under "
                f"SPAM_DELIVERY_MODE=reject. Reject-mode must produce "
                f"zero deliveries."
            )
