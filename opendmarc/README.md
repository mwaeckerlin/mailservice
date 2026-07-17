# OpenDMARC

Enforces DMARC on incoming mail. Runs as a milter after opendkim so it can
consume opendkim's `Authentication-Results: … dkim=…` header, and does its
own SPF check via `libspf2`. On a hard DMARC fail against a sender that
publishes `p=reject`, mail is rejected at SMTP time with `550 5.7.1`.

## Environment variables

| Variable        | Default                                                            | Description                                                                                                                                                                                                                                    |
|-----------------|--------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `DKIM_DMARC`    | `reject`                                                           | Enforcement level shared with `opendkim` (must be identical on both). One of `off` (pass-through, no A-R), `log` (verify, stamp A-R, never reject), `permissive` and `reject` (both reject on `p=reject` hard fail — DMARC-side there is nothing stricter than «respect `p=reject`»). See the DMARC verdict matrix below. |
| `AUTHSERV_ID`   | `mail.local`                                                       | Authentication-service identifier used both to stamp opendmarc's own A-R header and (via `TrustedAuthservIDs`) to decide which upstream A-R lines to trust. **Set opendkim's `AuthservID` to the same value** so opendmarc sees its dkim= result. |
| `TRUSTED_HOSTS` | `127.0.0.1 ::1 localhost 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16`  | Space-separated hosts/CIDRs written to `IgnoreHosts` — connections from these skip DMARC entirely (own users / internal container-to-container traffic).                                                                                       |

## What it does

For every non-ignored incoming mail:

1. Extracts `From:` header domain.
2. Looks up `_dmarc.<from-domain>` in DNS.
3. Reads DKIM verdict from the trusted `Authentication-Results` header
   opendkim added upstream in the milter chain.
4. Runs its own SPF check (`SPFSelfValidate true`) via `libspf2`.
5. If neither DKIM nor SPF is aligned with the `From:` domain **and** the
   sender's DMARC policy is `p=reject`, the mail is rejected with
   `550 5.7.1` at SMTP time. `p=quarantine` and `p=none` do not reject.

Own users (SASL-authenticated submissions and internal container networks)
are covered by `TRUSTED_HOSTS` / `IgnoreHosts` and never see DMARC
enforcement.

## DMARC verdict matrix

| Incoming mail state                                    | `off`          | `log`                            | `permissive` / `reject`    |
|--------------------------------------------------------|----------------|----------------------------------|-----------------------------|
| No `_dmarc` record for the `From:` domain              | accept, no A-R | accept, `dmarc=none`             | accept, `dmarc=none`        |
| `_dmarc … p=none`, alignment fails                     | accept, no A-R | accept, `dmarc=fail (dis=none)`  | accept, `dmarc=fail`        |
| `_dmarc … p=quarantine`, alignment fails               | accept, no A-R | accept, `dmarc=fail (dis=none)`  | accept, `dmarc=fail`        |
| `_dmarc … p=reject`, alignment fails                   | accept, no A-R | accept, `dmarc=fail (dis=none)`  | **reject** (`550 5.7.1`)    |
| Any policy, DKIM or SPF aligned with `From:` domain    | accept, no A-R | accept, `dmarc=pass`             | accept, `dmarc=pass`        |

`log` is the safe upgrade mode — opendmarc stamps every result but never
rejects. Escalate to `permissive` (== `reject` on the DMARC side —
there is no stricter DMARC action than «respect `p=reject`») once you
have watched for `dmarc=fail (dis=none)` in delivered mail for a few
days and are confident no legitimate sender is caught.

## Postfix integration

Set the `OPENDMARC` environment variable on the postfix service:

```yaml
postfix:
  environment:
    OPENDKIM:  opendkim
    OPENDMARC: opendmarc   # host[:port], default port 8893
```

Postfix appends `inet:opendmarc:8893` to its milter list AFTER the opendkim
milter, so opendmarc sees opendkim's `Authentication-Results` header at
end-of-message.

## Image layout

The image is built in three stages, matching `mwaeckerlin/nginx`,
`mwaeckerlin/php-fpm` and the sibling `opendkim`:

1. **`init`** — compiles `init.cpp` statically with `g++ -static -Os -flto`.
   The resulting binary parses env, composes the runtime `opendmarc.conf`
   under `/run/opendmarc/`, and `execv`s the daemon.
2. **`build`** — installs `opendmarc` on the Alpine base, then uses
   `tar cph … + ldd` to collect only the binaries, shared libraries and
   configs the runtime actually needs into `/root/`.
3. **runtime** — `FROM mwaeckerlin/scratch`, `COPY --from=build /root/ /`.
   No shell, no package manager. `ENTRYPOINT ["/usr/bin/init"]`.
