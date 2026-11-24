# CNX Toolkit (web)

Tools to migrate and onboard network devices into **HPE Aruba Networking Central** (new Central): AOS-CX switches,
Mobility Gateways and AOS-8 access points. The user interface and documentation are in Dutch for now.

> **Not an HPE product.** This project is not made, supported or endorsed by Hewlett Packard Enterprise. HPE, Aruba and
> HPE Aruba Networking Central are trademarks of Hewlett Packard Enterprise. The software changes configuration in
> Central and therefore on network devices: always run a dry run first and use it at your own risk.

## Status

A **hosted web version** of the CNX Toolkit (based on CNX Toolkit 1.25.2). It runs as a local app (`cnx web`) or as a
server for several users (`cnx web --server`, or the container image):

- **Stores no customer data.** No database and nothing written to disk on the server. Central credentials live only in
  memory for the session; inventories, migration plans and import files stay in the browser or are downloaded.
- **One Central connection per user**, so several people can use one hosted instance safely.
- **Runs as a container** (`docker run`), self-hosted or behind a login such as Microsoft Entra ID.

Not yet tested behind a real HTTPS proxy or against a real Central in server mode.

See [docs/WEBAPP.md](docs/WEBAPP.md) for the plan.

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

Put it behind a reverse proxy with HTTPS: the session cookie is `Secure`. `CNX_HOSTS` lists the host names the app is
reachable on. Health check: `GET /gezond`.

## Running locally

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
cnx web
```

Usage (Dutch): [LEESMIJ.md](LEESMIJ.md). Development notes (Dutch): [docs/ONTWIKKELING.md](docs/ONTWIKKELING.md).

## Security

See [SECURITY.md](SECURITY.md) for what data goes where and how to report a problem.

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE).
