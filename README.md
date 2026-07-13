# MailService

Run your own complete email service for your domain within a Docker stack:
a full mail server with **webmail**, an **admin web UI**, and modern
deliverability and anti-abuse (SPF, DKIM, DMARC, greylisting) — everything
needed to send, receive and read mail under your own domain, without handing
your correspondence to a third-party mail provider.

## Why MailService

- **A complete suite, not just an MTA.** Postfix (SMTP/TLS), Dovecot
  (IMAP/POP3/Sieve), the **SnappyMail** webmail, the **PostfixAdmin** admin UI,
  OpenDKIM, SPF and greylisting — wired together and ready to run.
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
- Greylisting (milter-greylist) to cut spam
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

Access rights for the volumes, if on a local filesystem, must be set to: `100:1000`

### Components

This stack is composed of independently maintained images:

- Postfix — https://github.com/mwaeckerlin/postfix
- Dovecot (IMAP/POP3/Sieve) — https://github.com/mwaeckerlin/dovecot
- PostfixAdmin — https://github.com/mwaeckerlin/postfixadmin
  and its nginx proxy — https://github.com/mwaeckerlin/postfixadmin-proxy
- Greylisting — https://github.com/mwaeckerlin/postgrey (now uses milter-greylist)
- SnappyMail webmail — see [Frontend: SnappyMail](#frontend-snappymail-web-mailer)

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

### SPF, DKIM and DMARC

#### SPF (Sender Policy Framework)

SPF lets receiving servers verify that inbound mail claiming to come from your domain was sent by an authorised server.

**Incoming check (server-side)**

The postfix container runs `postfix-policyd-spf-perl` automatically. It checks SPF on every incoming message and rejects mail that fails a hard SPF fail (`-all`). To disable it:

```yaml
postfix:
  environment:
    CHECK_SPF: "no"
```

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

#### DKIM (DomainKeys Identified Mail)

DKIM adds a cryptographic signature to every outgoing message. Receiving servers use the public key published in DNS to verify the signature and confirm the message was not tampered with.

**How it works in this stack**

The `opendkim` service signs outgoing mail and verifies signatures on incoming mail (mode `sv`). Postfix sends mail through the OpenDKIM milter on port 10026.

**Enable in `docker compose.yml`**

The `opendkim` service is already present. Set `OPENDKIM: opendkim` in the `postfix` environment (already done in the default `docker compose.yml`):

```yaml
postfix:
  environment:
    OPENDKIM: opendkim    # host[:port], default port 10026

opendkim:
  environment:
    DOMAIN:   example.com   # required — your mail domain
    SELECTOR: mail           # optional, default: mail
  volumes:
    - dkim-keys:/etc/opendkim/keys
```

**First start — get your DNS record**

On first start, OpenDKIM auto-generates a 2048-bit RSA key and prints the DNS record:

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

**Key rotation**

1. Set `SELECTOR` to a new name (e.g. `mail2`) in `docker compose.yml`.
2. Restart the `opendkim` container — a new key is generated and printed.
3. Publish the new DNS record alongside the old one.
4. After the old selector's TTL expires, remove it from DNS.
5. Remove the old key from the volume if desired.

**Disable DKIM signing in postfix**

Remove or leave empty the `OPENDKIM` environment variable:

```yaml
postfix:
  environment:
    OPENDKIM: ""
```

#### DMARC (Domain-based Message Authentication, Reporting and Conformance)

DMARC ties SPF and DKIM together and tells receiving servers what to do when both checks fail. It is DNS-only — no server-side configuration is required in this stack.

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

**Recommended roll-out sequence**

1. Start with `p=none; rua=mailto:your-address` and collect reports for a few weeks.
2. Once you are confident SPF and DKIM are working correctly, move to `p=quarantine`.
3. Finally switch to `p=reject` for maximum protection.

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
(`dovecot/start.sh`, inside `mysql { … }`).

## Development

### Image dependency chain

The images are layered — each builds on the previous:

```
mwaeckerlin/very-base
  └── mwaeckerlin/smtp-relay        simple open relay (for other apps: Nextcloud, Gitea…)
        ├── mwaeckerlin/smtp-relay-tls    same, with TLS support
        └── mwaeckerlin/mailforward       mail forwarder (no own mailbox)
              └── mwaeckerlin/postfix     full mail server ← core of this stack
```

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
  authenticated clients and the internal container networks are whitelisted in
  milter-greylist (the equivalent of `permit_sasl_authenticated,
  permit_mynetworks` preceding the former policy check). A greylisting `451`
  at submission would push the retry burden onto the human in front of the
  webmail — the opposite of this guarantee.

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
| Greylisting (milter-greylist) | `4xx` temporary deferral — RFC-compliant, sender retries automatically |
| SPF hard fail (`-all`) | `550` permanent rejection — sender informed |
| SPF soft-fail (`~all`), neutral, none | `DUNNO` — mail passes through to INBOX |
| SPF / DNS temporary error | `4xx` deferral — sender retries |
| DKIM verification failure | Header added, mail delivered — DKIM failure alone does not reject |

There is deliberately **no spam folder** and **no content-based filtering** that could cause silent misdirection.

### Roadmap

- Virus scanning is planned. It will follow the same principle: reject infected
  mail with an informative SMTP error rather than silently quarantining it.
