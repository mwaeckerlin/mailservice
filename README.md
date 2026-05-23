# MailService

Collection of Docker images for full Mailservice: SMTP/TLS + IMAPS + Greylisting (milter-greylist) + SPAM filter; built using several subprojects.

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

The configured setup password is `test123` — that's good for testing, not for production. To change it, set variable `SETUP_PASSWORD` in `docker-compose.yml` to anything else, e.g.: `SETUP_PASSWORD: ChangeMe` before you open http://localhost:8080/public/setup.php the first time (or delete the database, see below), then follow the instructions on the page and you get a new hash to set in `SETUP_DATABASE`.

If you use TLS, Configuration parameters are:
 - IMAP: `SSL/TLS` (port: `993`)
 - SMTP: `StartTLS` (port: `578`)
 - SIEVE: `StartTLS` (port: `4190`)

Access rights for the volumes, if on a local filesystem, must be set to: `100:1000`

## PostfixAdmin

Includes: https://github.com/mwaeckerlin/postfixadmin
Includes: https://github.com/mwaeckerlin/postfixadmin-proxy

To upgrade the Postfixadmin by upgrading the image, you need to remove the `mailservice/postfixadmin` volume:

```
docker-compose rm -vfs
docker volume rm mailservice_postfixadmin
```

Completly delete the database (loose al data), rebuild and use the new distribuition:

```
docker-compose rm -vfs
docker volume rm mailservice_postfixadmin mailservice_postfixadmin-db
docker-compose build
docker-compose up
```

## DoveCot IMAP

Includes: https://github.com/mwaeckerlin/dovecot

## Postfix

Includes: https://github.com/mwaeckerlin/postfix

## Greylisting

Includes: https://github.com/mwaeckerlin/postgrey (now uses milter-greylist)

## Virus Scan (to do)

## Frontend: SnappyMail Web-Mailer

[SnappyMail](https://snappymail.eu/) is the actively maintained successor to RainLoop. It includes the same PHP FPM + nginx container setup and is a drop-in replacement. See `rainloop/README.md` for migration instructions.

If you use TLS, configuration parameters are:
 - IMAP: `SSL/TLS` (port: `993`)
 - SMTP: `StartTLS` (port: `578`)
 - SIEVE: `StartTLS` (port: `4190`)

## Local Development

`docker-compose.local.yml` is an overlay for local testing — no root required, outbound mail is intercepted, a webmailer is included.

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
docker compose -f docker-compose.yml -f docker-compose.local.yml exec fake-smtp ls /mails

# read a captured mail
docker compose -f docker-compose.yml -f docker-compose.local.yml exec fake-smtp cat /mails/<filename>
```