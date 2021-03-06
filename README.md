# MailService

Collection of Docker images for full Mailservice: SMTP/TLS + IMAPS + PostGrey + SPAM filter; built using several subprojects.

Build the images:

    docker-compose build

Start:

    docker-compose up

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

## PostGrey

Includes: https://github.com/mwaeckerlin/postgrey

## Virus Scan (to do)

## Frontend: Rainloop Web-Mailer

Modern Web-Mailer to be used as frontend. It is completly independent from the mail server, but it fits well together. Just go to the subdirectory `rainloop` and follow the instructions in the `README.md`, then configure your mailserver.

If you use TLS, Configuration parameters are:
 - IMAP: `SSL/TLS` (port: `993`)
 - SMTP: `StartTLS` (port: `578`)
 - SIEVE: `StartTLS` (port: `4190`)

Includes: https://github.com/mwaeckerlin/rainloop