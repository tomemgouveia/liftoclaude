FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN npm install --no-save --no-package-lock wrangler@latest

COPY pyproject.toml uv.lock README.md ./
COPY src/liftostrava ./src/liftostrava
COPY src/cloudflare_worker.py ./src/cloudflare_worker.py
COPY wrangler.toml ./

RUN uv sync --frozen \
    && uv run pywrangler sync \
    && cp -R src/liftostrava python_modules/liftostrava

EXPOSE 8787

CMD ["uv", "run", "pywrangler", "dev", "--ip", "0.0.0.0"]
