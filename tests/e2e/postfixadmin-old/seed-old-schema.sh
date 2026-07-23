#!/bin/sh
# Run the REAL PostfixAdmin 3.2.4 upgrade chain against the fresh
# schema-upgrade database — on an empty database this creates the
# genuine, complete 3.2-era schema (that is exactly how the old release
# provisioned itself).
#
# `die()` in PHP exits with status 0, so a failed upgrade would look
# successful — verify the outcome instead: the config table must carry a
# schema version marker afterwards.
set -eu
cd /opt/postfixadmin

# the mariadb entrypoint restarts the server once after seeding users —
# a `healthy` gate can fire inside that window, so wait for a real,
# stable connection instead of relying on the healthcheck alone
i=0
until php -r '
    exit(@mysqli_connect("postfixadmin-db-upgrade", "postfixadmin",
                         "testpass", "postfixadmin") ? 0 : 1);
'; do
    i=$((i + 1))
    if [ "$i" -ge 60 ]; then
        echo "upgrade db not reachable after 60 tries" >&2
        exit 1
    fi
    sleep 2
done

if [ -f public/upgrade.php ]; then
    php public/upgrade.php
else
    php upgrade.php
fi
php -r '
    $c = mysqli_connect("postfixadmin-db-upgrade", "postfixadmin", "testpass", "postfixadmin");
    if (!$c) { fwrite(STDERR, "cannot connect to upgrade db\n"); exit(1); }
    $r = mysqli_query($c, "SELECT value FROM config WHERE name = \"version\"");
    $row = $r ? mysqli_fetch_row($r) : null;
    $v = $row ? (int)$row[0] : 0;
    echo "seeded 3.2.4 schema, version marker: $v\n";
    exit($v > 0 ? 0 : 1);
'
