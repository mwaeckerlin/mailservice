# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [3.2.0]

### Fixed — database persistence and engine

- The production compose mounted the account database volume at
  `/usr/lib/mysql` instead of `/var/lib/mysql` — the volume persisted
  **nothing**: every container recreate silently dropped all domains,
  mailboxes and password hashes. The volume now targets the real data
  directory, pinned by a new compose-contract check.
- The database service now runs `mariadb:11` (the stack requirement —
  Dovecot 2.4 needs the TLS the 11.x server offers, see README
  «Database version») instead of a rolling `mysql` image whose 8.4
  release additionally removed the `--default-authentication-plugin`
  switch the compose passed (start-up failure on next pull). Also
  pinned by the compose contract.

### Changed — security hardening across the stack

- Without a TLS certificate the postfix image no longer offers SASL
  authentication at all (stack invariant: passwords never travel
  unencrypted; same behaviour as dovecot). Deliberately TLS-less
  deployments can opt in via `POSTFIX_ALLOW_CLEARTEXT_AUTH=yes`.
  Pinned by a new e2e scenario (`postfix-nocert`) with valid
  credentials.
- Every image of the postfix family (`postfix`, `smtp-relay`,
  `smtp-relay-tls`, `mailforward`) and rspamd now whitelist-validates
  every environment value before rendering it into configuration files
  — a malformed value (embedded newline: config injection) refuses to
  start with a clear `invalid <VAR>` error. Each submodule carries its
  own config-validation test suite.
- The SnappyMail **nginx** image now verifies the release tarball's
  OpenPGP signature against the pinned key exactly like the php-fpm
  image — it serves all JavaScript the browser executes and previously
  downloaded without any check.
- The relay family's TLS setup is modernised: deprecated
  `smtpd_use_tls`/`smtpd_tls_eecdh_grade` knobs and the frozen 2015-era
  cipher list are gone, the protocol floor is TLS 1.2 (opportunistic —
  a legacy sender without TLS 1.2 falls back to plaintext and the mail
  still arrives).
- The PostfixAdmin admin UI (plain HTTP) is published on loopback only;
  remote access goes through a TLS reverse proxy (README «Trade-off —
  admin UI without TLS»). Pinned by the compose contract.

### Fixed — test harness

- `tests/run-e2e.sh` forwards pytest arguments again: `docker compose
  run` replaces the service command entirely, so `-k <test>` used to be
  exec'd as the entrypoint instead of selecting tests.

### Documentation

- README v2 leftovers corrected: the component overview names rspamd
  (not OpenDKIM/milter-greylist), the roadmap note «virus scanning is
  planned» is replaced by the integrated ClamAV description, and the
  `NOTIFY_SMTP` example reflects the numeric-IPv4 requirement.

## [3.1.0]

### Changed — every image in the stack is now headless

`postfix`, `dovecot`, `smtp-relay`, `smtp-relay-tls` and `mailforward`
now follow the same pattern as `rspamd`, `clamav` and `redis`: a
compiled C++ `init` binary configures the service from the environment
and execs the daemon — the shipped images contain **no shell, no
busybox, no perl and no package manager**. An attacker who reaches
code execution in any container finds nothing to pivot with. All
environment knobs and the on-disk data layouts are unchanged; the
whole e2e suite plus new relay-family tests pin the behaviour.

- The postfix family images inherit the accumulated `main.cf` from
  their parent image at build time (`smtp-relay` → `mailforward` →
  `postfix`); each build stage installs postfix fresh and layers its
  deltas on top.
- Every image now offers `init --healthcheck` (TCP probe of its main
  listener) for Docker healthchecks; mailforward's old bash/telnet
  `health.sh` is gone.
- The dovecot Bayes-autotrainer wrappers `report-spam` / `report-ham`
  are one static binary execing `rspamc` — same paths, same sieve
  contract as the former shell wrappers.
- The relay family (`smtp-relay`, `smtp-relay-tls`, `mailforward`)
  gets the same high, configurable delivery limits as postfix:
  `MESSAGE_SIZE_LIMIT` (default 100 GiB, was postfix's 10 MB default)
  and `SMTP_HARD_ERROR_LIMIT` (default 20; mailforward previously
  hardcoded 1, which turned a single rejected recipient into an
  abrupt disconnect).
- The relay family also gets postfix's `DISABLE_DNSBL` switch: strips
  the DNS-blocklist lookups from the smtpd restrictions for
  test/offline stacks whose resolver cannot answer the blocklist
  zones (each lookup stalled the SMTP dialogue until the resolver
  timeout).

### Fixed
- `mailforward`: the virtual alias map works again on current Alpine —
  alpine builds postfix without Berkeley DB, so the historical `hash:`
  map type no longer exists and every alias recipient drew a 451
  temporary failure. The map is now compiled and looked up as `lmdb:`
  (alpine's default type). Pinned by the new end-to-end forward test.
- **The mail queue is now persistent.** Postfix answers `250 Ok` as
  soon as a mail is fsync'ed into its queue — from that moment the
  server owns delivery and the sender never retries; a deferred mail
  can sit in the queue for hours or days. `/var/spool/postfix` was
  never a volume (in any previous version), so every container
  recreate or image update silently destroyed
  accepted-but-undelivered mail. All postfix-based images now declare
  the queue as a volume, the compose maps named volumes
  (`postfix-spool`, `mailforward-spool`), and the new
  `tests/compose-contract.sh` fails the suite if the mapping is ever
  removed.
- The image contract test now covers **all** own images of the stack
  (previously only rspamd, clamav, postfixadmin(+proxy), snappymail).
- New e2e tests pin the relay-family invariants: SMTP banner/EHLO,
  STARTTLS handshake on smtp-relay-tls, and a real end-to-end
  mailforward virtual-alias forward delivered via MX lookup to the
  test sink — plus a permanent 5xx for unmapped alias recipients.

### Removed
- `postfix`: the perl-based `postfix-policyd-spf-perl` and its
  `CHECK_SPF` knob (v3.0.0 had already unwired it by default) — SPF
  verification is rspamd's SPF module.
- `postfix`: baked-in debug settings (`debug_peer_list`, TLS handshake
  loglevel 2). TLS logging is now `POSTFIX_TLS_LOGLEVEL` (default 0 —
  production default; the e2e stack sets 2 for diagnosable logs).
- `smtp-relay-tls`: the unused `DAYS` env; `postfix`: the unused
  `LOCAL_DOMAINS` env.

## [3.0.1]

### Security
- `dovecot`: verbose auth debug logging is no longer baked into the
  image — it is off by default and only enabled by the new
  `DOVECOT_DEBUG_AUTH=yes` diagnostics override (the e2e stack sets it
  to keep failure logs verbose).
- `dovecot`: the forced-TLS login invariant is now pinned by e2e
  tests — cleartext authentication on an unencrypted connection is
  proven to be refused for IMAP, POP3 and ManageSieve.
- `dovecot`: the root run-mode of the container and the trust model of
  the internal LMTP/SASL listeners are now documented as explicit
  security trade-offs in the image README.

### Changed
- `dovecot`: image cleanup — removed unused environment leftovers,
  modernized the Dockerfile (no more build warnings), completed the
  declared ports (POP3, POP3S, ManageSieve).

## [3.0.0]

### ⚠️ BREAKING — mail filtering stack replaced

v3.0.0 retires the historical multi-container antispam chain
(`opendkim`, `opendmarc`, `postgrey`, `postfix-policyd-spf-perl`)
and replaces it with **one `rspamd`** container, backed by a headless
`redis` for state and `clamav` for antivirus. Rspamd does DKIM
signing, DKIM verify, DMARC, SPF, greylisting, Bayes-scored spam
and virus scanning through a single milter port.

**If your existing `docker-compose.yml` still names `opendkim`,
`opendmarc`, `postgrey` or the old milter envs on `postfix`** it will
fail to boot until you migrate. See the README section «Upgrading
from v2.x (opendkim + opendmarc + postgrey + policyd-spf)» — three
services to swap, one DKIM-key volume rename, no DNS change.

### Added
- `mwaeckerlin/rspamd` — headless three-stage scratch image with a
  compiled C++ `init` that generates one 2048-bit DKIM key per
  domain on first start (via `rspamadm dkim_keygen`), stages
  `local.d/*.conf` from templates according to `DKIM_DMARC`, and
  optionally mails the DNS TXT records to `NOTIFY_EMAIL` via a
  minimal in-process SMTP client.
- `mwaeckerlin/redis` — headless three-stage scratch image (only
  `redis-server`, no `redis-cli`). AOF persistence + `allkeys-lfu`
  eviction defaults; backs rspamd's Bayes / greylist / ratelimit
  state.
- `mwaeckerlin/clamav` — three-stage image running `clamd` +
  `freshclam --daemon` under a supervising C++ `init` (bootstraps
  the DB, keeps freshclam running as a child, execs into clamd as
  PID 1).
- SnappyMail release tarball is now OpenPGP-verified against a key
  pinned in `rainloop/snappymail-signing-key.asc` at build time;
  the build refuses a tarball that does not verify. `SKIP_GPG_VERIFY=1`
  build-arg exists solely for the e2e stack, which ships the
  placeholder key on purpose.
- OpenPGP in the webmail: the SnappyMail image ships the php-gnupg
  extension (compiled from the pinned upstream release) plus the gpg
  binary it drives — verifying signed mail and signing/encrypting
  outgoing mail works without extra installation.
- `RSPAMD_LOG_LEVEL` env on rspamd (default `notice`; `info` shows
  every learn/scan decision — used by the e2e stack for diagnosable
  failure logs).
- Bayes autotraining via dovecot's `imap_sieve`: moving mail into or
  out of the `Junk` folder in any IMAP client fires
  `sieve/learn-{spam,ham}.sieve` → `rspamc learn_{spam,ham}` against
  the sibling rspamd controller. Event-driven, no cron.
- `SPAM_DELIVERY_MODE` env on dovecot: `reject` (default; mailservice
  design), `mark` (add `X-Spam-Flag` etc. headers, never touch the
  body / subject to protect the sender's DKIM signature), `folder`
  (server-side sieve routes to IMAP «Junk», silent quarantine, not
  recommended).
- README section «Antispam, antivirus, signing — one rspamd» plus
  «Antivirus (ClamAV)», «Bayes-scored spam and autotraining»,
  «SPAM_DELIVERY_MODE» and legal-framing note on «SMTP-reject vs.
  Aufbewahrungspflicht».
- e2e tests: `test_virus_reject.py` (clamd INSTREAM probe + EICAR
  inline in the body + EICAR as attachment),
  `test_spam_score_reject.py` (GTUBE + clean-mail sanity),
  `test_bayes_autolearn.py` (Bayes counter advances on IMAP move
  to/from Junk), `test_delivery_mode.py` (reject-mode contract),
  `test_snappymail_gpg_verify.py` (positive + tampered-tarball +
  unknown-key cases of the GPG-verify machinery), and a php-gnupg
  image contract check.
- e2e now also exercises TLS end-to-end (`test_tls.py`): a `certs-init`
  container drops a self-signed cert into the `letsencrypt` volume so
  the cert-present → TLS-enabled wiring is tested — STARTTLS on SMTP,
  authenticated submission over STARTTLS, IMAPS on 993, IMAP STARTTLS
  on 143.

### Changed
- **Delivery-affecting limits are now high, configurable and
  documented** — a legitimate mail is never bounced by an artificial
  default:
  - `postfix`: `message_size_limit` and `smtpd_hard_error_limit` are no
    longer hardcoded. New env `MESSAGE_SIZE_LIMIT` (bytes, default
    **100 GiB** so even several photos/videos in one mail pass, `0` =
    unlimited; `mailbox_size_limit` is pinned to the same value) and
    `SMTP_HARD_ERROR_LIMIT` (default raised to the postfix standard 20 —
    the previous value of 1 turned a single protocol hiccup into an
    abrupt 421).
  - `clamav`: scan limits raised to clamav's architectural maxima
    (`CLAMD_MAX_FILESIZE` 2 GiB — clamav's internal hard cap,
    `CLAMD_MAX_SCANSIZE` 4 GiB) and the previously-unset
    `CLAMD_STREAM_MAXLENGTH` (4 GiB; clamd's own default is only 25 MB,
    which silently aborted the Rspamd INSTREAM for larger mails).
    Scanning is fail-open: a mail exceeding the limits — or larger than
    clamav can scan at all (>2 GiB per file / >4 GiB per message, a
    clamav architectural limit) — is delivered unscanned, never bounced.
  - `rspamd`/`redis` documented as never rejecting on size; the only
    reject knob remains the spam score vs. `RSPAMD_REJECT_SCORE` (15,
    Rspamd's own conservative default; see rspamd README «Scores and
    thresholds»).
- `postfix`: `OPENDKIM`, `OPENDMARC` and `GREYLIST` env vars removed;
  one new `RSPAMD` env (host or host:port, default port 11332).
  `CHECK_SPF` auto-disables when `RSPAMD` is set — rspamd's SPF
  module covers this and running policyd-spf-perl in parallel would
  produce contradictory verdicts.
- `dovecot`: adds `rspamd-client` to the build for the `rspamc`
  binary used by the Bayes-autotrainer sieve wrappers. `imap_sieve`
  and `sieve_extprograms` are now wired in `local.conf`. `start.sh`
  writes `/etc/dovecot/sieve/spam-to-junk.sieve` from
  `SPAM_DELIVERY_MODE` at start-up.
- `DKIM_DMARC` semantics preserved (off/log/permissive/reject) —
  same four modes, same behaviour contract, now enforced by rspamd
  instead of opendkim + opendmarc (bad-signature rejection via a
  force-action rule, DMARC `p=reject` enforcement via the DMARC
  module's reject action).
- **Greylisting is now score-based** (semantic change): postgrey
  delayed every unknown sender triplet with a 4xx; rspamd's greylist
  module only delays mail whose spam score crosses the greylist
  threshold. Clean mail from first-time senders is delivered on the
  first attempt — aligned with the «reliability over filtering»
  design. Own users (SASL) remain exempt in all cases.
- The e2e stack now runs three parallel rspamd instances (one per
  DKIM_DMARC mode) sharing one redis and one clamav, replacing the
  three parallel opendkim + opendmarc pairs of v2.x. Greylist
  timeouts / expires and the local-IP-check flag are env-driven so
  the test suite can shrink the delay from 300 s to 5 s without
  patching the rspamd config.
- `postfix/README.md` remains minimal — the RSPAMD env is documented
  in the Dockerfile's ENV block and in the mailservice compose.
- **Authentication is now encrypted-only by default.** Dovecot
  `auth_allow_cleartext` defaults to `no` (new `DOVECOT_ALLOW_CLEARTEXT`
  env), so the cleartext PLAIN/LOGIN mechanisms are offered only over
  TLS — a client must use IMAPS/POP3S/managesieve-TLS or issue STARTTLS
  before authenticating, and a password is never transmitted in the
  clear. Postfix keeps `smtpd_tls_auth_only=yes`, so SMTP submission
  SASL is likewise TLS-only. Soften only deliberately via
  `DOVECOT_ALLOW_CLEARTEXT=yes` (e.g. a trusted isolated network without
  certificates); see the dovecot and mailservice READMEs.

### Removed
- Submodule pointers: `opendkim`, `opendmarc`, `postgrey`. The
  filter chain lives entirely in `rspamd` + `redis` + `clamav`.
- `postfix-policyd-spf-perl` is still installed in the postfix image
  for backward compatibility (`CHECK_SPF=yes` overrides the auto-off)
  but is no longer wired by default.
- `tests/dkim-dmarc-mode.sh` and `tests/opendkim-multidomain.sh`
  (opendkim/opendmarc conf-based shell tests, obsolete under rspamd).

### Security
- The `postfixadmin` image carries a **documented, time-bounded
  workaround** for two upstream `spomky-labs/otphp` advisories
  (`GHSA-g7m4-839x-ch6v` HIGH, `GHSA-2jx3-65f3-xr8r` MEDIUM) that are
  unfixed in the version PostfixAdmin pins. A code audit shows the
  vulnerable code paths (`Factory::loadFromProvisioningUri`) are not
  reachable — PostfixAdmin only ever *creates* TOTP secrets and
  provisioning URIs. The build therefore proceeds with the audited
  version, and a build-time guard re-surfaces the issue for review if
  upstream still has not fixed it by 2026-08-16. See README «Security
  workarounds».

## [2.0.0]

### ⚠️ BREAKING — please read before upgrading

**If your existing `docker-compose.yml` does NOT include `opendkim` or
`opendmarc` services** (typical for older installs), a plain image pull
is fully backward-compatible: `postfix/start.sh` only wires the milters
into the chain when the `OPENDKIM` / `OPENDMARC` env vars are set, and
both default to empty. Your postfix keeps its previous milter chain
(usually just `postgrey`), no legitimate mail can be bounced by
DKIM/DMARC because there is no DKIM/DMARC verification running. To
actually add DKIM/DMARC to such a stack, see the «Adding DKIM + DMARC
to an existing compose file» section in `README.md` — always start with
`DKIM_DMARC: log`.

**If your existing `docker-compose.yml` DOES include `opendkim`** (or
you copy the repo's `docker-compose.yml`), the DKIM/DMARC enforcement
knobs have been unified. Anyone upgrading a running mailservice
**must decide explicitly** whether they want the new strict verification
behavior, or want to try it first without risking any legitimate mail
being bounced.

- The old env vars are **gone**: `DKIM_ENFORCE`, `DKIM_REJECT_ON_KEY_ERROR`
  (never released but existed on `master`), and the implicit
  «always reject bad/unknown-key» hard-wired into opendkim.
- One new env var takes their place on both `opendkim` and `opendmarc`:
  `DKIM_DMARC` with four levels — `off`, `log`, `permissive`, `reject`.
- **Image default is `reject`** (strict enforcement). Anyone who does a
  blind `docker compose pull && up -d` therefore ends up in the strictest
  mode and may bounce legitimate mail from senders with wonky DKIM/DMARC.
- **The upgrade path is: set `DKIM_DMARC: log` on both services first**,
  watch delivered mail for `Authentication-Results: … dkim=fail`,
  `dkim=none`, `dmarc=fail (p=… dis=none)` headers for a few days, and
  only then escalate to `permissive` or `reject`. See the new
  «Upgrade & Monitoring» section in `README.md` for the exact commands
  and log/header patterns to watch.
- The prod `docker-compose.yml` in this repo now ships with an explicit
  `DKIM_DMARC: log` on both milter services and a comment explaining the
  escalation path — so a fresh clone starts in log mode, not reject.

### Added

- **Single DKIM/DMARC-mode knob `DKIM_DMARC`** on both opendkim and
  opendmarc, four levels — `off` (no verify, no A-R stamping),
  `log` (verify + stamp Authentication-Results, never reject — the
  monitor mode operators run for a few days after upgrading),
  `permissive` (opendkim rejects bad signatures and unknown DKIM keys,
  accepts unsigned; opendmarc rejects on `p=reject` hard fail — the
  intended production semantic: DKIM is optional but must be correct if
  the sender publishes it) and `reject` (adds «reject unsigned» on
  opendkim on top of permissive). Both containers must be set to the
  same value or DMARC alignment breaks.
- **`DKIM_KEYERROR_ACTION`** env on opendkim: `reject` (default) sends
  the sender an immediate `550 5.7.20`; `tempfail` returns a 4xx so the
  sender-side MX retries for its usual timeout (~5 days) — useful during
  a DKIM key rotation where a legitimate sender may briefly publish a
  new selector before DNS propagation is complete. Only takes effect
  when `DKIM_DMARC` is `permissive` or `reject`.
- **e2e stack:** third `opendkim` / `opendmarc` / `postfix` triple
  wired to `DKIM_DMARC=log` (`postfix-log`) so the log-mode behavior
  is covered by real end-to-end tests.
- **`tests/dkim-dmarc-mode.sh`**: config-level test that starts opendkim
  and opendmarc briefly in each of the four modes and asserts the
  runtime `opendkim.conf` / `opendmarc.conf` contains (or omits) the
  expected directives.

- **Image contract**: the shipped images are now checked automatically for
  being headless — no shell, no bash, no busybox, no perl. Whoever gains code
  execution inside a container finds no tool there to go further. Covered so
  far: opendkim, opendmarc, postfixadmin, postfixadmin-proxy and both
  SnappyMail images. postfix, dovecot, postgrey, smtp-relay, smtp-relay-tls
  and mailforward still start through a shell script and therefore still ship
  a shell; they join the contract once their entrypoint is a binary.

- **README** (Design philosophy): new «Reject reasons — end-user first,
  then the admin» subsection — every SMTP reject should tell the sender
  in plain language what happened, followed by the technical hint an
  operator needs to fix the misconfig. Feature: the milter reject
  templates will be aligned to this in a follow-up.
- **OpenDMARC service** (`opendmarc/`): new milter that enforces DMARC on
  incoming mail. Runs after opendkim in the milter chain, consumes
  opendkim's `Authentication-Results` (via shared `AUTHSERV_ID`), does its
  own SPF check via `libspf2`, and **rejects at SMTP time** on a hard
  DMARC fail against a sender that publishes `_dmarc … p=reject`. Fills
  the gap opendkim alone cannot cover: mail from a DMARC-protected sender
  that arrives entirely unsigned is now rejected even without
  `DKIM_ENFORCE=yes`. Same shell-free three-stage image as opendkim
  (`init.cpp` compiled statically → `tar cph+ldd` collect →
  `mwaeckerlin/scratch`, no shell/perl/busybox in the runtime).
  Configurable via `AUTHSERV_ID` (must match opendkim) and `TRUSTED_HOSTS`
  (RFC1918 + loopback by default, skips DMARC for own users). Wired in
  by default in `docker-compose.yml` via `OPENDMARC: opendmarc` on
  postfix; postfix appends it as a milter after opendkim.
- **OpenDKIM multi-domain support** (`opendkim/`): new `DOMAINS` environment
  variable (space-separated list) generates and manages one 2048-bit RSA DKIM
  key per domain, prints one DNS TXT record per domain on first start, and
  signs `From:` addresses of every listed domain with the matching key. Adding
  a domain later reuses existing keys (only the new key is generated). The old
  `DOMAIN` (singular) variable is kept as the single-domain fallback.
- **OpenDKIM verification tightened by default** (`opendkim/`): incoming mail
  with a bad signature (`On-BadSignature`) or a signature referencing a DKIM
  key that does not exist in DNS (`On-KeyNotFound`) is now **rejected** at
  SMTP time — **always**, independent of `DKIM_ENFORCE`. DKIM in DNS is not
  optional once a sender publishes it; a mis-signed or unknown-key mail is
  either misconfigured or forged and never silently delivered.
- **OpenDKIM AUTHSERV_ID + NAMESERVERS env vars** (`opendkim/`): new
  `AUTHSERV_ID` sets the `AuthservID` in every `Authentication-Results`
  header — **must match opendmarc's `AUTHSERV_ID`** so opendmarc trusts
  opendkim's `dkim=` verdict when deciding DMARC alignment. Also new
  `NAMESERVERS` (space-separated list) is written into `Nameservers`
  and (as fallback) into `/etc/resolv.conf` at start-up so operators
  can bypass a mangled container resolver (e.g. `NAMESERVERS: "1.1.1.1"`
  in a Docker Swarm where the embedded resolver rewrites NXDOMAIN into
  SERVFAIL).
- **OpenDKIM InternalHosts / ExternalIgnoreList split** (`opendkim/`):
  `TRUSTED_HOSTS` env now maps only to `InternalHosts` (sign path);
  `ExternalIgnoreList` is hard-wired to loopback so a non-loopback
  sender's incoming DKIM signature is always verified, even if the
  same sender's outgoing mail is signed via `InternalHosts`.
- **OpenDKIM enforce mode** (`opendkim/`): new `DKIM_ENFORCE` environment
  variable — when set to `yes`, **unsigned** incoming mail is also rejected
  (`On-NoSignature reject`) on top of the always-on bad/unknown-key rejects
  above. Default `no` accepts unsigned mail (right for a public-facing MX
  that must not bounce mail from small senders that don't publish DKIM at
  all); `yes` is right for an ingress where every peer is known to sign.
- **OpenDKIM InternalHosts override** (`opendkim/`): new `TRUSTED_HOSTS`
  environment variable (space-separated hosts/CIDRs, default =
  loopback + RFC1918) exposes `InternalHosts`/`ExternalIgnoreList` for
  per-instance tightening — e.g. an enforce ingress can trust only loopback so
  that RFC1918 senders are actually verified.
- **E2E tests** (`tests/`):
  - `test_dkim_multidomain_sign.py`: two new tests prove that mail from a
    second signing domain (`@other.local`) gets a DKIM-Signature with
    `d=other.local`, and that adding the second domain does not break signing
    for the original one.
  - `test_dkim_verify.py`: four new tests prove the full DKIM verify matrix
    on a receiving instance — correctly signed → accept + `dkim=pass`;
    unsigned + `DKIM_ENFORCE=no` → accept; unsigned + `DKIM_ENFORCE=yes` →
    reject at SMTP time (mail never lands in INBOX); tampered signature +
    `DKIM_ENFORCE=yes` → reject. Signs with `dkimpy` as an external sender
    on `external.local`; matching public key published in the test dnsmasq
    zone; private key committed at `tests/e2e/testkeys/` (test key only).
  - `tests/image-contract.sh`: image-level contract tests, run by
    `run-e2e.sh` after `docker compose build` and before starting the stack —
    hard-fails the run if the shipped opendkim image contains `/bin/sh`,
    `/usr/bin/perl` or `/bin/busybox`, or if the multi-domain init does not
    generate both DNS records for `DOMAINS="alpha.local beta.local"`.
  - `opendkim-strict` + `postfix-strict` services added to the e2e stack for
    the enforce-mode tests; DKIM key + DNS records for `external.local` and
    a second signing zone for `other.local` added to `dns/dnsmasq.conf`;
    `dkimpy` added to the Playwright image; DKIM-related whitelist entries
    added to `tests/e2e/greylist.conf` so the new senders are not delayed
    by the greylist milter's tempfail.
- **README** (SPF, DKIM, DMARC): new «Multi-domain» subsections show how one
  mailservice serves several sending domains — SPF via `include:` chaining,
  DKIM via `DOMAINS=` and one DNS record per domain, DMARC via one
  `_dmarc.<domain>` record per domain with a shared report inbox.
- **README**: image dependency chain documented (`smtp-relay` → `mailforward` → `postfix`)
- **README** (Administration): database version requirement documented — MariaDB 11+
  is required because Dovecot 2.4's MySQL client needs TLS to the database; for an
  older MariaDB without TLS, set `ssl = no` in Dovecot's MySQL passdb block.
- **README** (Usage): after a server upgrade/migration every user must set a new
  password in PostfixAdmin — Dovecot 2.4 refuses legacy weak password hashes
  (e.g. `MD5-CRYPT`), so old passwords stop working until re-hashed.

- **README** (Design philosophy): new «Outbound» section — a client only hands
  mail to Postfix; Postfix owns delivery, queuing and retries; greylisting never
  applies to own (authenticated/internal) users; only permanent errors are
  reported, as a bounce.
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

- **OpenDKIM image is now multi-stage and shell-free** (same pattern as
  `mwaeckerlin/nginx` and `mwaeckerlin/php-fpm`): three stages — a statically
  linked C++ helper (`init.cpp`) is compiled in stage 1; stage 2 installs
  `opendkim` + `openssl` and uses `tar cph … + ldd` to collect only the
  needed binaries, shared libraries and configs into `/root/`; stage 3 is
  `FROM mwaeckerlin/scratch` and just `COPY --from=build /root/ /`.
  The runtime image contains no shell, no package manager, and no Perl —
  `opendkim-genkey` (Perl script) is replaced by `init.cpp`, which generates
  the 2048-bit RSA key per domain by forking `openssl genrsa` directly. The
  old `opendkim/start.sh` is gone. Multi-domain behavior is unchanged.
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

- **Sending mail no longer fails with «451 Greylisting in action»** (`postgrey/`):
  since the migration from postgrey to milter-greylist, the milter ran for EVERY
  smtpd connection — the former `check_policy_service` only ran after
  `permit_sasl_authenticated, permit_mynetworks`. On top of that the container
  started milter-greylist with `-A` (explicitly disables the built-in SMTP-AUTH
  whitelisting) and `-a 5` (auto-whitelist for only 5 **seconds**), so every
  webmail/IMAP-client submission was greylisted again and again and the user had
  to re-send manually — the mail never reached the postfix queue. Fixed:
  - milter-greylist flags: `-A` removed, auto-whitelist set to 35 days
    (`-w 300 -a 35d`, the classic postgrey defaults).
  - `greylist.conf`: SASL-authenticated clients (`racl whitelist auth /.*/`) and
    the internal container networks (loopback + RFC1918) whitelisted — the milter
    equivalent of the former `permit_sasl_authenticated, permit_mynetworks`;
    `racl greylist default` removed (it disables the built-in auto-whitelist).
  - Pinned by a new e2e regression test: a SASL-authenticated submission must be
    accepted, never greylisted (`test_authenticated_submission_not_greylisted`).
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
