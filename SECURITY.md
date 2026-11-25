# Security

## What data goes where

| Data | Where it is |
|---|---|
| Central client ID and secret | Only in memory, for the session. Never written to disk or logs. |
| Access token | Only in memory; renewed automatically when it expires. |
| Device data from Central (serials, IPs, hostnames, aliases) | Read from Central on request, sent to your browser. |
| Uploaded files (AOS-8 inventory, CSV) | Processed in memory. |

**Local app** (`cnx web`, on `127.0.0.1`): keeps a copy of import files and logs in a local folder `cnx-web/`.
**Server mode** (`cnx web --server`) and `--zonder-opslag`: nothing is written to disk. Import files and logs are
only sent to the browser. The AOS-8 inventory and migration-plan progress always stay in the browser (local storage),
never on the server. See [docs/WEBAPP.md](docs/WEBAPP.md).

In server mode (`cnx web --server`) each browser gets its own session: an HttpOnly, Secure, SameSite=Strict cookie and
its own CSRF token. A session, including the Central secret, is wiped after 30 minutes without activity or on sign-out.
Logs contain only the method, the path without parameters, the status and the duration. Sign-in is only allowed to
https addresses on the Central domains (`CNX_CENTRAL_DOMEINEN`, default `arubanetworks.com`).

Uploads are bounded (a decompressed-size, row, column and cell limit for Excel files; no DOCTYPE), at most two
heavy jobs run at once, idle connections time out after 60 seconds, and pages carry HSTS and a nonce-based
Content-Security-Policy. Per-visitor limits trust `X-Forwarded-For` only with `CNX_PROXY=1` (behind a proxy that
sets it, such as Azure Container Apps).

An optional access code (`CNX_PILOTCODE`, set as a secret in the hosting platform, never in the repository) can
restrict a hosted instance during a pilot; failed attempts are rate limited.

Use a Central API client with only the permissions you need. Anything that writes to Central runs as a dry run first.

## Supply chain

GitHub Actions are pinned to commit SHAs and the base image to a digest; Dependabot proposes updates weekly
(`.github/dependabot.yml`). Dependabot security updates, CodeQL code scanning and secret scanning with push
protection are enabled. What the app does with personal data: see [PRIVACY.md](PRIVACY.md).

## Reporting a problem

Please do not open a public issue for a security problem. Use
[GitHub private vulnerability reporting](../../security/advisories/new) for this repository instead.
