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
