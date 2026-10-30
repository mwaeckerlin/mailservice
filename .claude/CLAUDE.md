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
  suite green; it measures greylist and autowhite state, which a warm stack
  carries from earlier runs.

## dovecot pitfalls

- **Never set or clear `auth_username_chars`** in the dovecot config: an
  emptied character list is the precondition for the SQL auth bypass
  CVE-2026-24031 (and the LDAP filter injection CVE-2026-27860). The
  built-in default filters `'` out of usernames — leave it alone.
- **Auth debug logging only via `DOVECOT_DEBUG_AUTH=yes`** (the
  compiled init writes `conf.d/10-debug.conf`); never bake `log_debug`
  into `local.conf` — that is a production default seen by every log
  reader.
- **A `:regex` condition without `:comparator "i;octet"` folds case,**
  because Sieve compares with `i;ascii-casemap` by default. The subject
  is folded before the expression sees it, so the letter case is gone
  and no expression can recover it: `[A-Z]` and `[a-z]` both match every
  letter, `^[^a-z]+$` and `not [a-z]` match no subject at all. A rule
  meant for shouting subject lines therefore either rejects everything
  or nothing. Where it rejects and stops, every later rule of the script
  is dead and the mail is gone — which looks exactly like one single
  filter being broken. Measured with `sieve-test` in the image,
  2026-10-28, over seven expressions and two subjects. The webmail's
  filter form cannot write a comparator, so such a rule has to be kept
  in the script by hand or dropped. Pinned by
  `tests/v1/test_sieve_filters.py`. `regex` itself needs no
  `sieve_extensions` entry: Pigeonhole 2.4.5 carries it in the default
  list, measured with `doveconf sieve_extensions`.

## SnappyMail filter pitfalls

- **The webmail shows no filter settings at all unless the domain
  allows sieve scripts.** The screen `#/settings/filters` falls back to
  `#/settings/general` without it, so a user can write no filter. The
  init of the webmail image configures it from `SIEVE_HOST`,
  `SIEVE_PORT` and `SIEVE_SECURE`; in the admin panel it is the SIEVE
  tab of the domain. Pinned by the fixture `sm_domain_ready` in
  `tests/e2e/conftest.py`.
- **The filter FORM exists for the script `rainloop.user` alone**
  (`dev/Sieve/Model/Script.js`, `allowFilters()`); under any other name
  the popup offers the raw editor and no «Add a Filter» button. And the
  popup decides once, while it opens (`beforeShow`), which of the two it
  shows, while a script that does not exist yet carries no name — so a
  new script always opens raw, and the form appears when the stored
  script is opened again from the list. There the row of such a script
  shows the label «Simple» and carries its name in the `title`
  attribute alone.
- **The checkbox of the Checkbox component is a hidden input inside a
  label** (`templates/Views/Components/Checkbox.html`), so Playwright
  waits forever on its visibility: the label is what a test clicks.

## Config migrations & component replacements

On any config port across a major version, preserve the on-disk data layout
(paths, storage schemes) or ship a data migration — see
`tests/e2e/test_maildir_layout.py` and the Dovecot 2.4 regression in
CHANGELOG.md.
