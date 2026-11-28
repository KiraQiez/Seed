<h1 align="center">
  <img src="docs/assets/seed-hero.jpg" alt="Seed" width="100%">
</h1>

<p align="center">
  <img src="docs/assets/seed-icon.png" alt="" width="32" height="32">
  <br>
  <strong>Generate realistic, related test data for PostgreSQL.</strong>
</p>

<p align="center">
  <a href="https://github.com/KiraQiez/Seed/actions/workflows/quality.yml?query=branch%3Astaging"><img src="https://github.com/KiraQiez/Seed/actions/workflows/quality.yml/badge.svg?branch=staging&amp;event=push" alt="CI checks on staging"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.12%2B-306998?logo=python&amp;logoColor=white" alt="Requires Python 3.12 or newer"></a>
  <a href="docs/DATA_MODEL.md#postgresql-support"><img src="https://img.shields.io/badge/PostgreSQL-15%E2%80%9319-336791?logo=postgresql&amp;logoColor=white" alt="Tested on PostgreSQL 15 through 19"></a>
  <a href="#install"><img src="https://img.shields.io/badge/Install-from%20source-24754d" alt="Install from source"></a>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#use-seed-in-a-project">Use Seed</a> ·
  <a href="#run-from-source">Run from source</a> ·
  <a href="#documentation">Docs</a>
</p>

Seed is a command-line tool for filling development and test databases with synthetic data. It inspects your PostgreSQL schema and generates parent rows before the rows that reference them. Preview the data, apply it in one transaction, or export it as SQL, CSV, or JSON.

## Install

Install the staging checkout as a CLI with uv. Seed requires Python 3.12 or newer.

```sh
git clone --branch staging https://github.com/KiraQiez/Seed.git
cd Seed
uv tool install .
seed --version
```

If your shell cannot find `seed`, run `uv tool update-shell` and open a new terminal.

Seed is currently available from source. [Release and distribution plans](docs/RELEASE.md)

## Use Seed in a project

In your project directory, create `seed.toml` with `seed init`. Set `DATABASE_URL` in your shell to your development or test database URL. Set the schema in `seed.toml` if it differs from `public`. This example assumes your schema already has a `customers` table. [Configuration example](docs/DATA_MODEL.md#configuration)

```sh
seed inspect
seed plan --table customers
seed preview --table customers --limit 5
```

To write rows, add the matching `[safety.target]` and set `safety.environment` to `development` or `test`. Review the dry-run, then confirm the write at the prompt. [Apply safety](docs/SECURITY.md#apply-safety)

```sh
seed apply --table customers --dry-run
seed apply --table customers
```

| When you want to… | Run |
| --- | --- |
| Check all planned rows offline | `seed validate --table customers --dataset` |
| Preview a sample | `seed preview --table customers --limit 5` |
| Export a relational dataset | `seed export --table customers --format json` |
| Export files for PostgreSQL import | `seed export --table customers --format sql` or `seed export --table customers --format csv` |
| Read the plan in a script | `seed plan --table customers --json` |

Export creates a fresh `seed-export` directory by default. The manifest indicates that all files were written. [Import and sequence reconciliation](docs/SECURITY.md#sql-and-export-safety)

## Run from source

From the Seed checkout, use the locked contributor environment.

```sh
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
| Contributor checks and conventions | [Development guide](docs/DEVELOPMENT.md) · [Repository instructions](AGENTS.md) |
| Release plans and implementation status | [Release guide](docs/RELEASE.md) · [Roadmap](docs/ROADMAP.md) |

[Licence status](docs/RELEASE.md#naming-licence-and-versions)
