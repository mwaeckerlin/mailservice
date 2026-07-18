# Mailservice — Project Rules

## Mail philosophy (binding for every change)

Full statement: README.md «Design philosophy: reliability over filtering».

- **Outbound:** A client (webmail/IMAP) only hands mail to Postfix; Postfix
  owns delivery, queuing and retries. Once accepted at submission, the mail is
  guaranteed to leave the server or bounce with a real (permanent) error.
  Temporary errors are NEVER surfaced to the user.
  - Greylisting must NEVER apply to own users: SASL-authenticated clients and
    internal networks stay whitelisted in milter-greylist. Never pass `-A` to
    milter-greylist (disables SMTP-AUTH whitelisting). Pinned by
    `tests/e2e/test_greylisting.py::test_authenticated_submission_not_greylisted`.
- **Inbound:** The mailservice default is exactly two outcomes — delivered
  to INBOX, or rejected with an informative SMTP error to the sender. No
  silent drop.
  - Two additional delivery modes are available as **opt-in** for operators
    who explicitly want the big-provider-style behaviour, both controlled by
    the `SPAM_DELIVERY_MODE` env on the dovecot service:
    - `mark` — deliver to INBOX, add `X-Spam-Flag: YES` and related
      informational headers. **Never rewrite the subject**, never touch
      the body — anything that would break the sender's DKIM signature
      (or the ARC chain of an intermediate hop) is forbidden. The user's
      MUA can filter on the added headers client-side.
    - `folder` — deliver to the recipient's IMAP `Junk` folder via a
      server-side sieve rule (`X-Spam-Flag: YES` → `fileinto "Junk"`).
      This is a silent quarantine and is explicitly **not recommended**,
      but supported for admins who ask for it.
  - Default is `reject`. Anything above `RSPAMD_REJECT_SCORE` is rejected
    at SMTP time regardless of `SPAM_DELIVERY_MODE` — the mode only
    controls what happens to borderline mail (between add-header score
    and reject score) that was accepted at SMTP time.
  - Server-side sieve for the `folder` mode may only route the message —
    accept, reject, or fileinto. No transformation of the mail body.

## milter-greylist pitfalls (learned from incidents)

- CLI flags override `greylist.conf` directives. `-a` = autowhite duration
  (seconds unless suffixed `s/m/h/d/w`) — `-a 5` means 5 SECONDS.
- An explicit `racl greylist default` disables the built-in auto-whitelist —
  omit it; unmatched connections are greylisted by the implicit default.
- Changes to greylisting behavior must keep the whole `test_greylisting.py`
  suite green on a FRESH stack (`down -v` first; warm stacks carry greylist/
  autowhite state and produce phantom results).

## dovecot pitfalls

- **Never set or clear `auth_username_chars`** in the dovecot config: an
  emptied character list is the precondition for the SQL auth bypass
  CVE-2026-24031 (and the LDAP filter injection CVE-2026-27860). The
  built-in default filters `'` out of usernames — leave it alone.
- **Auth debug logging only via `DOVECOT_DEBUG_AUTH=yes`** (start.sh
  writes `conf.d/10-debug.conf`); never bake `log_debug` into
  `local.conf` — that is a production default seen by every log reader.

## Config migrations & component replacements

On any config port across a major version, preserve the on-disk data layout
(paths, storage schemes) or ship a data migration — see
`tests/e2e/test_maildir_layout.py` and the Dovecot 2.4 regression in
CHANGELOG.md.

More generally, when replacing any component or mechanism: list the
behavioural invariants of the old setup (e.g. "SASL-authenticated clients
are never greylisted"), reproduce each one explicitly in the new setup and
pin it with an e2e test; verify the semantics of every flag/option against
the manual instead of assuming it — see the greylisting regression pinned
by `tests/e2e/test_greylisting.py::test_authenticated_submission_not_greylisted`.
