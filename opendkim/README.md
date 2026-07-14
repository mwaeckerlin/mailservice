# OpenDKIM

Signs outgoing mail and verifies DKIM signatures on incoming mail.

## Environment variables

| Variable   | Default | Description                                                                    |
|------------|---------|--------------------------------------------------------------------------------|
| `DOMAINS`  | —       | Space-separated list of domains to sign for. One DKIM key is created per domain. |
| `DOMAIN`   | —       | Single-domain fallback. Used only when `DOMAINS` is unset. One of the two is required. |
| `SELECTOR` | `mail`  | DKIM selector (DNS label). Same selector name is used for every domain.        |

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
