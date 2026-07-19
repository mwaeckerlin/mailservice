# MailService

Run your own complete email service for your domain within a Docker stack:
a full mail server with **webmail**, an **admin web UI**, and modern
deliverability and anti-abuse (SPF, DKIM, DMARC, greylisting) — everything
needed to send, receive and read mail under your own domain, without handing
your correspondence to a third-party mail provider.

## Why MailService

- **A complete suite, not just an MTA.** Postfix (SMTP/TLS), Dovecot
  (IMAP/POP3/Sieve), the **SnappyMail** webmail, the **PostfixAdmin** admin UI,
  and rspamd (DKIM, SPF, DMARC, greylisting, spam scoring, ClamAV antivirus) —
  wired together and ready to run.
- **Reliability over filtering.** Every message is either delivered to the
  recipient's INBOX or rejected with a clear, RFC-compliant SMTP error. No spam
  folder, no silent drops — mail never vanishes into a black hole (see
  [Design philosophy](#design-philosophy-reliability-over-filtering)).
- **Accepted by the big providers.** SPF, DKIM and DMARC work out of the box, so
  your outgoing mail passes authentication at the receiving side.
- **Composable and reusable.** Built from small, independent images (e.g.
  `smtp-relay` for other apps such as Nextcloud or Gitea) — run only what you need.
- **Self-hosted and private.** Runs on your own Docker host. An isolated test
  stack lets you try the whole thing fully offline before you go live.

## Features

- Webmail for end users (**SnappyMail**)
- Admin web UI to manage domains, mailboxes and aliases (**PostfixAdmin**)
- SMTP send and receive, with TLS and authenticated submission
- IMAP and POP3 retrieval, with TLS
- Server-side mail filters via Sieve (ManageSieve)
- Rspamd (built-in DKIM signing + DKIM/DMARC/SPF verify, greylist, Bayes-scored spam)
- ClamAV antivirus (mail parts scanned by rspamd, virus hits rejected at SMTP time)
- Incoming SPF check, DKIM signing and verification, DMARC support
- Reliable delivery guarantee: deliver to INBOX, or reject with an informative error
- Fully isolated local test stack — no mail ever leaves the machine

## Usage

End users access their mail through the webmail or any standard mail client.

**Webmail:** open the SnappyMail address provided by your administrator and log
in with your full email address and password.

**Mail client** — recommended (TLS) settings:

| Protocol | Security | Port |
|----------|----------|------|
| IMAP | SSL/TLS | 993 |
| SMTP (submission) | StartTLS | 587 |
| Sieve | StartTLS | 4190 |

Without TLS the plain ports are IMAP `143`, SMTP `25`, POP3 `110`.

Logging in always requires an encrypted connection: the server offers the
cleartext password mechanisms only over TLS, so a mail client must use
SSL/TLS or STARTTLS to authenticate. Configure your client with one of the
secure settings above.

> **After a server upgrade or migration, set a new password.** Dovecot 2.4 refuses
> legacy weak password hashes (e.g. `MD5-CRYPT` carried over from an older system),
> so existing passwords stop working. Every user has to re-set their password once
> in PostfixAdmin — it is then stored with a current, strong hash and login works.

## Administration

### Build and run

Build the images:

    npm run build

Start in foreground (see logs in real-time):

    npm start

Start in background (daemon mode):

    npm run start:daemon

Wait until the database is initialized and outputs:

> postfixadmin-db_1 | 2021-06-10T19:41:31.466095Z 0 [System] [MY-010931] [Server] /usr/sbin/mysqld: ready for connections. Version: '8.0.25' socket: '/var/run/mysqld/mysqld.sock' port: 3306 MySQL Community Server - GPL.

### First-time setup

Open in browser: http://localhost:8080/setup.php — wait a moment and create an admin.

The configured setup password is `test123` — that's good for testing, not for production. To change it, set variable `SETUP_PASSWORD` in `docker compose.yml` to anything else, e.g.: `SETUP_PASSWORD: ChangeMe` before you open http://localhost:8080/setup.php the first time (or delete the database, see below), then follow the instructions on the page and you get a new hash to set in `SETUP_DATABASE`.

The same applies to the demo `DATABASE_PASSWORD` (`…-change-it`) shared
by PostfixAdmin, Postfix, Dovecot and the database service: change it
everywhere before going to production.

**Trade-off — admin UI without TLS:** the PostfixAdmin proxy speaks
plain HTTP, so the compose file publishes it on loopback only
(`127.0.0.1:8080`) — the setup and admin login passwords must never
travel unencrypted over a network. For remote access put a TLS reverse
proxy (e.g. [mwaeckerlin/reverse-proxy](https://github.com/mwaeckerlin/reverse-proxy))
in front, or tunnel via SSH. Pinned by `tests/compose-contract.sh`.

Access rights for the volumes, if on a local filesystem, must be set to: `100:1000`

### Components

This stack is composed of independently maintained images:

- Postfix — https://github.com/mwaeckerlin/postfix
- Dovecot (IMAP/POP3/Sieve) — https://github.com/mwaeckerlin/dovecot
- PostfixAdmin — https://github.com/mwaeckerlin/postfixadmin
  and its nginx proxy — https://github.com/mwaeckerlin/postfixadmin-proxy
- Rspamd (DKIM + DMARC + SPF + greylist + Bayes) — https://github.com/mwaeckerlin/rspamd
- ClamAV (antivirus) — https://github.com/mwaeckerlin/clamav
- Redis (Bayes / greylist / ratelimit state, headless) — https://github.com/mwaeckerlin/redis
- SnappyMail webmail — see [Frontend: SnappyMail](#frontend-snappymail-web-mailer)
- SMTP relay family (standalone relays this stack's postfix builds on) —
  https://github.com/mwaeckerlin/smtp-relay,
  https://github.com/mwaeckerlin/smtp-relay-tls,
  https://github.com/mwaeckerlin/mailforward

Every own image in the stack is **headless**: a compiled `init` binary
is the entrypoint; there is no shell, no busybox and no perl in any
shipped image (pinned by `tests/image-contract.sh`).

### Upgrading PostfixAdmin

To upgrade PostfixAdmin by upgrading the image, you need to remove the `mailservice/postfixadmin` volume:

```
docker compose rm -vfs
docker volume rm mailservice_postfixadmin
```

Completely delete the database (lose all data), rebuild and use the new distribution:

```
docker compose rm -vfs
docker volume rm mailservice_postfixadmin mailservice_postfixadmin-db
docker compose build
docker compose up
```

#### Database schema upgrade after an image update

When you upgrade the PostfixAdmin image but keep the existing database, the
schema must be migrated to the new version — otherwise pages that use newer
columns/tables (domain list, virtual list, fetchmail) fail with HTTP 500 while
others (login, admin list) still work. The migration is **not** run on normal
page access; trigger it once:

- **Web:** open `/setup.php` (enter the setup password). `setup.php` includes
  `upgrade.php`, which runs `_do_upgrade()` and applies the missing schema steps.
- **CLI (no web):** run the upgrade script directly in the container — it needs
  no setup password (only a valid DB config):

  ```
  docker exec <postfixadmin-container> php /app/public/upgrade.php
  ```

The database user needs `ALTER`/`CREATE` privileges for the upgrade to succeed.

### Mail queue persistence

Postfix answers `250 Ok` as soon as a mail is safely written (fsync)
into its queue — from that moment the server owns delivery and the
sender never retries. A deferred mail (receiver greylisting, dovecot
briefly down, remote MX unreachable) can sit in the queue for hours or
days. The compose file therefore maps `/var/spool/postfix` of every
postfix-based service to a **named volume** (`postfix-spool`,
`mailforward-spool`) — without it, a container recreate or image
update silently destroys accepted-but-undelivered mail.
`tests/compose-contract.sh` pins this: the suite fails if the queue
volume is ever removed.

### Authentication over TLS (secure default)

Passwords are never accepted over an unencrypted connection. This is the
default and needs no configuration:

- **Dovecot (IMAP/POP3/ManageSieve):** the cleartext `PLAIN`/`LOGIN`
  mechanisms are offered **only over TLS**. A client must connect via
  IMAPS/POP3S or issue STARTTLS before authenticating. Controlled by the
  `DOVECOT_ALLOW_CLEARTEXT` env on the `dovecot` service (default `no`).
  Because this requires a TLS certificate to be present, a stack **without
  a certificate** has no usable login until either a cert is provided or the
  setting is deliberately softened.
- **Postfix (SMTP submission):** `smtpd_tls_auth_only=yes` — SASL is offered
  only after STARTTLS, so submission credentials are likewise never sent in
  the clear.

Soften this **only deliberately** by setting `DOVECOT_ALLOW_CLEARTEXT=yes`
(for example a trusted, isolated network that has no certificates). Doing so
lets clients send passwords in cleartext and is not recommended.

### Antispam, antivirus, signing — one rspamd

Starting with v3.0.0 one **rspamd** container replaces the historical
stack of opendkim + opendmarc + postgrey (milter-greylist) +
postfix-policyd-spf-perl. Rspamd does all of it in one process, with
one config, one log stream, one milter connection to postfix:

- **DKIM signing** for every outgoing mail (per-domain 2048-bit RSA
  keys, auto-generated on first start).
- **DKIM verification** on every incoming mail (`Authentication-Results:
  … dkim=pass|fail|none|permerror`).
- **DMARC** — combines DKIM alignment + SPF alignment + the sender's
  `_dmarc` policy, rejects on `p=reject` hard fail when the mode
  allows it.
- **SPF** — inline, without a separate policyd. The verdict lands in
  the same `Authentication-Results:` header.
- **Greylist** — Redis-backed triplet state, **score-based**: only
  mail that already looks suspicious (score above the greylist
  threshold) is delayed with a 4xx; clean first-time senders are
  never delayed (v2's postgrey delayed every unknown triplet). Own
  users (SASL-authenticated submissions) always bypass.
- **Bayes-scored spam** — one global classifier per stack, trained
  event-driven by IMAPSieve when the user moves mail into or out of
  Junk. No cron.
- **Antivirus** — mail parts are handed to **ClamAV** (`clamd` in a
  sibling container); a virus hit contributes a large score that
  pushes the mail above the reject threshold.

Sibling containers on the same `antispam` network:

- `mwaeckerlin/rspamd` — the milter + all the modules above.
- `mwaeckerlin/redis` (headless) — Bayes / greylist / ratelimit state.
- `mwaeckerlin/clamav` — clamd + freshclam supervisor.

Postfix reaches rspamd on the milter port 11332 (single `RSPAMD` env
on the postfix service — `RSPAMD: rspamd`).

Throughout the rest of this section the mailservice itself runs on
`example.email`, and serves the following four domains as an example:

- `example.com`
- `example.net`
- `example.email` (same as the mailservice hostname)
- `example.org`

Postfix accepts mail for the extra domains once they are added in
PostfixAdmin (each becomes a `virtual_mailbox_domain`); no `docker
compose.yml` change is needed for that. SPF, DKIM and DMARC on the
other hand are **per sending domain** — each domain owns its own DNS
records below, and DKIM signs with a **separate key per domain**.

#### SPF (Sender Policy Framework)

SPF lets receiving servers verify that inbound mail claiming to come from your domain was sent by an authorised server.

**Incoming check (server-side)**

Rspamd's SPF module runs against every incoming mail and stamps the
result into `Authentication-Results:`. The verdict feeds into DMARC
alignment. The old perl-based `postfix-policyd-spf-perl` (and its
`CHECK_SPF` knob) is gone from the headless postfix image — it
duplicated rspamd's verdict and could contradict it.

**Outgoing DNS record**

Add a TXT record to your domain's DNS. Minimal example (only your MX servers may send):

```
Name:  example.com
Type:  TXT
Value: v=spf1 mx ~all
```

Replace `~all` (softfail) with `-all` (hardfail) once you are confident that all legitimate senders are listed.

Common modifiers:
- `mx` — allow your MX servers
- `a` — allow the A record of the domain itself
- `ip4:1.2.3.4` — allow a specific IP
- `include:sendgrid.net` — delegate to a third-party SPF record

**Multi-domain**

Every sending domain needs its own SPF record. If all mail leaves through the
mailservice on `example.email`, either list its IP explicitly on every domain,
or — cleaner — publish one SPF record on `example.email` and let the others
`include:` it:

```
Name:  example.email
Type:  TXT
Value: v=spf1 mx ~all

Name:  example.com
Type:  TXT
Value: v=spf1 include:example.email ~all

Name:  example.net
Type:  TXT
Value: v=spf1 include:example.email ~all

Name:  example.org
Type:  TXT
Value: v=spf1 include:example.email ~all
```

With `include:` a single change to `example.email`'s SPF record (a new
outbound relay, an added IP) propagates to every domain automatically.

#### DKIM (DomainKeys Identified Mail)

DKIM adds a cryptographic signature to every outgoing message. Receiving servers use the public key published in DNS to verify the signature and confirm the message was not tampered with.

**How it works in this stack**

The `rspamd` service signs outgoing mail (via `dkim_signing` module)
and verifies incoming signatures (via `dkim` module). Postfix hands
every mail to the rspamd milter on port 11332, on both signing and
verify paths.

**Enable in `docker compose.yml`**

The `rspamd` service is already present. Set `RSPAMD: rspamd` in the
`postfix` environment (already done in the default `docker-compose.yml`):

```yaml
postfix:
  environment:
    RSPAMD: rspamd        # host[:port], default port 11332

rspamd:
  environment:
    DOMAIN:   example.com   # required — your mail domain (single-domain form)
    SELECTOR: mail          # optional, default: mail
  volumes:
    - dkim-keys:/var/lib/rspamd    # per-domain private keys
```

**First start — get your DNS record**

On first start, rspamd's init helper runs `rspamadm dkim_keygen`
per domain (2048-bit RSA) and prints the DNS record:

```
==================================================================
  DKIM key generated — add this DNS TXT record to example.com:
==================================================================
mail._domainkey	IN	TXT	( "v=DKIM1; h=sha256; k=rsa; "
	  "p=MIIBIjAN..." )
==================================================================
```

Publish that TXT record in your DNS:

```
Name:  mail._domainkey.example.com
Type:  TXT
Value: v=DKIM1; h=sha256; k=rsa; p=<public-key>
```

The private key is persisted in the `dkim-keys` volume — back it up and keep it secret.

**Operator notification on key generation (optional)**

If `NOTIFY_EMAIL` is set on the rspamd service, the same records are
also delivered by e-mail — useful when a container restart on a fresh
volume would otherwise print keys only to stdout that no-one reads.
Delivery uses a minimal in-process SMTP client (no external `sendmail`
binary), best-effort, and never blocks start-up:

```yaml
rspamd:
  environment:
    NOTIFY_EMAIL: "hostmaster@example.email"
    NOTIFY_SMTP:  "postfix:25"
```

**Key rotation**

1. Set `SELECTOR` to a new name (e.g. `mail2`) in `docker compose.yml`.
2. Restart the `rspamd` container — a new key is generated for every
   domain, printed to stdout (and mailed if `NOTIFY_EMAIL` is set).
3. Publish the new DNS record alongside the old one.
4. After the old selector's TTL expires, remove it from DNS.
5. Remove the old key files from the `dkim-keys` volume if desired.

**Multi-domain**

For more than one sending domain use `DOMAINS` (space-separated).
Rspamd generates one 2048-bit key **per domain**, prints one DNS TXT
record per domain on first start, and signs any `From:` address whose
domain is in the list with that domain's key:

```yaml
rspamd:
  environment:
    DOMAINS:  "example.com example.net example.email example.org"
    SELECTOR: mail
  volumes:
    - dkim-keys:/var/lib/rspamd
```

Publish one DNS record per domain:

```
Name:  mail._domainkey.example.com
Type:  TXT
Value: v=DKIM1; h=sha256; k=rsa; p=<public-key-for-example.com>

Name:  mail._domainkey.example.net
Type:  TXT
Value: v=DKIM1; h=sha256; k=rsa; p=<public-key-for-example.net>

Name:  mail._domainkey.example.email
Type:  TXT
Value: v=DKIM1; h=sha256; k=rsa; p=<public-key-for-example.email>

Name:  mail._domainkey.example.org
Type:  TXT
Value: v=DKIM1; h=sha256; k=rsa; p=<public-key-for-example.org>
```

Notes:

- The selector name (`mail` by default) is shared across all domains — each
  domain still has its own key because the DNS record lives under
  `mail._domainkey.<domain>` on that domain's own zone.
- Keys are persisted per domain at
  `/var/lib/rspamd/dkim/<selector>.<domain>.key` in the `dkim-keys`
  volume. Adding a new domain later means: extend `DOMAINS`, restart
  the container, publish the printed DNS record. Existing domains'
  keys are reused (not regenerated).
- `DOMAIN` (singular) is kept as the single-domain fallback and is
  used only when `DOMAINS` is unset.

**DKIM/DMARC verification — single knob `DKIM_DMARC`**

Rspamd reads one env var, `DKIM_DMARC`, with four levels:

| `DKIM_DMARC` | Meaning                                                                                                                                    |
|--------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| `off`        | Verification off. Outgoing mail is still signed, incoming mail passes through untouched (no `Authentication-Results` header).              |
| `log`        | Verify every incoming signature, SPF and DMARC policy, stamp the result into an `Authentication-Results` header — **never reject**.        |
| `permissive` | Reject bad or unknown-key DKIM signatures (rspamd action `reject`); accept unsigned mail. Reject on `_dmarc … p=reject` hard fail. Default recommendation for a production MX. |
| `reject`     | On top of `permissive`, also reject mail whose spam score exceeds `RSPAMD_REJECT_SCORE` for other reasons. Right for ingresses where every peer is known to sign.              |

**Image default is `reject`** (strict enforcement). See «Upgrade &
Monitoring» below for the recommended path from log to permissive.

Own users are unaffected: SASL-authenticated submissions bypass the
milter through rspamd's built-in `AUTHENTICATED` symbol, just like for
greylisting.

**Upgrade & Monitoring — how to check before you enforce**

Before you flip a running mailservice to `permissive` or `reject`, run in
`log` mode for a few days and watch what would have been rejected.

1. In your `docker-compose.yml`, set the mode to log:

    ```yaml
    rspamd:
      environment:
        DKIM_DMARC: log
    ```

2. Restart the rspamd service:

    ```
    docker compose up -d rspamd
    ```

3. Watch for verdicts in delivered mail. Every incoming mail is stamped
   with an `Authentication-Results` header — grep those on any mailbox
   or in the dovecot log:

    ```
    docker compose exec dovecot grep -rE '^Authentication-Results:.*(dkim=fail|dkim=none|dkim=permerror|dmarc=fail|spf=fail)' /var/mail/domains/ | head
    ```

    Or, if you have IMAP access, search server-side:

    ```
    imap> UID SEARCH HEADER Authentication-Results "dkim=fail"
    imap> UID SEARCH HEADER Authentication-Results "dmarc=fail"
    ```

4. Rspamd logs every decision to its container stdout — filter by
   action:

    ```
    docker compose logs rspamd | grep -E '\<action=(reject|add header|greylist)\>' | head
    ```

    For a rspamd-side history browser, expose port 11334 and open the
    web UI (`http://<host>:11334/`) — every scan of the last hours
    with score, symbols and headers is browsable there.

5. For every `dkim=fail`, `dkim=permerror` or `dmarc=fail (p=reject)`
   you find, decide: is this a real sender that would get bounced
   under enforcement, or a broken/forged mail that _should_ be
   bounced? If it's a real sender, contact them so they can fix their
   DKIM/DMARC or their forwarding chain (a mailing list that breaks
   DMARC alignment must be re-signing with its own domain or
   rewriting `From:` for `p=reject` senders — modern Mailman does
   this automatically).

6. Once no legitimate mail is affected, escalate. Typical path:
   `log` → `permissive` (rejects broken DKIM and `p=reject` failures
   but still accepts mail from small senders that publish nothing)
   → optionally `reject` (only for an ingress where every peer is a
   known signer).

**Reject-score threshold: `RSPAMD_REJECT_SCORE`**

Score above which rspamd hard-rejects at SMTP time. Default `15` —
rspamd's own conservative default. Lowering it catches more spam but
raises the risk of bouncing legitimate mail with wonky signals; raising
it does the opposite. In doubt, keep the default and let Bayes learn:

```yaml
rspamd:
  environment:
    RSPAMD_REJECT_SCORE: "15"
```

**Disable DKIM signing / verification in postfix**

Remove or leave empty the `RSPAMD` environment variable:

```yaml
postfix:
  environment:
    RSPAMD: ""
```

**Upgrading from v2.x (opendkim + opendmarc + postgrey + policyd-spf)**

v3.0.0 replaces the whole legacy chain (`opendkim`, `opendmarc`,
`postgrey`, `postfix-policyd-spf-perl`) with one `rspamd` container.
On a running v2.x install:

1. Replace the four legacy services with the three v3.0.0 services in
   `docker-compose.yml`:

    ```yaml
    services:
      redis:
        image: mwaeckerlin/redis
        volumes:
          - redis-data:/data
        networks: [antispam]

      clamav:
        image: mwaeckerlin/clamav
        volumes:
          - clamav-db:/var/lib/clamav
        networks: [antispam]

      rspamd:
        image: mwaeckerlin/rspamd
        environment:
          DOMAINS:     "example.com example.org"   # every domain you sign for
          AUTHSERV_ID: mail.example.com
          DKIM_DMARC:  log                          # start in monitor mode
          REDIS_HOST:  redis
          CLAMAV_HOST: clamav
        volumes:
          - dkim-keys:/var/lib/rspamd      # keep the v2.x dkim-keys volume
        networks: [antispam]

      postfix:
        # your existing service — swap OPENDKIM/OPENDMARC/GREYLIST for RSPAMD:
        environment:
          RSPAMD: rspamd
        networks:
          - postfix-backend
          - antispam
    ```

2. The DKIM key volume you used with `mwaeckerlin/opendkim`
   (typically mounted at `/etc/opendkim/keys/`) contains files at
   `<domain>/mail.private`. Rspamd expects
   `/var/lib/rspamd/dkim/mail.<domain>.key`. Move each key file into
   the new location once — a one-shot init container is enough:

    ```bash
    docker run --rm -v mailservice_dkim-keys:/keys alpine sh -c '
      cd /keys
      for d in */; do
        dom=${d%/}
        test -f "$dom/mail.private" && mv "$dom/mail.private" "dkim/mail.$dom.key"
      done
      rmdir */ 2>/dev/null
    '
    ```

    (Skip this step if you accept regenerating the keys — you would
    also have to publish the new public key in DNS.)

3. `docker compose up -d rspamd redis clamav postfix`. Verify with
   `docker compose logs rspamd` and by grepping delivered mail's
   `Authentication-Results:` header for a few days in `log` mode,
   then escalate.

Nothing on the DNS side has to change — the DKIM public key, SPF
record, DMARC record and selector name all stay the same.

#### DMARC (Domain-based Message Authentication, Reporting and Conformance)

DMARC ties SPF and DKIM together and tells receiving servers what to
do when both checks fail. **On the sending side** it is DNS-only.
**On the receiving side** the rspamd DMARC module (same container,
same milter connection) evaluates the sender's `_dmarc` record,
combines DKIM alignment + SPF alignment, and — under `DKIM_DMARC`
`permissive` or `reject` — rejects a mail whose `From:` domain
publishes `p=reject` and passes neither DKIM nor SPF alignment
(`550 5.7.1`). Under `log` it stamps the verdict into
`Authentication-Results:` but never rejects. Under `off` it does
nothing.

Own users (SASL-authenticated submissions and internal container
networks) bypass the DMARC check via the built-in `AUTHENTICATED`
and `LOCAL` bypass symbols.

**Minimal DNS record**

```
Name:  _dmarc.example.com
Type:  TXT
Value: v=DMARC1; p=none; rua=mailto:dmarc-reports@example.com
```

Policy values:
- `p=none` — monitor only, no action taken (good starting point)
- `p=quarantine` — failing mail goes to spam
- `p=reject` — failing mail is rejected outright

**With reporting**

- `rua=mailto:…` — aggregate reports (daily summaries)
- `ruf=mailto:…` — forensic reports (individual failures)

**Multi-domain**

DMARC is DNS-only, so each sending domain publishes its own `_dmarc.<domain>`
record. The `rua`/`ruf` mailbox may live on any domain — pointing every
domain's reports to a single inbox on `example.email` centralises
monitoring:

```
Name:  _dmarc.example.com
Type:  TXT
Value: v=DMARC1; p=none; rua=mailto:dmarc-reports@example.email

Name:  _dmarc.example.net
Type:  TXT
Value: v=DMARC1; p=none; rua=mailto:dmarc-reports@example.email

Name:  _dmarc.example.email
Type:  TXT
Value: v=DMARC1; p=none; rua=mailto:dmarc-reports@example.email

Name:  _dmarc.example.org
Type:  TXT
Value: v=DMARC1; p=none; rua=mailto:dmarc-reports@example.email
```

If a report inbox on a **different** domain from the DMARC record is used,
that inbox's domain must also authorise it via an
`example.email._report._dmarc.<sender-domain>` TXT record — see RFC 7489.
Same-domain (`dmarc-reports@example.com` on `_dmarc.example.com`) needs no
extra record.

**Recommended roll-out sequence**

1. Start with `p=none; rua=mailto:your-address` and collect reports for a few weeks.
2. Once you are confident SPF and DKIM are working correctly, move to `p=quarantine`.
3. Finally switch to `p=reject` for maximum protection.

#### Antivirus (ClamAV)

The `clamav` sibling runs `clamd` in the foreground with `freshclam
--daemon` maintaining the signature database at
`/var/lib/clamav/`. Rspamd's `antivirus` module scans every mail
part; a signature hit contributes a large score (default 1000) that
pushes the mail above `RSPAMD_REJECT_SCORE`, and rspamd rejects
with SMTP 5xx at DATA time.

Freshclam takes minutes on the very first start of a fresh `clamav-db`
volume — the container is healthy from the start (clamd loads), but
until freshclam finishes downloading the initial bundle from
`database.clamav.net`, the antivirus scanner does not actually flag
anything. Once the DB is present it re-downloads incrementally.

Verify end-to-end with the EICAR test string
(`X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*` —
industry-standard, safe): submitting it to postfix must produce a
5xx reject.

Persistence: `/var/lib/clamav` (non-critical; freshclam re-populates
if lost, at the cost of the initial download).

#### Bayes-scored spam and autotraining

Rspamd's Bayes classifier lives in Redis (per `rspamd/classifier-
bayes.conf`) and is trained event-driven: dovecot's `imap_sieve`
plugin fires on every IMAP MOVE / COPY into or out of the `Junk`
folder, pipes the message through
`/usr/local/bin/report-{spam,ham}` → `rspamc learn_{spam,ham}`
against the sibling rspamd controller. No cron, no periodic scan.

`RSPAMD_BAYES_PER_USER` toggles between one global classifier
(default; reaches rspamd's ~200-messages-per-class training threshold
within days on a small deployment) and per-user classifiers
(right for large multi-tenant setups; takes months per user to
reach the threshold). Global is the default because the mailservice
target is small-to-medium.

Persistence: the `redis-data` volume — losing it wipes the Bayes
training AND the greylist / ratelimit state. Both regenerate over
time but the classifier is silent until re-trained.

#### `SPAM_DELIVERY_MODE` (dovecot)

Controls what dovecot does with mail that rspamd tagged as spam
(`X-Spam-Flag: YES`) but did not reject at SMTP time (score below
`RSPAMD_REJECT_SCORE`). Set on the dovecot service:

| `SPAM_DELIVERY_MODE` | Behaviour                                                                                                                                                                                                  |
|----------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `reject`             | Default. Aligned with the mailservice design («Design philosophy: reliability over filtering» below): exactly two outcomes, delivered or SMTP-rejected. Nothing above the reject score ever reaches here.  |
| `mark`               | Deliver to INBOX with `X-Spam-Flag: YES`, `X-Spam-Status: …`, `X-Spam-Level: ****`. **Never** rewrites the subject and never touches the body — a subject rewrite would invalidate the sender's DKIM signature (and any intermediate hop's ARC seal). The user's MUA can filter on those headers client-side. |
| `folder`             | Deliver to the recipient's IMAP `Junk` folder via a server-side sieve rule (`X-Spam-Flag: YES` → `fileinto :create "Junk"`). Silent quarantine — explicitly **not** recommended, but supported for admins who ask for it. |

The reject-score threshold is the same in all three modes: mail above
`RSPAMD_REJECT_SCORE` is always rejected at SMTP time. `SPAM_DELIVERY_MODE`
only decides what happens to borderline mail (between add-header score
and reject score) that was already accepted.

**Legal framing — SMTP-reject vs. Aufbewahrungspflicht**

An SMTP-time rejection (`5xx` at `DATA`) means the mail *never
became mail on our side*: it was refused before it left the sender's
queue. Nothing was accepted, nothing was received, nothing was
stored. That is materially different from the accept-then-file-into-
Junk pattern that the big providers use.

Legal record-keeping duties (e.g. commercial correspondence
retention under Swiss / EU tax and commercial law, or e-discovery
holds) attach to received mail — mail your server accepted. A
rejected mail is not received mail; the sender's MTA has the
bounce, and the sender can retry, sign, fix their SPF/DMARC, or
resend by another route. The mailservice's `reject`-mode default
therefore *reduces* the retention perimeter compared to a
`folder`-mode setup that quietly accepts everything and files it
into Junk.

Operators who need a quarantine trail for auditing reasons should
choose `folder` mode explicitly, understand the retention
consequences, and set up the Junk folder as an audit target
(retention policy, no user delete). The default deliberately does
not do this.

### Frontend: SnappyMail Web-Mailer

[SnappyMail](https://snappymail.eu/) is the actively maintained successor to RainLoop. It includes the same PHP FPM + nginx container setup and is a drop-in replacement. See `rainloop/README.md` for migration instructions.

If you use TLS, configuration parameters are:
 - IMAP: `SSL/TLS` (port: `993`)
 - SMTP: `StartTLS` (port: `587`)
 - SIEVE: `StartTLS` (port: `4190`)

### Database version

Dovecot 2.4's MySQL client requires TLS for the database connection, so
**MariaDB 11 or newer is required** — it provides TLS out of the box, so the
`dovecot` → database connection works. With an older MariaDB that offers no TLS
(e.g. 10.x) Dovecot fails with *"SSL is required, but the server does not
support it"*; in that case set `ssl = no` in Dovecot's MySQL passdb block
(`dovecot/init.cpp` writes it to `conf.d/passdb-sql.conf`, inside
`mysql { … }`).

## Development

### Image dependency chain

The images are layered — each inherits the accumulated postfix
configuration (`main.cf`) of its parent:

```
mwaeckerlin/very-base (build stages)
  └── mwaeckerlin/smtp-relay        simple open relay (for other apps: Nextcloud, Gitea…)
        ├── mwaeckerlin/smtp-relay-tls    same, with TLS support
        └── mwaeckerlin/mailforward       mail forwarder (no own mailbox)
              └── mwaeckerlin/postfix     full mail server ← core of this stack
```

All images are **headless**: the build stage (from `very-base`, which
still has the package manager) installs postfix, copies the parent
image's `main.cf` and layers its own settings on top; the shipped
scratch image contains only the daemon, its libraries, the config and
a compiled `init` entrypoint — no shell, no busybox, no perl. The
`tests/image-contract.sh` suite pins this for every image in the
stack.

`smtp-relay` and `smtp-relay-tls` are also published as standalone images for use by other Docker services that need an SMTP server without the full mailservice stack.

### Tests

```bash
npm test            # full end-to-end suite (Postfix, Dovecot, greylisting,
                    # SPF/DKIM, PostfixAdmin and SnappyMail web UIs)
```

The suite runs in a fully isolated stack (domain `test.local`, its own DNS) so
no mail ever leaves the machine.

### Manual testing in the isolated test stack

This drives the same stack that `npm test` uses (domain `test.local`), but with
the web UIs and mail ports published to `localhost` so you can drive it from a
browser.

The bundled `dns` service runs with `no-resolv`, so no external domain can be
resolved: mail addressed outside `test.local` is rejected, never sent out.

#### Start / stop

```bash
npm run test:manual        # build + start, prints the access URLs, stays running
npm run test:manual:stop   # stop (data is preserved; add -v manually to wipe)
```

Host ports are fixed but deliberately uncommon (`478xx` range) so collisions
with other projects are unlikely. If one is taken on your machine, change it in
`tests/e2e/docker-compose.manual.yml`.

#### Services and ports

| Service | Address | Access |
|---------|---------|--------|
| PostfixAdmin | http://localhost:47808/setup.php | setup password: `test123` |
| SnappyMail admin | http://localhost:47880/?admin | `admin` / `12345` |
| SnappyMail webmail | http://localhost:47880/ | the accounts you create in PostfixAdmin |
| SMTP | localhost:47825 | `swaks --server localhost:47825` |
| IMAP | localhost:47843 | — |
| POP3 | localhost:47810 | — |

#### Walk-through: send a mail without touching the internet

1. **Create the admin and the mailboxes in PostfixAdmin.**
   - Open http://localhost:47808/setup.php, enter the setup password `test123`,
     and create an admin account.
   - Log in, add the domain `test.local`, then add two mailboxes, e.g.
     `alice@test.local` and `bob@test.local`. Passwords must satisfy the policy:
     at least 5 characters, 3 letters and 2 digits (e.g. `alicepass12`).
2. **Point the webmail at the mail servers.** Open the SnappyMail admin at
   http://localhost:47880/?admin (`admin` / `12345`) → *Domains* → *Add Domain*
   `test.local`:
   - IMAP host `dovecot`, port `143`
   - SMTP host `postfix`, port `25`

   (These are the **internal** container ports — unrelated to the host ports
   above. It persists in the volume, so it is only needed once.)
3. **Send.** Open http://localhost:47880/, log in as `alice@test.local`, compose
   a mail to `bob@test.local`, send.
4. **Receive.** Log in as `bob@test.local` and read it in the INBOX.

You can also inject mail from the host with `swaks`:

```bash
swaks --to bob@test.local --from alice@test.local --server localhost:47825
```

Trying to send to an external address (e.g. `@gmail.com`) is refused with an
SMTP error — the isolated DNS cannot resolve it, so it can never go out.

#### Inspect trapped outbound mail

```bash
docker compose -f tests/e2e/docker-compose.yml -f tests/e2e/docker-compose.manual.yml \
  exec fake-smtp ls /mails
```

### Local development overlay

`docker compose.local.yml` is an overlay for local development — no root required, outbound mail is intercepted, a webmailer is included. Unlike the test stack above it uses the domain `localhost` and lets you create your own accounts.

#### Start

```bash
npm run start:local          # foreground (live logs)
npm run start:local:daemon   # background
```

#### Services and ports

| Service | Address | Description |
|---------|---------|-------------|
| PostfixAdmin | http://localhost:8080 | Manage mail accounts and domains |
| SnappyMail | http://localhost:8081 | Webmailer |
| SMTP | localhost:2525 | Submit mail (`swaks --port 2525`) |
| SMTP submission | localhost:5870 | Authenticated submission |
| IMAP | localhost:1143 | Retrieve mail |
| POP3 | localhost:1110 | Retrieve mail |
| IMAPS | localhost:1993 | IMAP over TLS |
| POP3S | localhost:1995 | POP3 over TLS |
| ManageSieve | localhost:4190 | Manage Sieve filter scripts |
| fake-smtp direct | localhost:2526 | Send directly to the mail trap |

All outbound mail is captured by [fake-smtp](../fake-smtp) — nothing leaves your machine.

#### One-time setup

**1. PostfixAdmin**

Open http://localhost:8080/setup.php — setup password is `test123`.
Create an admin account, then add domain `localhost` and at least one mailbox (e.g. `alice@localhost`).

**2. SnappyMail admin**

Open http://localhost:8081/?admin — default password `12345`.

Add a domain configuration:
- IMAP server: `dovecot`, port `143`
- SMTP server: `postfix`, port `25`

#### Send and receive test mails

Send from the host:

```bash
swaks --to alice@localhost --server localhost --port 2525
```

Log in to SnappyMail at http://localhost:8081 with the credentials you created in PostfixAdmin.

Inspect outbound mail caught by fake-smtp:

```bash
# list captured mails
docker compose -f docker compose.yml -f docker compose.local.yml exec fake-smtp ls /mails

# read a captured mail
docker compose -f docker compose.yml -f docker compose.local.yml exec fake-smtp cat /mails/<filename>
```

## Design philosophy: reliability over filtering

### Outbound: submission is final — the server owns delivery

A mail client (webmail, IMAP client) has exactly one job when sending: hand the
message to Postfix. From that moment **Postfix owns delivery** — it queues the
message and retries temporary failures (e.g. greylisting at the recipient's
server) automatically until the mail is delivered or a permanent error occurs.

- Once a message is accepted at submission, the sender may assume it will
  successfully leave this server. No manual re-sending, ever.
- Only **real** (permanent) errors are reported — as a bounce message to the
  sender. Temporary errors are retried, never surfaced to the user.
- Consequently, **greylisting never applies to our own users**: SASL-
  authenticated clients and the internal container networks are exempt in
  rspamd's greylist layer (the equivalent of `permit_sasl_authenticated,
  permit_mynetworks` preceding the former policy check). A greylisting `451`
  at submission would push the retry burden onto the human in front of the
  webmail — the opposite of this guarantee.

### Reject reasons — end-user first, then the admin

Every reject must return a reason the sender can act on:

- **First address the end user** in plain, non-technical wording — «Your
  mail could not be delivered because …». Never a bare `5.7.0` or
  «policy violation».
- **Then add the technical hint the admin needs** to find the misconfig
  — DKIM selector, DMARC policy, SPF result, greylist retry window,
  whatever is relevant.

Example (DMARC quarantine rejected because this server does not accept
quarantine):

> `550 5.7.1 DMARC is configured with p=quarantine, but the check failed.
> Your mail was marked as quarantine; this server does not accept
> quarantined mail (no Junk folder) and rejects it as potential spam.
> (Admin: check `_dmarc.<sender-domain>` policy, DKIM signature and SPF
> alignment against `<From:>`.)`

The current rspamd reject messages are not yet uniformly at this level
of detail — this is a follow-up feature that will refine the
milter-side reject templates.

### Inbound: delivered or rejected — nothing in between

Every message has exactly **two possible outcomes**:

1. **Delivered** — the message arrives in the recipient's **INBOX**.
2. **Rejected** — the sender receives a **correct, informative SMTP error** (RFC 5321 compliant) explaining why the message was refused.

There is no third outcome. Messages do **not** disappear into a spam folder, are **not** silently dropped, and are **not** quarantined without notification. Either the recipient has the mail, or the sender knows it was refused and why.

This guarantee holds as long as the sender's infrastructure also follows the RFCs (i.e. correctly handles 4xx/5xx responses and does not forge envelope addresses).

### How each component upholds this

| Component | Behaviour on rejection |
|-----------|----------------------|
| Postfix restrictions (invalid HELO, unknown domain, relay attempt, RBL hit) | `5xx` permanent rejection — sender informed immediately |
| Greylisting (rspamd, score-based) | `4xx` temporary deferral — RFC-compliant, sender retries automatically |
| SPF hard fail (`-all`) | `550` permanent rejection — sender informed |
| SPF soft-fail (`~all`), neutral, none | `DUNNO` — mail passes through to INBOX |
| SPF / DNS temporary error | `4xx` deferral — sender retries |
| DKIM verification failure | Header added, mail delivered — DKIM failure alone does not reject |

There is deliberately **no spam folder** and **no content-based filtering** that could cause silent misdirection.

### Virus scanning

Virus scanning is integrated (ClamAV via rspamd's antivirus module) and
follows the same principle: infected mail is rejected at SMTP time with
an informative error rather than silently quarantined. Oversized mail
beyond the scanner's limits is delivered unscanned, never bounced (see
the rspamd README «fail-open» notes).
