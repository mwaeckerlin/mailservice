# Features

What MailService does, from the point of view of the people who use and
operate it. This is the *what* (user-visible behaviour); the *how*
(architecture, images, configuration internals) lives in the README and
CONTRIBUTING.

Every feature carries a stable number (`F<n>`); a number is never
reassigned. [TESTS.md](TESTS.md) references these numbers — every
feature is covered by at least one executed test, enforced by the
coverage guard in the test suite.

## For the mail user

- **F1 — Webmail in the browser.** Read, write, organise and search mail
  through SnappyMail — no client setup. Folders and contacts work out of
  the box.
- **F2 — Any standard mail client.** IMAP and POP3 for reading, SMTP
  submission for sending, ManageSieve for server-side filters. Recommended
  encrypted settings: IMAP over SSL/TLS (993), submission over STARTTLS
  (587) or implicit TLS (465), Sieve over STARTTLS (4190).
- **F3 — Your password is never sent in the clear.** The server offers the
  password login mechanisms only once the connection is encrypted; a
  client that will not use TLS simply cannot log in. For trusted,
  isolated networks without certificates the operator can deliberately
  soften this (`DOVECOT_ALLOW_CLEARTEXT=yes`).
- **F4 — Send mail and forget it.** Once the server accepts a message at
  submission, it owns delivery: it queues and retries for days if a
  recipient is temporarily unreachable, and only ever reports a
  *permanent* failure back to you (as a bounce). You never see a
  temporary error and never have to re-send.
- **F5 — Your own mail is never greylisted or blocklisted.** Authenticated
  submission from your account bypasses greylisting, DNSBLs and the
  spam-score delay entirely — those apply only to incoming mail from
  strangers.
- **F6 — See how securely a mail reached you.** Every incoming message
  carries an `X-Transport-Security` header recording whether the last hop
  used modern TLS, obsolete TLS, or no encryption at all; the webmail
  marks cleartext or obsolete transport visibly (red / orange) so you can
  tell which correspondents deliver insecurely. The header cannot be
  forged by a sender.
- **F7 — Spam and viruses are rejected, not hidden.** By default there is
  no spam folder and no silent quarantine: a message is either delivered
  to your INBOX or refused at send time with a clear reason the sender
  can read. Infected mail (ClamAV) and mail scoring above the spam
  threshold are rejected the same way; doubtful mid-score mail is
  deferred (greylisting) and accepted on the RFC-compliant retry.
- **F8 — Nothing silently vanishes.** No content filter can misfile a
  message into a folder you never check; a sender-forged spam verdict
  header cannot divert legitimate mail; oversized mail beyond the virus
  scanner's limits is delivered unscanned rather than bounced.
- **F9 — OpenPGP in the webmail.** Generate or import key pairs in
  SnappyMail (server-side GnuPG store backed by the shipped php-gnupg
  extension), sign and encrypt outgoing mail, decrypt and verify
  incoming mail — the message body travels as ciphertext only.

## For the operator

- **F10 — A complete suite in one deployment.** Postfix (SMTP/TLS),
  Dovecot (IMAP/POP3/Sieve/LMTP), the SnappyMail webmail, the
  PostfixAdmin admin UI, and rspamd (DKIM signing, DKIM/DMARC/SPF
  verification, greylisting, Bayes spam scoring, ClamAV antivirus) —
  wired together and ready to run with `docker compose`. The relay
  images (`smtp-relay`, `smtp-relay-tls`, `mailforward`) are usable
  standalone.
- **F11 — Domain and mailbox administration.** Create and manage domains,
  mailboxes, aliases and per-mailbox quotas through the PostfixAdmin web
  UI. The admin UI speaks plain HTTP and is therefore bound to loopback
  by default — put a TLS reverse proxy in front for remote access.
- **F12 — Separate MX and submission roles.** Port 25 is the anonymous
  server-to-server MX (opportunistic TLS, full anti-spam restrictions);
  ports 587 and 465 are for your users' clients and enforce TLS 1.2+ and
  authentication with no MX restrictions. Optionally require TLS on the
  MX too (`SMTPD_TLS_REQUIRED=yes`) for a closed / internal ingress.
  Without a certificate no authentication is offered at all — passwords
  never travel unencrypted.
- **F13 — DKIM/DMARC modes you can roll out safely.** Choose per stack:
  `off`, `log` (verify and stamp results, never reject — the monitor mode
  to run for a few days after enabling), `permissive` (reject
  bad/unknown-key signatures and DMARC `p=reject` fails), or `reject`
  (also reject unsigned external mail). DKIM keys are generated per
  domain on first start and the DNS records are printed (and optionally
  e-mailed) to you.
- **F14 — Spam handling you choose.** Default is reject-at-SMTP. Operators
  who want big-provider behaviour can opt into `mark` (add `X-Spam-*`
  headers, never touch the body or subject, so DKIM stays intact) or
  `folder` (server-side move to Junk — a silent quarantine, explicitly
  not recommended).
- **F15 — Mail survives restarts.** The Postfix queue is a persistent
  volume; an accepted-but-undelivered mail is never lost across a
  container recreate or image update. The account database persists on
  the real data path. Both are pinned by automated tests.
- **F16 — Optional per-mailbox quota** (`DOVECOT_QUOTA=yes`, off by
  default) taken from PostfixAdmin; when a mailbox is full, delivery
  tempfails (the sender retries) rather than dropping mail silently.
- **F17 — Limits are high, configurable and documented,** never silently
  bouncing legitimate mail: message size (default 100 GiB), Sieve script
  size (default 500M), scan sizes, and hard-error limits are all env
  knobs — and they are enforced, not merely rendered into a config.
- **F18 — Hardened images.** Every shipped image is headless (no shell,
  perl, busybox or package manager) and validates its entire environment
  on start-up, refusing to boot on a malformed value rather than
  rendering a broken or injected configuration. No default database
  password ships — an unset one fails fast instead of coming up on a
  known credential.
- **F19 — Database schema upgrade after an image update.** When a newer
  PostfixAdmin image runs on an existing database, opening `setup.php`
  migrates the schema in place; accounts and mail are untouched.
- **F20 — Generic milter hooks on the standalone relays.** `smtp-relay`
  (`OPENDKIM=host[:port]`) and `mailforward` (`GREYLIST=host[:port]`)
  can wire ANY milter — e.g. the rspamd container — into their mail
  path; the env names are historical (opendkim/milter-greylist era),
  the mechanism is a plain milter endpoint.
- **F21 — Fully wired by environment.** Every service connection is an
  env knob validated at start-up: database (`DB_*` /
  PostfixAdmin `DATABASE_*`), milter (`RSPAMD`), antispam backends
  (`REDIS_HOST/PORT`, `CLAMAV_HOST/PORT`), identities and routing
  (`DOMAIN`, `DOMAINS`, `HOSTNAME`, `HOSTROOT`, `MAILHOST`, `MAPPINGS`,
  `LOCAL_DOMAINS`, `MYNETWORKS`, `RELAYHOST`, `PHP_FPM_HOST`) and the
  authserv identity (`AUTHSERV_ID`). Legacy password hashes from an
  imported database keep working via `DEFAULT_PASS_SCHEME`.
- **F22 — Anti-spam behaviour is tunable.** The rspamd action
  thresholds (`RSPAMD_GREYLIST_SCORE`, `RSPAMD_ADDHEADER_SCORE`,
  `RSPAMD_REJECT_SCORE`), greylist timing (`RSPAMD_GREYLIST_TIMEOUT`,
  `RSPAMD_GREYLIST_EXPIRE`), the trust perimeter
  (`RSPAMD_LOCAL_ADDRS`, `RSPAMD_SIGN_NETWORKS`), the local-client
  greylist opt-in (`RSPAMD_CHECK_LOCAL`), per-user Bayes
  (`RSPAMD_BAYES_PER_USER`), the DKIM selector (`SELECTOR`), key
  notification (`NOTIFY_EMAIL`, `NOTIFY_SMTP`) and log verbosity
  (`RSPAMD_LOG_LEVEL`, `POSTFIX_TLS_LOGLEVEL`, `DOVECOT_DEBUG_AUTH`)
  are all env knobs.
- **F23 — PostfixAdmin deployment configuration.** Setup password,
  per-admin limits and quota defaults (`ALIASES`, `MAILBOXES`,
  `MAXQUOTA`, `DOMAIN_QUOTA_DEFAULT`), domain-creation defaults
  (`DEFAULT_ALIASES` role accounts, `DEFAULT_ALIASES_ADDRESS/DOMAIN`)
  and UI branding (`FOOTER_TEXT`, `FOOTER_LINK`, `WELCOME_TEXT`,
  `SHOW_CUSTOM_*`) are env knobs rendered into the admin UI.
  `VACATION_DOMAIN` is passed through to PostfixAdmin, but this stack
  ships no vacation transport — leave it unset.

## Quality assurance

- **A real end-to-end test suite** (`npm test`) exercises every numbered
  feature against a real Docker Compose environment with Playwright and
  live SMTP/IMAP/POP3/Sieve — the complete register is in
  [TESTS.md](TESTS.md), and an automated coverage guard fails the suite
  if any feature loses its tests.
- **A manual two-domain playground** (`tests/manual/`) for realistic
  hands-on testing: two full deployments delivering to each other over
  real server-to-server SMTP with a local pseudo-CA — see its
  [README](tests/manual/README.md).

## Deprecated / removed

- `postgrey` (milter-greylist): removed from the stack in 3.0.0
  (greylisting is rspamd's job) and the standalone image is now
  deprecated and archived.
- `opendkim` / `opendmarc` / `postfix-policyd-spf-perl`: replaced by
  rspamd in 3.0.0.
