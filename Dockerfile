# CNX Toolkit (web) in servermodus: per gebruiker een sessie, niets op schijf.
#   docker run -p 8080:8080 -e CNX_HOSTS=cnx.voorbeeld.be ghcr.io/levicaers1-pixel/cnx-toolkit-web
# Zet de container achter een reverse proxy met HTTPS (de sessiecookie is Secure).
# Vaste digest (multi-arch index) van python:3.12-slim op 2026-11-25; Dependabot stelt nieuwe digests voor.
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /build
COPY pyproject.toml LEESMIJ.md LICENSE NOTICE ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && rm -rf /build \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin cnx

# Niets om naar te schrijven: de app draait ook met --read-only.
WORKDIR /app
USER 10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8080') + '/gezond', timeout=4)"]

# Hostnamen via CNX_HOSTS (komma's), of voeg --host-naam toe na de image-naam.
ENTRYPOINT ["cnx", "web", "--server"]
