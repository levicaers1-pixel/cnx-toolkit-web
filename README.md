# CNX Toolkit (web)

Tools to migrate and onboard network devices into **HPE Aruba Networking Central** (new Central): AOS-CX switches,
Mobility Gateways and AOS-8 access points. The web app is available in English and Dutch (switch at the top right);
the manual is in both languages ([MANUAL.md](MANUAL.md), [LEESMIJ.md](LEESMIJ.md)). The command-line tools are in Dutch.

> **Not an HPE product.** This project is not made, supported or endorsed by Hewlett Packard Enterprise. HPE, Aruba and
> HPE Aruba Networking Central are trademarks of Hewlett Packard Enterprise. The software changes configuration in
> Central and therefore on network devices: always run a dry run first and use it at your own risk.

## Status

A **hosted web version** of the CNX Toolkit (based on CNX Toolkit 1.25.2). It runs as a local app (`cnx web`) or as a
server for several users (`cnx web --server`, or the container image):

- **Stores no customer data.** No database and nothing written to disk on the server. Central credentials live only in
  memory for the session; inventories, migration plans and import files stay in the browser or are downloaded.
- **One Central connection per user**, so several people can use one hosted instance safely.
- **Runs as a container** (`docker run`), self-hosted or on Azure Container Apps, optionally behind a pilot access code.

**Public instance: [cnx.caersultancy.com](https://cnx.caersultancy.com)** (currently a closed pilot with an access code).

Tested in server mode on Azure Container Apps behind its HTTPS proxy, with sign-in to a real new Central. The commands in
the AP migration plan (steps marked *check*) are not yet verified against HPE's migration guide.

See [docs/WEBAPP.md](docs/WEBAPP.md) for the design.

## Features

- **Onboarden**: pick a device group in new Central, check IP and hostname per switch or gateway, download the bulk
  alias import file.
- **Overrides controleren**: compare local overrides per switch with the library, and remove them via the API after a
  plan you see first.
- **AP-migratie**: read an AOS-8 inventory (`show ap database long`, `show switches`, or Excel/CSV), get an AOS-10
  readiness report and a step-by-step migration plan per cluster.

## Running with Docker

```bash
docker run -d -p 8080:8080 -e CNX_HOSTS=cnx.example.com --read-only ghcr.io/levicaers1-pixel/cnx-toolkit-web:latest
```

Free hosting on Azure Container Apps (public, no login): see [docs/AZURE.md](docs/AZURE.md) (Dutch).

Put it behind a reverse proxy with HTTPS: the session cookie is `Secure`. `CNX_HOSTS` lists the host names the app is
reachable on. Set `CNX_PROXY=1` only behind a proxy that sets `X-Forwarded-For` itself. Health check: `GET /gezond`.

## Running locally

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
cnx web
```

Usage (Dutch): [LEESMIJ.md](LEESMIJ.md). Development notes (Dutch): [docs/ONTWIKKELING.md](docs/ONTWIKKELING.md).

## Security

See [SECURITY.md](SECURITY.md) for what data goes where and how to report a problem, and the privacy statement
([PRIVACY.md](PRIVACY.md), [Dutch](PRIVACY.nl.md)); the hosted app shows it at `/privacy`.

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE).
