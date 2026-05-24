#!/bin/sh -e

if [ -z "${DOMAIN}" ]; then
    echo "#### ERROR: DOMAIN environment variable must be set" >&2
    exit 1
fi

SELECTOR="${SELECTOR:-mail}"
KEYDIR="/etc/opendkim/keys/${DOMAIN}"

if [ ! -f "${KEYDIR}/${SELECTOR}.private" ]; then
    echo "**** Generating DKIM key: selector=${SELECTOR} domain=${DOMAIN}"
    mkdir -p "${KEYDIR}"
    opendkim-genkey -b 2048 -D "${KEYDIR}" -d "${DOMAIN}" -s "${SELECTOR}"

    echo ""
    echo "=================================================================="
    echo "  DKIM key generated — add this DNS TXT record to ${DOMAIN}:"
    echo "=================================================================="
    cat "${KEYDIR}/${SELECTOR}.txt"
    echo "=================================================================="
    echo ""
fi

cat > /etc/opendkim/KeyTable << EOF
${SELECTOR}._domainkey.${DOMAIN} ${DOMAIN}:${SELECTOR}:${KEYDIR}/${SELECTOR}.private
EOF

cat > /etc/opendkim/SigningTable << EOF
*@${DOMAIN} ${SELECTOR}._domainkey.${DOMAIN}
EOF

cat > /etc/opendkim/TrustedHosts << EOF
127.0.0.1
::1
localhost
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
EOF

echo "**** Starting OpenDKIM (sign+verify) on port 10026 for ${DOMAIN}"
exec /usr/sbin/opendkim -f -x /etc/opendkim.conf
