"""SPAM_DELIVERY_MODE end-to-end (all three modes).

Default mode (`reject`, main dovecot service):

  1. Clean mail lands in INBOX (sanity — the reject-mode delivery
     path does nothing surprising to normal mail).
  2. GTUBE lands in NEITHER INBOX NOR Junk (rspamd rejected it at
     SMTP time, so it never reached the delivery path — the exact
     mailservice project contract).

Opt-in modes (dedicated `dovecot-mark` / `dovecot-folder` services,
exercised over LMTP port 24 — the exact interface postfix uses for
final delivery):

  3. `mark` — mail carrying `X-Spam-Flag: YES` is delivered to INBOX
     (headers only, never a Junk detour).
  4. `folder` — mail carrying `X-Spam-Flag: YES` is routed to the
     Junk folder by the server-side sieve_before rule; clean mail
     still reaches INBOX.

Ingress invariant (default stack, through rspamd):

  5. Sender-supplied X-Spam-* verdict headers are forgeries of OUR
     verdict and must not survive to delivery — otherwise a foreign
     upstream filter's leftover verdict would silently misfile
     legitimate mail under `folder`/`mark` mode (same invariant class
     as the pinned X-Transport-Security forgery test in test_tls.py).
"""
import email
import imaplib
import time
import uuid

from conftest import (
    POSTFIX, DOVECOT, DOVECOT_MARK, DOVECOT_FOLDER, IMAP_P, ALICE, ALICE_PW,
    DOMAIN, smtp_send, send_raw, imap_starttls, lmtp_deliver, build_message,
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


# ------------------------------------------------- mark / folder modes ---

def _spam_flagged_message(subject: str) -> bytes:
    """A borderline-spam mail exactly as postfix hands it to dovecot:
    rspamd accepted it at SMTP time (score below the reject threshold)
    and stamped `X-Spam-Flag: YES` above the add-header threshold."""
    msg = build_message(subject)
    return (f"X-Spam-Flag: YES\r\n{msg}").encode()


def _wait_in(host: str, folder: str, subject: str, retries: int = 15) -> bool:
    for _ in range(retries):
        with imap_starttls(host) as conn:
            conn.login(ALICE, ALICE_PW)
            if _search_in(conn, folder, subject):
                return True
        time.sleep(1)
    return False


def test_mark_mode_spam_flag_mail_lands_in_inbox(unique_subject):
    """SPAM_DELIVERY_MODE=mark: a spam-flagged mail is delivered to
    INBOX — the informational headers are the whole story, there is no
    server-side Junk detour (the user's MUA filters client-side)."""
    code, text = lmtp_deliver(DOVECOT_MARK, ALICE,
                              _spam_flagged_message(unique_subject))
    assert 200 <= code < 300, f"mark-mode LMTP delivery failed: {code} {text}"
    assert _wait_in(DOVECOT_MARK, "INBOX", unique_subject), (
        "spam-flagged mail did not reach INBOX under mark mode"
    )
    with imap_starttls(DOVECOT_MARK) as conn:
        conn.login(ALICE, ALICE_PW)
        assert not _search_in(conn, "Junk", unique_subject), (
            "mark mode filed a mail into Junk — that is folder-mode "
            "behaviour and a silent quarantine"
        )


def test_folder_mode_spam_flag_mail_lands_in_junk(unique_subject):
    """SPAM_DELIVERY_MODE=folder: a spam-flagged mail is routed to the
    Junk folder by the sieve_before rule (the documented, explicitly
    not-recommended opt-in) — and consequently stays out of INBOX."""
    code, text = lmtp_deliver(DOVECOT_FOLDER, ALICE,
                              _spam_flagged_message(unique_subject))
    assert 200 <= code < 300, f"folder-mode LMTP delivery failed: {code} {text}"
    assert _wait_in(DOVECOT_FOLDER, "Junk", unique_subject), (
        "spam-flagged mail did not reach Junk under folder mode"
    )
    with imap_starttls(DOVECOT_FOLDER) as conn:
        conn.login(ALICE, ALICE_PW)
        assert not _search_in(conn, "INBOX", unique_subject), (
            "folder mode delivered a spam-flagged mail to INBOX as well"
        )


def test_folder_mode_clean_mail_lands_in_inbox(unique_subject):
    """SPAM_DELIVERY_MODE=folder: mail without the flag is untouched by
    the sieve rule and reaches INBOX normally."""
    raw = build_message(unique_subject).encode()
    code, text = lmtp_deliver(DOVECOT_FOLDER, ALICE, raw)
    assert 200 <= code < 300, f"folder-mode LMTP delivery failed: {code} {text}"
    assert _wait_in(DOVECOT_FOLDER, "INBOX", unique_subject), (
        "clean mail did not reach INBOX under folder mode"
    )
    with imap_starttls(DOVECOT_FOLDER) as conn:
        conn.login(ALICE, ALICE_PW)
        assert not _search_in(conn, "Junk", unique_subject), (
            "clean mail was filed into Junk under folder mode"
        )


# --------------------------------------------- forged-flag ingress guard ---

def test_forged_spam_headers_stripped_on_ingress(unique_subject):
    """The X-Spam-* verdict headers are OURS — sender-supplied copies are
    forgeries and must be stripped by rspamd before delivery. Otherwise a
    foreign upstream filter's leftover verdict on a clean, legitimate
    mail would misfile it (Junk quarantine via `X-Spam-Flag` under folder
    mode, MUA filters via Status/Level under mark mode) — exactly the
    misdirection the design philosophy forbids.

    This pins an UPSTREAM guarantee (rspamd milter_headers): incoming
    X-Spam-Flag / X-Spam-Status are removed on every scan, X-Spam-Level
    from score >= 1, and the `SPAM_FLAG` rule additionally scores a
    pre-existing flag as a spam signal (5.0). Recognisable FORGED
    markers are asserted absent (the same technique as
    test_transport_security_header_not_forgeable) because rspamd may
    legitimately stamp its OWN verdict headers on this mail. The flag
    itself is deliberately NOT forged here: its `SPAM_FLAG` score plus
    the e2e environment noise would push the mail over the add-header
    threshold, and the test targets the dangerous below-threshold case
    where only the ingress removal protects the delivery path."""
    msg = build_message(unique_subject)
    forged = (
        "X-Spam-Status: Yes, score=999.9 (FORGED)\r\n"
        "X-Spam-Level: ****FORGED****\r\n"
        f"{msg}"
    )
    accepted, resp = send_raw(POSTFIX, f"outsider@{DOMAIN}", ALICE,
                              forged.encode())
    assert accepted, f"mail with forged X-Spam-* headers rejected: {resp!r}"
    assert _wait_in(DOVECOT, "INBOX", unique_subject), (
        "mail with forged X-Spam-* headers never delivered"
    )
    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        conn.select("INBOX")
        _, data = conn.search(None, f'SUBJECT "{unique_subject}"')
        _, raw = conn.fetch(data[0].split()[0], "(RFC822)")
        delivered = email.message_from_bytes(raw[0][1])
    for header in ("X-Spam-Status", "X-Spam-Level", "X-Spam-Flag"):
        values = delivered.get_all(header, [])
        assert "FORGED" not in " ".join(values), (
            f"forged {header} survived to delivery: {values!r} — a foreign "
            f"verdict on clean mail misfiles it under folder/mark mode"
        )
