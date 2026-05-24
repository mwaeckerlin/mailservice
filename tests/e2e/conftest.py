"""Shared fixtures: connection details + wait-for-service helpers."""
import os
import socket
import time
import imaplib
import smtplib
import email.mime.text
import uuid

import pytest


# ----------------------------------------------------------------- Config ---

POSTFIX   = os.environ.get("POSTFIX_HOST",  "postfix")
DOVECOT   = os.environ.get("DOVECOT_HOST",  "dovecot")
OPENDKIM  = os.environ.get("OPENDKIM_HOST", "")
SMTP_P    = int(os.environ.get("SMTP_PORT",     "25"))
IMAP_P    = int(os.environ.get("IMAP_PORT",    "143"))
POP3_P    = int(os.environ.get("POP3_PORT",    "110"))
SIEVE_P   = int(os.environ.get("SIEVE_PORT", "4190"))
OPENDKIM_P = int(os.environ.get("OPENDKIM_PORT", "10026"))
DOMAIN    = os.environ.get("MAIL_DOMAIN",   "test.local")
ALICE     = os.environ.get("ALICE_USER",    f"alice@{DOMAIN}")
ALICE_PW  = os.environ.get("ALICE_PASS",    "alicepass")
BOB       = os.environ.get("BOB_USER",      f"bob@{DOMAIN}")
BOB_PW    = os.environ.get("BOB_PASS",      "bobpass")
SENDER    = f"sender@{DOMAIN}"


# ----------------------------------------------------------- Helpers -------

def wait_for_port(host: str, port: int, timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return
        except OSError:
            time.sleep(1)
    raise TimeoutError(f"{host}:{port} did not become ready within {timeout}s")


def build_message(subject: str, body: str = "test body",
                  from_: str = SENDER, to: str = ALICE) -> str:
    msg = email.mime.text.MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = from_
    msg["To"]      = to
    msg["Message-ID"] = f"<{uuid.uuid4()}@{DOMAIN}>"
    return msg.as_string()


def smtp_send(subject: str, to: str = ALICE,
              from_: str = SENDER, body: str = "test") -> str:
    """Send a mail and return the subject (for IMAP search)."""
    with smtplib.SMTP(POSTFIX, SMTP_P) as s:
        s.ehlo(f"testhost.{DOMAIN}")
        s.sendmail(from_, [to], build_message(subject, body, from_, to))
    return subject


# --------------------------------------------------------- Fixtures --------

@pytest.fixture(scope="session", autouse=True)
def wait_for_services():
    wait_for_port(POSTFIX, SMTP_P)
    wait_for_port(DOVECOT, IMAP_P)
    wait_for_port(DOVECOT, POP3_P)
    wait_for_port(DOVECOT, SIEVE_P)
    # opendkim: guaranteed healthy by docker-compose before postfix starts;
    # test-runner does not need direct access to port 10026.
    time.sleep(3)


@pytest.fixture
def imap_alice():
    with imaplib.IMAP4(DOVECOT, IMAP_P) as conn:
        conn.login(ALICE, ALICE_PW)
        yield conn


@pytest.fixture
def unique_subject():
    return f"E2E-{uuid.uuid4()}"
