# Seed

**Schema-Aware Database Seeder**

Seed is a planned open-source CLI for populating development and test databases with realistic synthetic data. It inspects a PostgreSQL schema, plans parent-first generation, and lets developers and QA teams review the results before applying or exporting them.

**Status.** The Python foundation is available from source. It provides help, version, starter configuration creation, read-only PostgreSQL schema inspection, generation planning, validation, offline preview, guarded database apply, and SQL, CSV, and JSON exports.

Run `just setup`, then `uv run seed --help` or `uv run seed init`. Set the configured connection environment variable and run `uv run seed inspect` to inspect a schema.

## Workflow

```bash
seed init
seed inspect
seed plan --table customers
seed preview --table customers --limit 5
seed validate --table customers --dataset
seed export --table customers --format json
seed apply --table customers --dry-run
```

Set the connection URL in the environment variable named in [the configuration](docs/DATA_MODEL.md#configuration). To write rows, configure an explicit development or test target and review `seed apply --dry-run` before `seed apply`. Export creates a new directory with a completion manifest. See the [import and sequence instructions](docs/SECURITY.md#sql-and-export-safety) before loading artifacts.

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
