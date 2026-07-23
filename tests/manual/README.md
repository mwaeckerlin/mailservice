# Manual two-domain test environment

A realistic, fully offline playground on a single Linux machine: **two
complete, independent mailservice deployments** (domain `alice` and
domain `bob`) that deliver mail to each other over real server-to-server
SMTP, plus a **local pseudo-CA** («letsencrypt») that issues the TLS
certificates both stacks use. You drive everything the way a real user
and a real operator would — admin UI, webmail, OpenPGP, a native mail
client — and watch the advertised guarantees hold: TLS between the
servers, encrypted mail that is ciphertext on the wire, and spam that is
rejected with a proper error instead of vanishing.

Unlike the automated e2e suite (`npm test`) this environment is meant
for **exploration by hand**: no assertions, no teardown after three
minutes — it keeps running until you stop it.

## Architecture

```
 /etc/hosts (host only):  127.0.0.1  alice bob letsencrypt

 ┌───────────────────────┐   manual-mailnet    ┌───────────────────────┐
 │  stack «alice»        │  (shared network)   │  stack «bob»          │
 │  postfixadmin :8080   │                     │  postfixadmin :9080   │
 │  snappymail   :8081   │   postfix ⇄ postfix │  snappymail   :9081   │
 │  IMAPS        :1993   │   («alice» ⇄ «bob») │  IMAPS        :2993   │
 │  submission   :1587   │                     │  submission   :2587   │
 └───────────────────────┘                     └───────────────────────┘
              ▲                     ▲                     ▲
              └────────── manual-letsencrypt volume ──────┘
                 (pseudo-CA: live/alice, live/bob, ca.crt)
                 served at http://letsencrypt:8082/ca.crt
```

- **Pseudo-DNS, two layers.** On the **host**, one `/etc/hosts` line
  maps the three names to loopback so your browser and mail client can
  use pretty URLs. **Between the containers** `/etc/hosts` of the host
  is invisible — Docker containers resolve through Docker's own DNS —
  so the two `postfix` services join the shared `manual-mailnet`
  network under the aliases `alice` and `bob`. There are no MX records
  in this pseudo-DNS; postfix falls back to the A record (the alias),
  which is exactly the standard implicit-MX behaviour.
- **Pseudo-CA.** The `letsencrypt` compose generates a local CA once
  and issues one certificate per mail domain into the shared
  `manual-letsencrypt` volume, using the `/etc/letsencrypt/live/<domain>/`
  layout the postfix/dovecot images look for. Both mail stacks mount
  that volume read-only — TLS between the two postfixes and on
  IMAPS/submission is real, chained to your local CA. A tiny web
  server offers `ca.crt` for import into a browser or mail client.
- **`DKIM_DMARC=off`** in both stacks, deliberately: there is no real
  DNS between them, so SPF/DKIM/DMARC verification of the peer cannot
  work. Everything else stays fully armed — the spam score threshold,
  the GTUBE reject and the ClamAV virus reject (that is what the spam
  test case below exercises).

## Prerequisites

- Linux with Docker + Docker Compose, and `sudo` for one `/etc/hosts`
  edit.
- Free loopback ports: 8080–8082, 9080, 8081, 9081, 1587, 1993, 2587,
  2993 (change them in the compose files if something collides).
- Disk/network: each stack runs its own ClamAV, and the **first** start
  downloads the signature database (~300 MB per stack) — the antivirus
  case only works once `freshclam` has finished (watch
  `docker compose -f tests/manual/alice/docker-compose.yml logs clamav`).

## Setup

**1. Pseudo-DNS on the host** — add one line to `/etc/hosts`:

```
127.0.0.1  alice bob letsencrypt
```

**2. Start everything** (from the mailservice directory):

```bash
npm run manual:up
```

This starts, in order: the pseudo-CA (creates the shared network, the
certificate volume, the certificates), then the full `alice` stack, then
the full `bob` stack (the first run builds all images). Stop later with
`npm run manual:down`; wipe all data (mailboxes, accounts, keys,
certificates) with `npm run manual:down:wipe`.

**3. Create the mail accounts** — once per domain, exactly like a real
operator would:

| | alice | bob |
|---|---|---|
| PostfixAdmin setup | http://alice:8080/setup.php | http://bob:9080/setup.php |
| PostfixAdmin login | http://alice:8080 | http://bob:9080 |
| SnappyMail admin | http://alice:8081/?admin | http://bob:9081/?admin |
| SnappyMail webmail | http://alice:8081 | http://bob:9081 |

For **each** of the two domains:

1. Open `setup.php`, enter the setup password `test123`, create an
   admin account (password policy: ≥ 5 chars, ≥ 3 letters, ≥ 2 digits —
   e.g. `Admin123pass`).
2. Log in, add the domain (`alice` respectively `bob`), then add the
   mailbox `alice@alice` respectively `bob@bob` (e.g. password
   `alicepass12` / `bobpass12`).
3. Open the SnappyMail admin (`admin` / `12345`), *Domains* → *Add
   Domain*: name `alice` (resp. `bob`), IMAP host `dovecot` port `143`,
   SMTP host `postfix` port `25` — these are the **container-internal**
   names, identical in both stacks.
4. Log in to the webmail with the full address (`alice@alice` /
   `bob@bob`). On first login SnappyMail may pop up an identity dialog —
   enter a display name and save.

## Test cases

Work through them in order; the early ones establish what the later
ones need.

### 1. Plain mail in both directions (+ TLS transparency)

Alice (http://alice:8081) composes a mail to `bob@bob` and sends; Bob
answers. Both arrive in the INBOX — that is a real SMTP hand-over
between two independent servers, not a shared mailbox trick.

Now open the received mail and display its headers (⋮ menu → view
source): the `X-Transport-Security:` header shows the TLS version of
the **server-to-server hop**, e.g. `TLSv1.3 (cipher …)` — proving the
two postfixes really negotiated TLS with the pseudo-CA certificates.
The webmail shows no red «UNENCRYPTED» banner for the same reason (it
would for a cleartext hop).

### 2. OpenPGP setup for both users

In **each** webmail: *Settings → Security → OpenPGP*:

1. **Generate Key Pair** — name, e-mail (prefilled), a passphrase you
   remember, type ECC. The key lands in the key lists on the same page.
2. **Exchange public keys.** Open your own key (key list → click it),
   copy the armored **public** block. The other user opens *Import
   Key* in their webmail and pastes it («store in GnuPG» stays
   ticked — that is the server-side backend). Do this in both
   directions: Bob imports Alice's public key, Alice imports Bob's.

### 3. Signed-only mail

Alice composes to `bob@bob`, enables **✍ Sign** (bottom bar of the
compose window, turns green), sends, and enters her passphrase when
asked. Bob opens the mail: the signature panel verifies against
Alice's imported public key (green). Bob answers signed; Alice
verifies. The mail body itself stays readable — signature without
encryption.

### 4. Signed and encrypted mail

Alice composes to `bob@bob`, enables **✍ Sign** and **🔒 Encrypt**
(possible because she has Bob's public key), sends. Bob opens the
mail, clicks **Decrypt**, enters his passphrase — plaintext appears
and the signature verifies. Bob answers encrypted.

To see that the encryption is real, check the raw message (view
source): the body is a `-----BEGIN PGP MESSAGE-----` block — the
plaintext never travelled between the servers.

### 5. Spam is rejected, not hidden

Bob composes a mail to `alice@alice` whose body contains the
industry-standard GTUBE test string (one line, no spaces):

```
XJS*C4JDBQADN1.NSBN3*2IDNEN*GTUBE-STANDARD-ANTI-UBE-TEST-EMAIL*C.34X
```

Bob's **own** server accepts the submission (authenticated users are
never filtered — the design guarantee) and tries to deliver it to
Alice's MX, which **rejects it at SMTP time with a 5xx**. The visible
result for Bob: a bounce mail («Undelivered Mail Returned to Sender»)
in his INBOX quoting Alice's server's rejection. Alice sees nothing —
no spam folder, no silent drop: the sender got a clear, actionable
error. Exactly the «delivered or rejected, nothing in between»
philosophy.

### 6. Virus mail is rejected the same way

Same as case 5, but with the harmless industry-standard EICAR test
string as the body (or as an attachment):

```
X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*
```

Alice's ClamAV flags it, rspamd rejects at SMTP time, Bob receives the
bounce. Requires the ClamAV database download to have finished (see
prerequisites).

### 7. Alias delivery

In Bob's PostfixAdmin add an alias `info@bob` → `bob@bob` (*Virtual
List* → *Add Alias*). Alice writes to `info@bob`; the mail arrives in
Bob's INBOX with `To: info@bob` intact.

### 8. Unknown recipient is rejected

Alice writes to `nobody@bob`. Bob's MX rejects the recipient (no such
mailbox, no catch-all — deliberate), and Alice receives the bounce
with the exact reason. Nothing is silently accepted into a void.

### 9. Server-side filter rules (Sieve)

In Bob's webmail: *Settings → Filters* → create a rule «Subject
contains `SORTME` → move to folder `Sorted`» (create the folder when
asked). Alice sends a mail with `SORTME` in the subject — it lands
directly in Bob's `Sorted` folder, filtered by the **server** at
delivery time (the webmail does not need to be open).

### 10. A real mail client through the pseudo-CA

Configure a native client (e.g. Thunderbird) for Bob:

- IMAP: server `bob`, port `2993`, SSL/TLS, user `bob@bob`
- SMTP: server `bob`, port `2587`, STARTTLS

The client will distrust the self-signed chain at first. Download the
CA from http://letsencrypt:8082/ca.crt and import it as a trusted
certificate authority (Thunderbird: *Settings → Privacy & Security →
Certificates → Manage Certificates → Authorities → Import*, tick
«identify websites»/mail servers). After the import the connection
validates cleanly against the pseudo-CA — the same trust flow as a
real CA, just local. Send and receive a few mails; they interleave
seamlessly with the webmail sessions.

### More ideas

The environment is a full mailservice twice over — everything the
[FEATURES list](../../FEATURES.md) describes can be exercised here by
hand: per-mailbox quota (`DOVECOT_QUOTA=yes` on a dovecot service),
Bayes training by dragging mail into and out of Junk, POP3S, ManageSieve
with a real Sieve client, the PostfixAdmin schema upgrade, or a third
domain by copying one of the stack directories.

## Teardown

```bash
npm run manual:down        # stop; all data (accounts, mail, keys) kept
npm run manual:down:wipe   # stop AND delete all volumes — full reset
```

Remove the `/etc/hosts` line when you are done.

## Troubleshooting

- **Mail between the domains sits in the queue:** both stacks up? The
  sending postfix resolves the peer by its `manual-mailnet` alias —
  `docker compose -f tests/manual/alice/docker-compose.yml logs postfix`
  shows the delivery attempts. Postfix retries deferred mail
  automatically; the queue survives restarts (named spool volume).
- **EICAR mail is delivered instead of bounced:** freshclam has not
  finished its first download yet — check the clamav logs, retry later.
- **Browser cannot open http://alice:8081:** `/etc/hosts` entry
  missing, or a loopback port collision (adjust the `ports:` mappings).
- **Certificate warnings in the mail client:** the pseudo-CA
  (`ca.crt`) is not imported yet — see test case 10.
