-- Minimal postfixadmin-compatible schema for e2e testing.
-- Passwords use PLAIN scheme (set DEFAULT_PASS_SCHEME=PLAIN in dovecot).

CREATE TABLE domain (
  domain      varchar(255)    NOT NULL,
  active      tinyint(1)      NOT NULL DEFAULT 1,
  PRIMARY KEY (domain)
) ENGINE=InnoDB;

CREATE TABLE mailbox (
  username    varchar(255)    NOT NULL,
  password    varchar(255)    NOT NULL,
  local_part  varchar(255)    NOT NULL,
  domain      varchar(255)    NOT NULL,
  maildir     varchar(255)    NOT NULL DEFAULT '',
  active      tinyint(1)      NOT NULL DEFAULT 1,
  PRIMARY KEY (username)
) ENGINE=InnoDB;

CREATE TABLE alias (
  address     varchar(255)    NOT NULL,
  goto        text            NOT NULL,
  domain      varchar(255)    NOT NULL,
  active      tinyint(1)      NOT NULL DEFAULT 1,
  PRIMARY KEY (address)
) ENGINE=InnoDB;

CREATE TABLE alias_domain (
  alias_domain    varchar(255) NOT NULL,
  target_domain   varchar(255) NOT NULL,
  active          tinyint(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (alias_domain)
) ENGINE=InnoDB;

-- Test domain
INSERT INTO domain (domain) VALUES ('test.local');

-- Test users  (PLAIN passwords: alicepass / bobpass)
INSERT INTO mailbox (username, password, local_part, domain, maildir) VALUES
  ('alice@test.local', 'alicepass', 'alice', 'test.local', 'test.local/alice/'),
  ('bob@test.local',   'bobpass',   'bob',   'test.local', 'test.local/bob/');

-- Delivery aliases (required by postfix virtual_alias_maps)
INSERT INTO alias (address, goto, domain) VALUES
  ('alice@test.local', 'alice@test.local', 'test.local'),
  ('bob@test.local',   'bob@test.local',   'test.local');
