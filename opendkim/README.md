# OpenDKIM

Signs outgoing mail and verifies DKIM signatures on incoming mail.

## Environment variables

| Variable   | Default | Description                          |
|------------|---------|--------------------------------------|
| `DOMAIN`   | —       | **Required.** Domain to sign for     |
| `SELECTOR` | `mail`  | DKIM selector (DNS label)            |

## Key management

On first start the container auto-generates a 2048-bit RSA key and prints the
DNS TXT record you must publish:

```
Name:  mail._domainkey.example.com
Type:  TXT
Value: v=DKIM1; h=sha256; k=rsa; p=<public-key>
```

The private key is stored in the `/etc/opendkim/keys` volume — back it up and
keep it secret. To rotate keys:

1. Set `SELECTOR` to a new name (e.g. `mail2`).
2. Restart the container — a new key is generated and printed.
3. Publish the new DNS record.
4. After the old selector's TTL expires, remove it from DNS.

## Postfix integration

Set the `OPENDKIM` environment variable on the postfix service:

```yaml
postfix:
  environment:
    OPENDKIM: opendkim
```

Postfix appends `inet:opendkim:10026` to its milter list automatically.
