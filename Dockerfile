# luach's container image, for Docker Compose or any container host.
#
# State (agent checkpoints, the mail key, the loops lock) lives under /var/lib/luach, a
# volume; the built PWA is at /opt/luach/web/dist. Secrets can be plain environment
# variables, or arrive as they do under systemd, a secrets.env and Google key files in
# $CREDENTIALS_DIRECTORY (a mounted secret, say); config.load_credentials() folds them in
# at startup.

# The web app is JavaScript and CSS, the same on every processor, so it is built on the build
# machine's own (BUILDPLATFORM) rather than under emulation for each platform of the image.
FROM --platform=$BUILDPLATFORM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS build
WORKDIR /src
# The dependencies are requirements.lock, exactly: every version pinned and every file checked
# against its hash, so two builds of one commit install the same packages and a release upstream
# changes nothing until a commit moves the lock (scripts/lock.sh). Their own layer, so a change
# to src/ alone does not reinstall them. luach itself then goes in on its own, --no-deps: the
# lock already holds everything it needs.
COPY requirements.lock ./
RUN pip install --no-cache-dir --prefix=/install --require-hashes -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install --no-deps .

# The ONNX model behind what luach remembers, fetched at build time rather than
# on first boot. This download can lose recall — to a missing package, or to a
# cache directory it cannot write — and silently, because a memory tool that
# raises still produces a friendly reply.
# Baked into the image there is nothing to download, nothing to write, and no
# dependency on huggingface being up the morning of a deploy.
FROM build AS embedder
ENV PYTHONPATH=/install/lib/python3.12/site-packages \
    HF_HOME=/model/hub HF_XET_CACHE=/model/hub XDG_CACHE_HOME=/model/hub
RUN python -c "\
from fastembed import TextEmbedding; \
m = TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/model'); \
print('embedding dimension', len(next(iter(m.embed(['probe'])))))"

FROM python:3.12-slim
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin luach \
 && install -d -o 10001 -g 10001 -m 700 /var/lib/luach
COPY --from=build /install /usr/local
COPY --from=web /web/dist /opt/luach/web/dist
COPY --from=embedder --chown=10001:10001 /model /opt/luach/embed
# The store is Postgres, LUACH_DATABASE_URL, set by the deployment; the data volume holds
# the state below.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    LUACH_STATE_DIR=/var/lib/luach \
    LUACH_STATIC_DIR=/opt/luach/web/dist \
    LUACH_EMBED_CACHE=/opt/luach/embed \
    LUACH_HOST=0.0.0.0 \
    LUACH_PORT=8004
USER 10001:10001
EXPOSE 8004
# 0.0.0.0 inside the container only; how the port is published (127.0.0.1 in the compose
# file) and the app's own login decide who gets in. LUACH_TRUSTED_PROXIES must list the
# network the reverse proxy connects from.
CMD ["python", "-m", "luach"]
