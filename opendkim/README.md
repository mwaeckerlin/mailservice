# OpenDKIM

Signs outgoing mail and verifies DKIM signatures on incoming mail.

## Environment variables

| Variable   | Default | Description                                                                    |
|------------|---------|--------------------------------------------------------------------------------|
| `DOMAINS`      | —      | Space-separated list of domains to sign for. One DKIM key is created per domain. |
| `DOMAIN`       | —      | Single-domain fallback. Used only when `DOMAINS` is unset. One of the two is required. |
| `SELECTOR`     | `mail` | DKIM selector (DNS label). Same selector name is used for every domain.        |
| `DKIM_DMARC`   | `reject` | Enforcement level shared with `opendmarc` (must be identical on both). One of `off`, `log`, `permissive`, `reject`. See «DKIM verification matrix» below. |
| `DKIM_KEYERROR_ACTION` | `reject` | Only relevant when `DKIM_DMARC` is `permissive` or `reject`. `reject` returns `5.7.20` immediately; `tempfail` returns `4xx` so the sender-side MX retries — useful if you want to tolerate short DKIM key-rotation gaps. |
| `TRUSTED_HOSTS` | `127.0.0.1 ::1 localhost 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16` | Space-separated list of hosts/CIDRs considered internal (`InternalHosts` only — the sign path). `ExternalIgnoreList` (the verify-skip path) is hard-wired to loopback so a non-loopback sender's incoming signature is always verified, even if the same sender's outgoing mail is signed via `InternalHosts`. |
| `AUTHSERV_ID` | `mail.local` | `AuthservID` written into every `Authentication-Results` header opendkim adds. **Must match opendmarc's `AUTHSERV_ID`** so opendmarc trusts opendkim's `dkim=` verdict when deciding DMARC alignment. |

## Key management

On first start the container auto-generates a 2048-bit RSA key per domain and
prints the DNS TXT record you must publish:

```
Name:  mail._domainkey.example.com
Type:  TXT
Value: v=DKIM1; h=sha256; k=rsa; p=<public-key>
```

The private keys are stored in the `/etc/opendkim/keys/<domain>/` volume —
back them up and keep them secret. To rotate keys:

1. Set `SELECTOR` to a new name (e.g. `mail2`).
2. Restart the container — a new key is generated per domain and printed.
3. Publish each new DNS record.
4. After the old selector's TTL expires, remove it from DNS.

## Multi-domain example

Sign for four domains with one container:

```yaml
opendkim:
  environment:
    DOMAINS: "example.com example.net example.email example.org"
```

Adding a new domain later is a live operation: extend `DOMAINS`, restart the
container, publish the printed DNS record. Existing domains' keys are reused
(no re-generation) because the private key file already exists.

## DKIM verification matrix

| Incoming mail state                             | `off`               | `log`                              | `permissive` (Marc's design default) | `reject` (image default)      |
|-------------------------------------------------|---------------------|------------------------------------|--------------------------------------|-------------------------------|
| Correct signature, key in DNS                   | accept, no A-R      | accept, `dkim=pass`                | accept, `dkim=pass`                  | accept, `dkim=pass`           |
| No `DKIM-Signature` header at all               | accept, no A-R      | accept, `dkim=none`                | accept, `dkim=none`                  | **reject** (`5.7.20`)         |
| Signature present, verification fails           | accept, no A-R      | accept, `dkim=fail`                | **reject** (`5.7.20`)                | **reject** (`5.7.20`)         |
| Signature present, DKIM key missing in DNS      | accept, no A-R      | accept, `dkim=permerror`           | **reject** (`5.7.20`)                | **reject** (`5.7.20`)         |

`log` is the safe upgrade mode — verify, stamp the verdict into an
`Authentication-Results` header, never reject. `permissive` is the
production semantic: DKIM is opt-in for the sender, but the moment a
sender opts in (publishes a `_domainkey` record) any misconfiguration or
forgery attempt is rejected — never silently delivered. `reject` extends
that from «sender opted in» to «every sender must opt in» and is the
right choice for an ingress that only accepts mail from known,
DKIM-signing peers.

## Postfix integration

Set the `OPENDKIM` environment variable on the postfix service:

```yaml
postfix:
  environment:
    OPENDKIM: opendkim
```

Postfix appends `inet:opendkim:10026` to its milter list automatically.

## Image layout

The image is built in three stages (same pattern as `mwaeckerlin/nginx` and
`mwaeckerlin/php-fpm`):

1. **`init`** — compiles `init.cpp` statically with `g++ -static -Os -flto`.
   The resulting binary parses `DOMAINS`/`DOMAIN`/`SELECTOR`, generates
   missing keys via `openssl genrsa`, writes `KeyTable`, `SigningTable` and
   `TrustedHosts`, then `execv`s the daemon. Replaces the old `start.sh`
   *and* `opendkim-genkey` (Perl).
2. **`build`** — installs `opendkim` and `openssl` on the Alpine base, then
   uses `tar cph … + ldd` to collect only the binaries, shared libraries
   and configs the runtime actually needs into `/root/`.
3. **runtime** — `FROM mwaeckerlin/scratch`, `COPY --from=build /root/ /`.
   No shell, no package manager, no Perl. `ENTRYPOINT ["/usr/bin/init"]`.
