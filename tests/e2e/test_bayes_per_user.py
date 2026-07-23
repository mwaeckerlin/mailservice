"""RSPAMD_BAYES_PER_USER (F22): the per-user classifier switch must
really separate statistics by RECIPIENT, not just render a config line.

The rspamd-log instance runs with RSPAMD_BAYES_PER_USER=true (its Bayes
is otherwise unused — autolearn trains the main instance). The redis
key layout hashes the user, so key inspection cannot observe the knob;
the SEMANTIC effect can: after training past the min_learns threshold
for alice only, scanning the same spammy mail yields a Bayes verdict
for alice and NONE for charlie — with a global classifier both would
score identically.
"""
import json
import os
import urllib.request
import uuid

from conftest import ALICE, CHARLIE, DOMAIN

RSPAMD_LOG_CTL = os.environ.get("RSPAMD_LOG_CTL_URL", "http://rspamd-log:11334")
# classifier-bayes.conf: symbols contribute only after this many learns
# of EACH class
MIN_LEARNS = 200

SPAM_WORDS = ("viagra casino winner lottery pills cheap deal bonus "
              "free money crypto jackpot")
HAM_WORDS = ("meeting agenda protocol invoice project review report "
             "schedule budget draft milestone summary")


def _mail(rcpt: str, words: str) -> bytes:
    return (
        f"From: someone-{uuid.uuid4().hex[:8]}@{DOMAIN}\r\n"
        f"To: {rcpt}\r\n"
        f"Subject: {words.split()[0]} {uuid.uuid4().hex}\r\n"
        f"\r\n"
        f"{words} {uuid.uuid4().hex} {uuid.uuid4().hex}\r\n"
    ).encode()


def _post(path: str, rcpt: str, body: bytes) -> bytes:
    req = urllib.request.Request(
        f"{RSPAMD_LOG_CTL}{path}", data=body,
        headers={"Deliver-To": rcpt, "Rcpt": rcpt})
    with urllib.request.urlopen(req, timeout=20) as resp:
        # 200 (json) or 204 — anything below 400 processed the sample
        assert resp.status < 400, f"{path} failed: HTTP {resp.status}"
        return resp.read()


def _bayes_spam_score(rcpt: str, body: bytes) -> float:
    raw = _post("/checkv2", rcpt, body)
    data = json.loads(raw)
    sym = data.get("symbols", {}).get("BAYES_SPAM")
    return float(sym["score"]) if sym else 0.0


def test_bayes_per_user_separates_recipients():
    for _ in range(MIN_LEARNS):
        _post("/learnspam", ALICE, _mail(ALICE, SPAM_WORDS))
        _post("/learnham", ALICE, _mail(ALICE, HAM_WORDS))

    probe = _mail(ALICE, SPAM_WORDS)
    alice_score = _bayes_spam_score(ALICE, probe)
    assert alice_score > 0, (
        "no BAYES_SPAM verdict for alice after training past min_learns "
        "— the per-user classifier did not learn"
    )

    charlie_score = _bayes_spam_score(CHARLIE, probe)
    assert charlie_score == 0, (
        f"charlie got a BAYES_SPAM verdict ({charlie_score}) from "
        f"alice's training — statistics are shared, so "
        f"RSPAMD_BAYES_PER_USER is not effective"
    )
