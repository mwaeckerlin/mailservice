"""Antivirus — EICAR test file must be rejected at SMTP time.

The EICAR string is an industry-standard test payload that every
antivirus scanner recognises and reports as a virus. It is safe to
transmit (it does not actually do anything, it is 68 bytes of ASCII
that trigger a signature match) but our stack must reject it just as
it would a real Trojan.

The rspamd antivirus module hands the WHOLE raw message to clamav
(`scan_mime_parts = false` — per-part scanning would miss payloads in
inline text/html bodies); a hit sets CLAM_VIRUS with a forced reject
action, so postfix answers 5xx at DATA time. Both delivery forms are
covered: EICAR inline in the body AND as an attachment.

The compose healthcheck gates the whole stack on clamd being up (which
in turn requires a loaded signature DB), so by the time pytest runs,
EICAR detection must work — an accept here is a hard failure, never a
skip.
"""
import os
import socket
import struct
import time
import uuid

import pytest

from conftest import POSTFIX, DOMAIN, ALICE, send_raw


CLAMAV_HOST = os.environ.get("CLAMAV_HOST", "clamav")
CLAMAV_PORT = int(os.environ.get("CLAMAV_PORT", "3310"))

EICAR = (
    "X5O!P%@AP[4\\PZX54(P^)7CC)7}"
    "$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


def test_clamd_detects_eicar_directly():
    """clamd itself must flag the EICAR string via its INSTREAM
    protocol. Separates «scanner broken / DB not loaded» from «rspamd
    milter wiring broken» when the SMTP-level test below fails."""
    payload = EICAR.encode("ascii")
    with socket.create_connection((CLAMAV_HOST, CLAMAV_PORT), timeout=15) as s:
        s.sendall(b"zINSTREAM\0")
        s.sendall(struct.pack("!I", len(payload)) + payload)
        s.sendall(struct.pack("!I", 0))
        resp = s.recv(4096)
    assert b"FOUND" in resp, (
        f"clamd did not flag EICAR via INSTREAM — scanner or signature "
        f"DB broken. Response: {resp!r}"
    )


def _send_eicar_inline(subject: str) -> tuple[bool, str]:
    sender = f"virus-sender@{DOMAIN}"
    raw = (
        f"From: {sender}\r\n"
        f"To: {ALICE}\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: <{uuid.uuid4()}@{DOMAIN}>\r\n"
        f"Date: Fri, 17 Jul 2026 12:00:00 +0000\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=us-ascii\r\n"
        f"\r\n"
        f"{EICAR}\r\n"
    ).encode("ascii")
    return send_raw(POSTFIX, sender, ALICE, raw)


def _send_eicar_attachment(subject: str) -> tuple[bool, str]:
    sender = f"virus-sender@{DOMAIN}"
    raw = (
        f"From: {sender}\r\n"
        f"To: {ALICE}\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: <{uuid.uuid4()}@{DOMAIN}>\r\n"
        f"Date: Fri, 17 Jul 2026 12:00:00 +0000\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: multipart/mixed; boundary=\"XEICAR\"\r\n"
        f"\r\n"
        f"--XEICAR\r\n"
        f"Content-Type: text/plain; charset=us-ascii\r\n"
        f"\r\n"
        f"see attachment\r\n"
        f"--XEICAR\r\n"
        f"Content-Type: application/octet-stream; name=\"eicar.com\"\r\n"
        f"Content-Disposition: attachment; filename=\"eicar.com\"\r\n"
        f"\r\n"
        f"{EICAR}\r\n"
        f"--XEICAR--\r\n"
    ).encode("ascii")
    return send_raw(POSTFIX, sender, ALICE, raw)


def _assert_rejected(send, label: str):
    """Send until rejected; a short retry loop absorbs rspamd's clamd
    connection warm-up on a freshly started stack. Still accepted
    after 2 min → hard failure (never a skip; the compose
    healthchecks already guaranteed clamd is up with a loaded DB)."""
    subject = f"E2E-EICAR-{uuid.uuid4()}"
    deadline = time.time() + 120
    last_resp = None
    while time.time() < deadline:
        accepted, resp = send(subject)
        last_resp = resp
        if not accepted:
            return
        time.sleep(10)
    pytest.fail(
        f"EICAR ({label}) was still ACCEPTED after 2 min — the "
        f"rspamd→clamav antivirus chain is not rejecting viruses. "
        f"Last SMTP resp: {last_resp!r}"
    )


def test_eicar_inline_body_rejected():
    """EICAR inline in a text/plain body → whole-message clamd scan
    flags it → SMTP 5xx. Guards `scan_mime_parts = false`: per-part
    scanning would never show inline bodies to the scanner."""
    _assert_rejected(_send_eicar_inline, "inline body")


def test_eicar_attachment_rejected():
    """EICAR as a proper attachment → flagged → SMTP 5xx. The classic
    virus delivery form."""
    _assert_rejected(_send_eicar_attachment, "attachment")
