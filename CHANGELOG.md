# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **README**: image dependency chain documented (`smtp-relay` → `mailforward` → `postfix`)
- **README** (Administration): database version requirement documented — MariaDB 11+
  is required because Dovecot 2.4's MySQL client needs TLS to the database; for an
  older MariaDB without TLS, set `ssl = no` in Dovecot's MySQL passdb block.
- **README** (Usage): after a server upgrade/migration every user must set a new
  password in PostfixAdmin — Dovecot 2.4 refuses legacy weak password hashes
  (e.g. `MD5-CRYPT`), so old passwords stop working until re-hashed.

- **OpenDKIM service** (`opendkim/`): new container that auto-generates a 2048-bit RSA
  key on first start, signs outgoing mail and verifies incoming signatures (mode `sv`).
  Key is persisted in the `dkim-keys` volume. DNS TXT record is printed to the log on
  first start. Configurable via `DOMAIN` (required) and `SELECTOR` (default: `mail`).
- **SPF incoming check**: `postfix` now installs `postfix-policyd-spf-perl` and enables
  it by default. Disable with `CHECK_SPF=no` in the postfix environment.
- **DKIM milter wiring in postfix**: new `OPENDKIM` environment variable connects postfix
  to an OpenDKIM milter (`host[:port]`, default port 10026).
- **Multi-milter support in postfix**: `_add_milter()` helper in `start.sh` appends
  milters instead of overwriting, so greylisting and DKIM can coexist.
- **`MYNETWORKS` env var in postfix**: allows restricting trusted networks at runtime
  (used in e2e tests to force SPF checks for all connections).
- **`DISABLE_DNSBL` env var in postfix**: strips RBL/DNSBL checks for development and
  testing environments.
- **opendkim in `docker-compose.yml`**: service wired into the main stack with
  `dkim-net` network and `dkim-keys` volume.
- **opendkim in `docker-compose.local.yml`**: local-dev overlay with `DOMAIN: localhost`.
- **SPF / DKIM / DMARC documentation** in `README.md`: DNS record examples, roll-out
  sequences, key rotation procedure.
- **E2E test suite** (`tests/e2e/`):
  - `test_dkim_spf.py`: verifies DKIM-Signature header fields and `Received-SPF: Pass`.
  - `test_greylisting.py`: added `test_greylisting_known_sender_not_delayed` — tests the
    milter-greylist auto-whitelist mechanism end-to-end.
  - `greylist.conf`: custom config with `greylist 5s` and `autowhite 1d`; removes
    `racl greylist default` so built-in auto-whitelist works correctly.
  - `dns/` container (dnsmasq): authoritative for `test.local`, publishes A, MX, and
    SPF TXT records; enables realistic SPF testing without external DNS.
  - `docker-compose.yml`: added `opendkim`, `dns` services; `dkim-net`, `dns-net`
    networks; postfix wired to both milters with `MYNETWORKS=127.0.0.0/8`.
  - `conftest.py`: `OPENDKIM_HOST` config variable for optional service detection.
  - `run-e2e.sh`: starts `opendkim` and `dns` services alongside the rest of the stack.
- **Maildir layout regression test** (`tests/e2e/test_maildir_layout.py`): delivers a
  mail and asserts the on-disk maildir is created at `<domain>/<localpart>` (not the
  full-email path), so legacy mailboxes cannot silently be orphaned again. Needs the
  new shared `maildata` volume (dovecot store, mounted read-only into the test runner).
- **Frontend UI test suite** (`tests/e2e/`):
  - `Dockerfile.playwright`: Playwright Python image for browser-based tests.
  - `requirements.playwright.txt`: `pytest` + `pytest-playwright` dependencies.
  - `docker-compose.ui.yml`: overlay adding PostfixAdmin (own DB), SnappyMail, and the
    Playwright `ui-test-runner` service alongside the existing mail stack.
  - `test_webui.py`: tests PostfixAdmin admin setup/login/domain/mailbox creation and
    SnappyMail domain config, user login, mail reading, and mail sending end-to-end.
  - `run-ui.sh`: starts the full UI test stack and runs Playwright tests.
  - `package.json`: new `test:ui` script (`bash tests/run-ui.sh`).
- **Manual test stack** for exercising the isolated e2e stack by hand in a browser:
  - `tests/e2e/docker-compose.manual.yml`: overlay that publishes the web UIs and
    mail ports (SnappyMail, PostfixAdmin, SMTP, IMAP, POP3) on fixed but uncommon
    host ports (`478xx`, low collision probability) — same isolated `test.local`
    stack, no internet mail.
  - `tests/run-manual.sh`: brings the stack up (without the automated test-runner),
    left running, primes the PostfixAdmin schema (so pages no longer return HTTP 500
    before setup), and prints the access URLs plus the pre-seeded `alice`/`bob`
    credentials.
  - `package.json`: new `test:manual` / `test:manual:stop` scripts.
  - `README.md`: «Manual Testing in the Isolated Test Stack» section with the
    isolation guarantee, credentials, and a send/receive walk-through.

### Changed

- **e2e test stack uses a single shared database** (mirrors production): Postfix,
  Dovecot and PostfixAdmin now all use `postfixadmin-db`; the separate mail `db`
  service and the `tests/e2e/init/db.sql` pre-seed were removed. Accounts are no
  longer pre-seeded — the `provision_mail_accounts` fixture creates the domain and
  the `alice`/`bob` mailboxes through PostfixAdmin (the schema for Postfix/Dovecot
  is created by PostfixAdmin's setup), and a dedicated test verifies them. Dovecot
  uses its default `SHA512-CRYPT` scheme, matching PostfixAdmin's `php_crypt`
  hashes; test passwords now satisfy PostfixAdmin's policy (`alicepass12` /
  `bobpass12`). The manual stack inherits this: accounts created in PostfixAdmin
  are the ones the webmail uses.
- **README** restructured to the standard «Template A» layout (Purpose → Why →
  Features → Usage → Administration → Development → Internals). The opening now
  pitches the project and names the **webmail**; end-user mail-client settings,
  operator tasks and developer/testing topics are separated into clear sections.
- **postfix `start.sh`**: ported from bash to POSIX sh; greylisting code refactored
  into the reusable `_add_milter()` function.
- **postfix `Dockerfile`**: `RUN` commands split to one per line; added
  `postfix-policyd-spf-perl` and `master.cf` entry for the policy service; added
  `OPENDKIM`, `CHECK_SPF`, `MYNETWORKS` ENV declarations.
- **postgrey `Dockerfile`**: refactored to one `RUN` per line; added multi-stage
  pattern (`FROM build` final stage to collapse layers); fixed ENTRYPOINT flags
  (`-D` daemon mode, correct socket syntax); replaced inline `sed`/`printf` config
  patch with a proper `ADD greylist.conf`.
- **dovecot**: updated to Dovecot 2.4 configuration API — `conf.d/` pattern for
  runtime-generated config, new `passdb sql {}` block syntax, `mail_driver`/`mail_path`
  instead of `mail_location`; added `dovecot-pop3d` package; added `dovecot.conf`.
- **mailforward `start.sh`**: ported from bash to POSIX sh (shebang and condition
  syntax); greylisting port detection uses POSIX parameter expansion.
- **README.md**: fixed SMTP submission port (`578` → `587`, two occurrences); replaced
  `docker-compose` with `docker compose` throughout.

### Fixed

- **Dovecot 2.4 maildir path regression** (`dovecot/`): the 2.4 config port changed
  the maildir layout from the pre-2.4 `maildir:/var/mail/domains/%d/%n`
  (domain/localpart) to `mail_path = /var/mail/domains/%{user}` (full email), and
  the userdb `home` likewise. Existing maildirs live at `<domain>/<localpart>/`, so
  after the upgrade **every mailbox appeared empty and Sieve filters were gone**
  (dovecot looked under `<full-email>/` and created empty maildirs there; Sieve
  scripts live in `home`). Restored to `%{user | domain}/%{user | username}` for
  both `mail_path` and `home`. Pinned by the new `test_maildir_layout.py` regression
  test so the on-disk layout can no longer drift unnoticed.
- **Dovecot 2.4 TLS config** (`dovecot/`): the SSL block used the pre-2.4 setting
  names (`ssl_cert`/`ssl_key`/`ssl_prefer_server_ciphers`), which crashed Dovecot
  2.4 with a fatal `Unknown setting: ssl_cert` and a restart loop whenever a
  certificate was present. Now uses the 2.4 names (`ssl_server_cert_file`/
  `ssl_server_key_file`, no `<` prefix) and `ssl = yes` instead of `required`
  (`required` conflicts with `auth_allow_cleartext = yes` in 2.4 and would block
  internal plaintext login on 143).
- **e2e tests**: DKIM/SPF tests no longer skipped (`OPENDKIM` is always configured
  in the stack); PostfixAdmin mailbox-creation test now verifies the mailbox is
  actually listed for the domain; `run-e2e.sh`/`run-ui.sh` no longer abort under
  `set -e` before collecting failure logs; obsolete `tests/e2e/Dockerfile` and
  `tests/e2e/requirements.txt` removed (superseded by the Playwright image).
- `smtpd_tls_auth_only = no` set explicitly when TLS is not configured, preventing
  Postfix from silently refusing cleartext auth in development setups.
- **Frontend UI test suite** (`tests/e2e/test_webui.py`): the full PostfixAdmin and
  SnappyMail end-to-end flow now passes (all 38 e2e tests green). Required fixes:
  - **PostfixAdmin** (`postfixadmin/`): custom settings moved to `config.local.php`
    (env-var overrides only) so the Alpine package's `config.inc.php` 4.x defaults —
    including `$CONF['dkim']` — are preserved; replacing the main config crashed setup
    with a `Config::bool('dkim')` fatal. Both files are placed under
    `/root/etc/postfixadmin/` so `COPY --from=build /root/ /` includes the symlink
    targets. `display_errors`/`display_startup_errors` disabled and `clear_env = no`
    set in the PHP-FPM pool so PHP warnings no longer corrupt HTML/JSON responses.
  - **PostfixAdmin proxy** (`postfixadmin-proxy/`): nginx `ROOT` kept at the app's
    `public/` directory (PostfixAdmin's required layout). The web UI is reached at
    `/setup.php`, `/login.php`, … (no `/public/` prefix) and the bare root no longer
    shows the «directory layout changed» notice. URLs updated accordingly in the
    tests and README.
  - **SnappyMail** (`rainloop/Dockerfile.php-fpm`): same PHP-FPM hardening
    (`display_errors` off, `clear_env = no`); the deprecation warnings were corrupting
    the admin `AdminAppData` JSON and blocking login. `VOLUME` corrected to `/app/data`.
  - **`test_webui.py` selectors** updated for PostfixAdmin 4.x (two-step `setup.php`
    with repeated `setup_password`, `edit.php?table=…`, `value[…]` fields) and the
    SnappyMail 2.38 SPA (Knockout/Squire): identity-popup dismissal, `emailsTags` To
    field, Squire body editor, double-fill of the SMTP host to defeat the
    `smtpHostFocus` auto-fill, and Sent-folder "Do not use" handling on send.
  - **`docker-compose.yml`** (e2e): SnappyMail admin seeded with `admin_login`/
    `admin_password`; `SM_ADMIN_USER` exposed to the test runner.
