# Seed

**Schema-Aware Database Seeder**

Seed is a planned open-source CLI for populating development and test databases with realistic synthetic data. It inspects a PostgreSQL schema, plans parent-first generation, and lets developers and QA teams review the results before applying or exporting them.

**Status.** The Python foundation is available from source. It provides help, version, starter configuration creation, read-only PostgreSQL schema inspection, generation planning, validation, offline preview, guarded database apply, and SQL, CSV, and JSON exports.

Run `just setup` from the checkout and use `uv run seed --help` to list commands. The workflow below assumes a development or test database with a `customers` table.

## Workflow

```bash
uv run seed init
uv run seed inspect
uv run seed plan --table customers
uv run seed preview --table customers --limit 5
uv run seed validate --table customers --dataset
uv run seed export --table customers --format json
uv run seed apply --table customers --dry-run
uv run seed apply --table customers
```

After `init`, set `DATABASE_URL` to the connection URL and adjust the schema in `seed.toml` as needed. Before the two apply commands, configure the explicit development or test target, review the dry-run, and confirm the real write at the prompt. [Configuration example](docs/DATA_MODEL.md#configuration)

Export creates a fresh `seed-export` directory with a completion manifest. [Import and sequence reconciliation](docs/SECURITY.md#sql-and-export-safety)

The MVP uses a standalone Python package, PostgreSQL, and Faker. It includes supported composite keys, deterministic data generation, transactional insertion, and SQL, CSV, and JSON exports. See the [product requirements](docs/PRD.md#mvp-workflow) for scope.

## Documentation

| Topic | Reference |
|---|---|
| Product goals and requirements | [PRD](docs/PRD.md) |
| Design, generation, stack, and decisions | [Architecture](docs/ARCHITECTURE.md) |
| Commands and exit codes | [CLI specification](docs/CLI_SPEC.md) |
| Configuration, PostgreSQL support, and formats | [Data model](docs/DATA_MODEL.md) |
| Target safety, transactions, and exports | [Security](docs/SECURITY.md) |
| Contributor checks and benchmarks | [Development guide](docs/DEVELOPMENT.md) |
| Implementation checklist and milestones | [Roadmap](docs/ROADMAP.md) |
| Packaging and publication | [Release guide](docs/RELEASE.md) |

Contributors start with the roadmap and development guide. Coding agents start at [AGENTS.md](AGENTS.md). Seed’s names and Apache-2.0 licence are provisional pending [release review](docs/RELEASE.md#naming-licence-and-versions).
