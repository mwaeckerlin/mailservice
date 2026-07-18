"""Bayes autotraining via IMAPSieve — moving mail into/out of Junk teaches
the classifier without a cron job.

Dovecot's imap_sieve fires `sieve/learn-spam.sieve` on IMAP MOVE/COPY
into the Junk folder and `sieve/learn-ham.sieve` on move out of Junk.
Each sieve pipes the message through /usr/local/bin/report-{spam,ham}
→ `rspamc -h rspamd:11334 learn_{spam,ham}`.

The classifier's state lives in Redis (per rspamd/classifier-bayes.conf),
shared across all three test rspamd instances via one redis container.
We verify by querying rspamd's controller stats before and after —
`ham` / `spam` learn counters must advance.
"""
import imaplib
import time
import urllib.request
import urllib.error
import uuid

import pytest

from conftest import (
    DOVECOT, IMAP_P, ALICE, ALICE_PW, RSPAMD, RSPAMD_CP, smtp_send,
    imap_starttls,
)


# The learn only counts if the message carries more tokens than the
# classifier's min_tokens (11) — rspamd skips statistically worthless
# mini-mails. And rspamd's learn cache dedupes on the message digest,
# so a body reused across tests would be silently ignored as «already
# learned» — every training mail embeds its unique subject.
def _bayes_body(unique: str) -> str:
    return (
        "Congratulations dear customer, you have been specially selected "
        "to receive an exclusive limited investment opportunity with "
        "guaranteed returns, simply confirm your account details today "
        f"and claim the reward before offer {unique} expires forever."
    )


def _bayes_counters() -> dict:
    """Return {'spam': int, 'ham': int} learn counters from rspamd's
    /stat endpoint. The per-statfile learn count is the `revision`
    field (`total` is the storage block count, not learns)."""
    url = f"http://{RSPAMD}:{RSPAMD_CP}/stat"
    with urllib.request.urlopen(url, timeout=5) as r:
        raw = r.read().decode("utf-8")
    import json
    data = json.loads(raw)
    stats = data.get("statfiles") or []
    counters = {"spam": 0, "ham": 0}
    for sf in stats:
        sym = (sf.get("symbol") or "").upper()
        learned = sf.get("revision") or sf.get("learned") or 0
        if "SPAM" in sym:
            counters["spam"] = learned
        elif "HAM" in sym:
            counters["ham"] = learned
    return counters


def _create_junk_and_move(imap: imaplib.IMAP4, uid: bytes) -> None:
    imap.create("Junk")
    imap.select("INBOX")
    typ, _ = imap.copy(uid, "Junk")
    assert typ == "OK", f"IMAP COPY into Junk failed: {typ}"
    imap.store(uid, "+FLAGS", "\\Deleted")
    imap.expunge()


def test_move_to_junk_advances_spam_learn_counter(unique_subject):
    """MOVE a delivered mail into Junk → rspamd's spam-learn counter
    goes up by at least one (imap_sieve fires learn-spam.sieve →
    /usr/local/bin/report-spam → rspamc learn_spam).

    The controller /stat endpoint is part of the image contract — if
    it is unreachable, the Bayes-training loop is unobservable AND
    rspamc learn_* would fail the same way, so that is a hard failure.
    """
    try:
        before = _bayes_counters()
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        pytest.fail(f"rspamd controller /stat endpoint not reachable: {e}")

    smtp_send(unique_subject, body=_bayes_body(unique_subject))

    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        # find our mail
        uid = None
        for _ in range(20):
            conn.select("INBOX")
            typ, data = conn.search(None, f'SUBJECT "{unique_subject}"')
            if typ == "OK" and data[0]:
                uid = data[0].split()[0]
                break
            time.sleep(1)
        assert uid is not None, f"Mail {unique_subject} did not arrive in INBOX"
        _create_junk_and_move(conn, uid)

    # give imap_sieve → pipe → rspamc a moment to hit rspamd
    deadline = time.time() + 30
    while time.time() < deadline:
        after = _bayes_counters()
        if after["spam"] > before["spam"]:
            return  # ✓ counter advanced
        time.sleep(1)

    pytest.fail(
        f"spam-learn counter did not advance after IMAP MOVE to Junk: "
        f"before={before}, after={_bayes_counters()}. "
        f"imap_sieve → sieve_pipe → rspamc wiring is broken."
    )


def test_move_out_of_junk_advances_ham_learn_counter(unique_subject):
    """MOVE a message from Junk back to INBOX → rspamd's ham-learn
    counter goes up by at least one (learn-ham.sieve → report-ham →
    rspamc learn_ham).
    """
    try:
        before = _bayes_counters()
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        pytest.fail(f"rspamd controller /stat endpoint not reachable: {e}")

    smtp_send(unique_subject, body=_bayes_body(unique_subject))

    with imap_starttls() as conn:
        conn.login(ALICE, ALICE_PW)
        # place a mail in Junk first
        uid_in_inbox = None
        for _ in range(20):
            conn.select("INBOX")
            typ, data = conn.search(None, f'SUBJECT "{unique_subject}"')
            if typ == "OK" and data[0]:
                uid_in_inbox = data[0].split()[0]
                break
            time.sleep(1)
        assert uid_in_inbox is not None
        conn.create("Junk")
        conn.copy(uid_in_inbox, "Junk")
        conn.store(uid_in_inbox, "+FLAGS", "\\Deleted")
        conn.expunge()

        # give the spam-learn sieve a moment
        time.sleep(3)

        # now move it BACK from Junk → INBOX to trigger ham-learn
        conn.select("Junk")
        typ, data = conn.search(None, f'SUBJECT "{unique_subject}"')
        assert typ == "OK" and data[0], "Mail is not in Junk after move"
        uid_in_junk = data[0].split()[0]
        conn.copy(uid_in_junk, "INBOX")
        conn.store(uid_in_junk, "+FLAGS", "\\Deleted")
        conn.expunge()

    deadline = time.time() + 30
    while time.time() < deadline:
        after = _bayes_counters()
        if after["ham"] > before["ham"]:
            return
        time.sleep(1)

    pytest.fail(
        f"ham-learn counter did not advance after IMAP MOVE out of "
        f"Junk: before={before}, after={_bayes_counters()}."
    )
