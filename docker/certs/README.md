# Corporate TLS certificates

This directory is copied into each Debian image and processed by
`update-ca-certificates`. Put only trusted corporate **CA** certificates here,
not website/server leaf certificates.

## Recommended workflow

Obtain the corporate root or issuing CA from your IT/security team or export it
from the managed host trust store, then run:

```bash
make certs CA_FILE=/path/to/corporate-root.crt
make doctor
docker compose build --no-cache
```

The staging script accepts PEM or DER input, validates X.509, keeps only
certificates with `Basic Constraints: CA:TRUE`, and writes one certificate per
`.crt` file. Debian's `update-ca-certificates` expects one certificate per file.

If the host itself reports certificate failures, install the same CA in the host
trust store:

```bash
make host-certs CA_FILE=/path/to/corporate-root.crt
```

That target supports Debian/Ubuntu-style Linux and macOS. On Windows, use an
elevated PowerShell/CMD and add the corporate CA to the Trusted Root store with
`certutil -addstore -f Root <certificate>`, subject to your organization's
endpoint-management policy.

## Why the old automatic capture was removed

`openssl s_client -showcerts` shows the chain a server/proxy chooses to present.
That chain commonly omits the trust root, and it includes the website leaf.
Blindly adding the returned chain to the local trust store can therefore trust
the wrong certificate and also violates Debian's one-certificate-per-file
expectation. Use the actual managed corporate CA instead.

The build deliberately does **not** fall back to pip `--trusted-host`; TLS
verification remains enabled.
