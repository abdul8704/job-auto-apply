FROM python:3.12-slim

ARG TECTONIC_VERSION=0.15.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates fontconfig \
 && curl -fsSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
    | tar xz -C /usr/local/bin \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home app
WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .
COPY alembic.ini ./
COPY alembic ./alembic
COPY config ./config

USER app
# Download and cache the LaTeX packages the templates need, so the first real render is fast.
RUN python -m app.rendering.warmup

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
