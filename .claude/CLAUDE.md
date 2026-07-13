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
- **Inbound:** Exactly two outcomes — delivered to INBOX, or rejected with an
  informative SMTP error to the sender. No junk folder, no silent drop, no
  quarantine. Sieve filters may only accept or reject.

## milter-greylist pitfalls (learned from incidents)

- CLI flags override `greylist.conf` directives. `-a` = autowhite duration
  (seconds unless suffixed `s/m/h/d/w`) — `-a 5` means 5 SECONDS.
- An explicit `racl greylist default` disables the built-in auto-whitelist —
  omit it; unmatched connections are greylisted by the implicit default.
- Changes to greylisting behavior must keep the whole `test_greylisting.py`
  suite green on a FRESH stack (`down -v` first; warm stacks carry greylist/
  autowhite state and produce phantom results).

## Config migrations

On any config port across a major version, preserve the on-disk data layout
(paths, storage schemes) or ship a data migration — see
`tests/e2e/test_maildir_layout.py` and the Dovecot 2.4 regression in
CHANGELOG.md.
