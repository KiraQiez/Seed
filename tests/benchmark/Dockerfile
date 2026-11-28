FROM ghcr.io/astral-sh/uv:0.13.9 AS uv
FROM docker.io/library/postgres:16
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends time && rm -rf /var/lib/apt/lists/*
WORKDIR /benchmark
COPY pyproject.toml uv.lock LICENSE ./
COPY docs/PYPI.md docs/PYPI.md
COPY src src
RUN uv sync --locked --no-dev --python 3.12
COPY tests/fixtures/ecommerce.sql tests/fixtures/ecommerce.sql
COPY tests/benchmark tests/benchmark
ENTRYPOINT ["sh", "tests/benchmark/container.sh"]
