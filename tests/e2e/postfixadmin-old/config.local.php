<?php
// Test-only configuration for the PostfixAdmin 3.2.4 schema seeder —
// credentials match the e2e compose service `postfixadmin-db-upgrade`.
$CONF['configured'] = true;
$CONF['database_type'] = 'mysqli';
$CONF['database_host'] = 'postfixadmin-db-upgrade';
$CONF['database_user'] = 'postfixadmin';
$CONF['database_password'] = 'testpass';
$CONF['database_name'] = 'postfixadmin';
$CONF['encrypt'] = 'md5crypt';
