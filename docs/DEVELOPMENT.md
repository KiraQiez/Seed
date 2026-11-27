# Development guide

## Tooling and quality gates

Use uv for the locked contributor environment, Hatchling for wheels and source distributions, pytest for tests, Ruff for linting and formatting, Mypy for typing, Just for recipes, and GitHub Actions for CI. Keep development tools out of the runtime package. Record runtime versions that affect deterministic data during releases.

Run `just setup` to sync the lockfile. Run `just check` for lock consistency, lint, formatting, types, and unit tests, and `just build` to build a wheel and sdist.

| Check | Command |
|---|---|
| Lint and format | `uv run ruff check .` and `uv run ruff format --check .` |
| Types | `uv run mypy src tests` |
| Unit | `uv run pytest tests/unit` |
| PostgreSQL integration | `just test-integration` |
| Installed database CLI workflows | Planned `just test-e2e` |
| Build and smoke test | `uv build`, then install the wheel in isolation and run `seed --version`, `seed --help`, and `seed init` |

Linux CI exercises Python 3.12–3.15 and PostgreSQL 15–19 on current supported patch releases. Run full end-to-end checks on minimum and latest combinations. macOS and Windows run portable checks, builds, and clean installation smoke tests. Review platform-specific driver requirements and upstream support before each release. [Python version status](https://devguide.python.org/versions/) · [PostgreSQL version policy](https://www.postgresql.org/support/versioning/)

## Test structure and fixtures

Use `tests/unit/` for pure models, config, dependency graphs, generators, serialization, and redaction. Use `tests/integration/` for real metadata, driver behavior, transactions and concurrency. Use `tests/e2e/` for the installed CLI, statuses, and output. Both database suites use a unique, loopback-only Compose project with generated credentials and owned teardown. Fail closed if fixture identity is unclear. Never fall back to an application `DATABASE_URL`.

Inspection tests use PostgreSQL 17 by default. Set `SEED_TEST_POSTGRES_MAJOR` to a supported major from 15 through 19 for a local run. The recipe requires a running local Docker daemon and Compose.

Keep simple users, e-commerce, tickets, junction tables, composite parent keys, cycles, and unsupported features in `tests/fixtures/`. Include quoted identifiers, nullable keys, unsupported constraints, ordinary and specialized indexes, and distinct source and empty import schemas.

| Acceptance area | Required evidence |
|---|---|
| Read-only and reproducibility | Inspect, plan, preview, both validation modes, and exports leave source rows, metadata, and sequences unchanged. Offline rows are stable across repeat runs and batch sizes. Preview matches the corresponding export prefix. |
| Supported constraints | Valid composite tuples, mixed nullability, both unique-null modes, one-to-one capacity, and numeric bounds. Unsupported constraints and exhausted domains produce scoped and bounded failures. |
| Apply safety | Exercise credential redaction, spoofed or mismatched targets, missing grants, confirmation, non-interactive refusals, lock contention, inserts during confirmation, object replacement, guarded append, and disappearing reused parents. |
| Recovery | A late insert failure rolls back earlier batches, while sequence gaps are tracked separately. Test interruption and unknown commit acknowledgement without success counts or automatic replay. |
| Exports | Round-trip SQL and CSV against a matching empty schema. Validate JSON types and key references. Test explicit identities, sequence reconciliation followed by a normal insert, quoting, null and empty text, multiline fields, path collisions, and incomplete outputs. |

Drive additional checks from the [roadmap](ROADMAP.md#implementation-checklist) and [security contract](SECURITY.md). Record actual evidence with completed tasks.

## Benchmark

Use the [26,500-row e-commerce fixture](PRD.md#mvp-workflow) with identity parents, an enum, composite unique key, and simple numeric checks. Use an idle Linux runner with 4 vCPUs, 8 GiB RAM, Python 3.12, and local Docker PostgreSQL 16. Record patches and dependency versions, reset the schema each run, and use locale `en_US`, seed `42`, the default reference time, and batches of 1,000.

Measure apply and offline JSON export separately over three trials, from CLI startup to success. Target at most **60 seconds median** and **256 MiB peak CLI RSS** per path, with all 26,500 rows and zero broken references. Record the highest sampled RSS. Measure append separately and record lock time and collision-probe cost. These are proposed gates until benchmark measurements are available.
