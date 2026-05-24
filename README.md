# MailService

Collection of Docker images for a full mail service: Postfix (SMTP/TLS) + Dovecot (IMAP/POP3/Sieve) + Greylisting + SPF/DKIM/DMARC; built from several submodules.

Build the images:

    npm run build

Start in foreground (see logs in real-time):

    npm start

Start in background (daemon mode):

    npm run start:daemon

Wait until the database is initialized and outputs:

> postfixadmin-db_1 | 2021-06-10T19:41:31.466095Z 0 [System] [MY-010931] [Server] /usr/sbin/mysqld: ready for connections. Version: '8.0.25' socket: '/var/run/mysqld/mysqld.sock' port: 3306 MySQL Community Server - GPL.

Open in Browser: http://localhost:8080/public/setup.php

Wait for a long time and create an admin.

The configured setup password is `test123` — that's good for testing, not for production. To change it, set variable `SETUP_PASSWORD` in `docker compose.yml` to anything else, e.g.: `SETUP_PASSWORD: ChangeMe` before you open http://localhost:8080/public/setup.php the first time (or delete the database, see below), then follow the instructions on the page and you get a new hash to set in `SETUP_DATABASE`.

If you use TLS, Configuration parameters are:
 - IMAP: `SSL/TLS` (port: `993`)
 - SMTP: `StartTLS` (port: `587`)
 - SIEVE: `StartTLS` (port: `4190`)

Access rights for the volumes, if on a local filesystem, must be set to: `100:1000`

## Design Philosophy: Reliability over Filtering

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

---

## PostfixAdmin

Includes: https://github.com/mwaeckerlin/postfixadmin
Includes: https://github.com/mwaeckerlin/postfixadmin-proxy

To upgrade the Postfixadmin by upgrading the image, you need to remove the `mailservice/postfixadmin` volume:

```
docker compose rm -vfs
docker volume rm mailservice_postfixadmin
```

Completly delete the database (loose al data), rebuild and use the new distribuition:

```
docker compose rm -vfs
docker volume rm mailservice_postfixadmin mailservice_postfixadmin-db
docker compose build
docker compose up
```

## DoveCot IMAP

Includes: https://github.com/mwaeckerlin/dovecot

## Postfix

Includes: https://github.com/mwaeckerlin/postfix

## Greylisting

Includes: https://github.com/mwaeckerlin/postgrey (now uses milter-greylist)

## SPF, DKIM and DMARC

### SPF (Sender Policy Framework)

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

---

### DKIM (DomainKeys Identified Mail)

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

---

### DMARC (Domain-based Message Authentication, Reporting and Conformance)

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

---

## Virus Scan (to do)

## Frontend: SnappyMail Web-Mailer

[SnappyMail](https://snappymail.eu/) is the actively maintained successor to RainLoop. It includes the same PHP FPM + nginx container setup and is a drop-in replacement. See `rainloop/README.md` for migration instructions.

If you use TLS, configuration parameters are:
 - IMAP: `SSL/TLS` (port: `993`)
 - SMTP: `StartTLS` (port: `587`)
 - SIEVE: `StartTLS` (port: `4190`)

## Local Development

`docker compose.local.yml` is an overlay for local testing — no root required, outbound mail is intercepted, a webmailer is included.

### Start

```bash
npm run start:local          # foreground (live logs)
npm run start:local:daemon   # background
```

### Services and ports

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

### One-time setup

**1. PostfixAdmin**

Open http://localhost:8080/public/setup.php — setup password is `test123`.
Create an admin account, then add domain `localhost` and at least one mailbox (e.g. `alice@localhost`).

**2. SnappyMail admin**

Open http://localhost:8081/?admin — default password `12345`.

Add a domain configuration:
- IMAP server: `dovecot`, port `143`
- SMTP server: `postfix`, port `25`

### Send and receive test mails

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