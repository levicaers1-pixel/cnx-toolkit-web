# Security

## What data goes where

| Data | Where it is |
|---|---|
| Central client ID and secret | Only in memory, for the session. Never written to disk or logs. |
| Access token | Only in memory; renewed automatically when it expires. |
| Device data from Central (serials, IPs, hostnames, aliases) | Read from Central on request, sent to your browser. |
| Uploaded files (AOS-8 inventory, CSV) | Processed in memory. |

**Current version:** the app still runs locally on `127.0.0.1` and keeps import files, logs, the AOS-8 inventory and
migration-plan progress in a local folder `cnx-web/`. The hosted version will store none of this on the server; see
[docs/WEBAPP.md](docs/WEBAPP.md).

Use a Central API client with only the permissions you need. Anything that writes to Central runs as a dry run first.

## Reporting a problem

Please do not open a public issue for a security problem. Use
[GitHub private vulnerability reporting](../../security/advisories/new) for this repository instead.
