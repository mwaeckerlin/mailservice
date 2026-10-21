#!/bin/sh
# Seed the webmail's own configuration, the way the production
# deployment does it: the configs directory is a mounted volume there,
# written once and then owned by the operator.
#
# The domain file is what lets a mailbox of test.local log in at all —
# without it the webmail has no idea which IMAP server the address
# belongs to. Writing it here keeps the suite independent of the admin
# interface, whose markup differs between webmail releases.
set -eu

DATA="${SNAPPYMAIL_DATA:-/data}/_data_/_default_"
mkdir -p "$DATA/configs" "$DATA/domains"

cat > "$DATA/configs/application.ini" <<INI
[security]
admin_password = "\$2y\$12\$wbso8NPeetgyrrwa5yKLBup0N011YwzKfyOYb0TCtsv/jX2q58nJi"
admin_login = "admin"

[ssl]
; the stack's certificate is self-signed on purpose — the subject of
; these tests is the mail path, not a chain of trust
verify_certificate = Off
allow_self_signed = On
INI

cat > "$DATA/domains/${MAIL_DOMAIN}.ini" <<INI
imap_host = "${DOVECOT_HOST}"
imap_port = ${IMAP_PORT}
imap_secure = "TLS"
imap_short_login = Off
smtp_host = "${POSTFIX_HOST}"
smtp_port = ${SMTP_PORT}
smtp_secure = "TLS"
smtp_short_login = Off
smtp_auth = On
smtp_php_mail = Off
white_list = ""
INI

# The webmail runs unprivileged and writes its cache, its logs and its
# per-user storage below this directory. Everything created here belongs
# to root, so without this the application answers every request with an
# empty page and logs «Failed to create directory … /cache/».
$ALLOW_USER "${SNAPPYMAIL_DATA:-/data}"

echo "**** webmail configured for ${MAIL_DOMAIN}: imap ${DOVECOT_HOST}:${IMAP_PORT}, smtp ${POSTFIX_HOST}:${SMTP_PORT}"
