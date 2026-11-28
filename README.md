<h1 align="center">
  <img src="docs/assets/seed-hero.jpg" alt="Seed" width="100%">
</h1>

<p align="center">
  <img src="docs/assets/seed-icon.png" alt="" width="64" height="64">
  <br>
  <strong>Generate realistic, related test data for PostgreSQL.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/seed-dev-db/"><img src="https://img.shields.io/pypi/v/seed-dev-db?logo=pypi&amp;color=24754d" alt="Latest Seed version on PyPI"></a>
  <a href="https://github.com/KiraQiez/Seed/actions/workflows/quality.yml?query=branch%3Amain"><img src="https://github.com/KiraQiez/Seed/actions/workflows/quality.yml/badge.svg?branch=main&amp;event=push" alt="CI checks on main"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.12%2B-306998?logo=python&amp;logoColor=white" alt="Requires Python 3.12 or newer"></a>
  <a href="docs/DATA_MODEL.md#postgresql-support"><img src="https://img.shields.io/badge/PostgreSQL-15%E2%80%9319-336791?logo=postgresql&amp;logoColor=white" alt="Tested on PostgreSQL 15 through 19"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-586174" alt="Apache 2.0 license"></a>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="Guide.md">Guide</a> ·
  <a href="#run-from-source">Run from source</a> ·
  <a href="#documentation">Docs</a>
</p>

Seed is a command-line tool for filling development and test databases with synthetic data. It inspects your PostgreSQL schema and generates parent rows before the rows that reference them. Preview the data, apply it in one transaction, or export it as SQL, CSV, or JSON.

## Install

**macOS and Linux x86-64 with Homebrew**

```sh
brew install KiraQiez/tap/seed
seed --version
```

If Homebrew prompts for trust, run `brew trust --formula KiraQiez/tap/seed` and retry.

| Other installers | Command |
| --- | --- |
| uv | `uv tool install seed-dev-db` |
| pipx | `pipx install seed-dev-db` |

uv and pipx work on macOS, Linux, and Windows. Seed requires Python 3.12 or newer. [Releases and checksums](https://github.com/KiraQiez/Seed/releases)

## Use Seed in a project

Start with `seed init --interactive` to choose tables and row counts. Set `DATABASE_URL` for your development or test database, then run `seed preview` to see sample rows.

The [beginner guide](Guide.md) walks through setup, preview, export, and the checks before inserting rows. It also includes a disposable PostgreSQL example.

## Run from source

Use the `staging` branch for development and the locked contributor environment.

```sh
git clone --branch staging https://github.com/KiraQiez/Seed.git
cd Seed
uv sync --locked
uv run --locked seed --help
```

Run `just check` for lint, formatting, types, and unit tests. With Docker and Compose running, use `just test-integration` and `just test-e2e` to exercise disposable PostgreSQL fixtures.

## Documentation

| Topic | Guide |
| --- | --- |
| Commands, options, and exit codes | [CLI specification](docs/CLI_SPEC.md) |
| Configuration, supported schemas, and output formats | [Data model](docs/DATA_MODEL.md) |
| Database and file safety | [Security](docs/SECURITY.md) |
| Project design and scope | [Architecture](docs/ARCHITECTURE.md) · [Product requirements](docs/PRD.md) |
| Contributor checks and conventions | [Development guide](docs/DEVELOPMENT.md) · [Contributing](CONTRIBUTING.md) |
| Release plans and implementation status | [Release guide](docs/RELEASE.md) · [Roadmap](docs/ROADMAP.md) |

[Apache License 2.0](LICENSE)
