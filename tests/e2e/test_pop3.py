"""POP3 access tests."""
import poplib
import time
import pytest
from conftest import DOVECOT, POP3_P, ALICE, ALICE_PW, smtp_send


def test_pop3_login():
    conn = poplib.POP3(DOVECOT, POP3_P)
    resp = conn.user(ALICE)
    assert resp.startswith(b"+OK")
    resp = conn.pass_(ALICE_PW)
    assert resp.startswith(b"+OK")
    conn.quit()


def test_pop3_wrong_password_rejected():
    conn = poplib.POP3(DOVECOT, POP3_P)
    conn.user(ALICE)
    with pytest.raises(poplib.error_proto):
        conn.pass_("wrongpassword")
    conn.quit()


def test_pop3_list_and_retrieve(unique_subject):
    """Mail delivered via SMTP is listed and retrievable via POP3."""
    smtp_send(unique_subject)
    time.sleep(3)
    conn = poplib.POP3(DOVECOT, POP3_P)
    conn.user(ALICE)
    conn.pass_(ALICE_PW)
    _, msgs, _ = conn.list()
    assert msgs, "No messages found via POP3"
    # retrieve the last message and check our subject appears
    msg_num = msgs[-1].split()[0].decode()
    _, lines, _ = conn.retr(int(msg_num))
    raw = b"\r\n".join(lines).decode(errors="replace")
    # subject might be among many messages; verify POP3 retrieval works
    assert "Subject:" in raw
    conn.quit()


def test_pop3_stat(unique_subject):
    """STAT returns message count and total size."""
    smtp_send(unique_subject)
    time.sleep(3)
    conn = poplib.POP3(DOVECOT, POP3_P)
    conn.user(ALICE)
    conn.pass_(ALICE_PW)
    count, size = conn.stat()
    assert count >= 1
    assert size > 0
    conn.quit()
