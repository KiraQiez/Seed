setup:
    uv sync --locked

check:
    uv lock --check
    uv run --locked ruff check .
    uv run --locked ruff format --check .
    uv run --locked mypy src tests
    uv run --locked pytest tests/unit

build:
    uv build

test-integration:
    uv run --locked pytest tests/integration

test-e2e:
    uv run --locked pytest tests/e2e

benchmark:
    sh tests/benchmark/run.sh
