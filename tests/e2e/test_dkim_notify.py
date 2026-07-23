"""DKIM key-generation operator notification (F13, `NOTIFY_EMAIL` /
`NOTIFY_SMTP`).

The `rspamd-notify` service starts with a FRESH key volume, so it
generates a DKIM key for `notify.local` on every stack start and — with
`NOTIFY_EMAIL` set — delivers the printed DNS records by mail through
its minimal in-process SMTP client to `NOTIFY_SMTP` (fake-smtp's fixed
address). The test proves the notification really arrives: best-effort
stdout logging alone would let a fresh-volume restart print keys nobody
reads.
"""
import pathlib
import time

import pytest

FAKE_MAILS_DIR = "/fake-mails"


def test_dkim_key_notification_mail_delivered():
    deadline = time.time() + 120
    store = pathlib.Path(FAKE_MAILS_DIR)
    while time.time() < deadline:
        for f in store.rglob("*"):
            if not f.is_file():
                continue
            text = f.read_text(errors="replace")
            if "hostmaster@extern.local" in text and "notify.local" in text \
                    and "DKIM" in text:
                assert "_domainkey" in text, (
                    "notification mail carries no DNS record body"
                )
                return
        time.sleep(3)
    pytest.fail(
        "no DKIM key notification for notify.local arrived at "
        "hostmaster@extern.local — NOTIFY_EMAIL/NOTIFY_SMTP is not effective"
    )
