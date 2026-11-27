# Data model

## Configuration

Seed reads UTF-8 `seed.toml` with `tomllib` and strict Pydantic validation. Require `version = 1` and `database.url_env`. Reject unknown fields, unsupported versions and generators, wrong types, or conflicting rules with a scoped diagnostic. Configuration is declarative. Add optional fields with stable defaults within v1. Breaking changes require a new version and upgrade guide.

| Field | Default and validation |
|---|---|
| `database.driver` | `postgresql`, the only supported driver |
| `database.url_env` | Required environment variable name matching `[A-Za-z_][A-Za-z0-9_]*`. Resolve the [PostgreSQL URL](SECURITY.md#connection-and-credentials) from the process environment. |
| `database.schema`, `database.connect_timeout` | `public` as an exact schema name, 5 seconds with range 2–60 |
| `generation.locale`, `generation.random_seed` | `en_US` or another supported Faker locale, seed `0` as an unsigned 64-bit integer |
| `generation.default_rows`, `generation.batch_size` | 100 rows with range 0–100,000, batch size 1,000 with range 1–10,000 |
| `generation.reference_time`, `generation.null_rate` | `2025-01-01T00:00:00Z` as an offset datetime normalized to UTC with a valid preceding 365-day window, finite null probability `0.05` in `[0, 1]` |
| `safety.environment`, `safety.allow_existing_data` | Unset, and `false`. Apply and its dry-run require `development` or `test`. |
| `safety.target` | When present, require `host` (one DNS name or IP), `port` (1–65,535), and exact `database` and `schema` names. Required for apply and its dry-run. |
| `tables.<name>.rows`, `tables.<name>.reuse_existing` | Effective default count, and `false`. Reuse requires explicit `rows = 0` and is live-only. |
| `rules.<table>.<column>` | Optional built-in generator rule or scalar null/uniqueness override |

CLI overrides take precedence over the TOML file, then built-in defaults. Read `--config PATH` or `./seed.toml`. Use repeatable `--table` to replace the initial selection from `[tables]`. With neither, select all ordinary user tables in the schema. Expand parents only for tables generating rows. Zero-row reused parents are terminal dependencies and require either eligible existing keys for live apply or an entirely null eligible edge. A CLI count override conflicting with reuse is invalid. Apply requires a positive total. Seed reads credentials only from the named environment variable.

TOML table and column keys are exact unqualified names. CLI `--table` accepts `table` or `schema.table` with exact case. Quote components containing dots or double quotes, and double embedded quotes. For example, `--table '"public"."Order.Items"'` selects the literal `Order.Items` in `public`.

### Generator rules

Use `generator` with `integer`, `decimal`, `boolean`, `text`, `date`, `datetime`, `uuid`, `choice`, `constant`, or one of the [named semantic generators](ARCHITECTURE.md#generation). Numeric rules accept inclusive `min` and `max` as integers or, for decimals, exact decimal strings. `choice` requires a nonempty `values` array with distinct converted scalars. `constant` requires one typed `value`. Use native TOML dates and datetimes, canonical UUID strings, and exact enum labels. Use `unique = true` to check uniqueness across generated rows. A per-column `null_rate` overrides the global rate on a nullable scalar. Omit `generator` to set only uniqueness or null behavior. Reject inapplicable parameters, incompatible values, and explicit rules on FK, identity, and generated columns.

Once `DATABASE_URL` is set outside the file, this example selects an existing `public.customers` table. The safety block pins a local development target.

```toml
version = 1

[database]
url_env = "DATABASE_URL"
schema = "public"

[generation]
random_seed = 42
locale = "en_US"

[safety]
environment = "development"

[safety.target]
host = "127.0.0.1"
port = 5432
database = "seed_dev"
schema = "public"

[tables.customers]
rows = 1000

[rules.customers.email]
generator = "email"
unique = true
```

For live-only parent reuse, set `rows = 0` and `reuse_existing = true` under that parent’s tables entry. If a table receiving rows is non-empty, also set `safety.allow_existing_data = true`. See [apply safety](SECURITY.md#apply-safety).

## PostgreSQL support

The planned PostgreSQL 15–19 classifications are **MVP**, **Partial**, **Detected only**, and **Future**. Inspect reports each feature's classification. Plan blocks the affected mode when required metadata cannot be verified. Unrelated tables do not block a selection.

| Feature | Status | Planned boundary |
|---|---|---|
| Relations | Partial | Generate from ordinary, non-inherited tables in one schema. Detect other schemas, views, materialized views, partitions, inheritance, and foreign tables. Reject unsupported kinds as targets or required parents. |
| Scalars | MVP | Support integers, boolean, text/varchar, date, timestamp/timestamptz, UUID, and declared enums. Enforce character lengths, timestamp precision, and exact enum labels. Reject NUL in text. |
| Numeric and other types | Partial | Support finite numeric/decimal with `0 <= scale <= precision` where declared. Detect and reject writable arrays, domains, JSON/JSONB, floating-point, binary, `char`, `citext`, and other unsupported types. |
| Primary and unique keys | Partial | Support ordinary non-deferrable single and composite keys and B-tree unique indexes with known equality and deterministic collation. Respect both nulls-distinct modes. Block exclusion, partial, expression, invalid, or specialized uniqueness. |
| Foreign keys | Partial | Support validated, non-deferrable `MATCH SIMPLE` tuples within the schema, including junctions and unique FKs. Reject cycles, self references, overlapping members, incompatible key types, cross-schema links, and unavailable server-produced key sources. |
| Checks | Partial | Support validated comparisons between one writable integer/decimal column and finite literals, including conjunctions, reversed comparisons, and known exact numeric casts. Intersect representable bounds and preserve NULL behavior. Block other expressions without evaluating their SQL. |
| Defaults and identities | Partial | Classify defaults without publishing expression bodies. Generate explicit ordinary values. Delegate supported key identities and unambiguously owned serial sequences to PostgreSQL in live mode. Offline IDs require ascending increment-one, noncycling sequences and IDs in range. |
| Generated columns | Partial | Omit stored columns outside constraints and relationships. Reject other generated-column cases. Use live `INSERT DEFAULT VALUES` when all values are server-supplied. Positive offline plans need at least one output column per table. |
| Triggers, rules, RLS | Detected only | Reject enabled user triggers or rewrite rules on generated tables and RLS on write targets or required parents. Ordinary PostgreSQL integrity triggers remain active. |
| Other engines and advanced rules | Future | Additional engines, advanced dependency handling, and business rules require separate requirements. |

## Schema, plans, and records

The core uses typed models. Ordered collections serialize as arrays. `?` marks an optional field. An issue names the affected scope without containing candidate values.

| Model | Fields and invariants |
|---|---|
| `TableId`, `Target` | `TableId` carries exact `schema` and `table` strings. `Target` carries `host`, integer `port`, `database`, and `schema`. |
| `DatabaseSchema` | `target`, integer `server_major`, names of visible `schemas`, ordered `tables`, and a structural `fingerprint`. |
| `TableSchema`, `ColumnSchema` | Table identity, relation kind, ordered columns, optional primary key, FK/unique/check lists, features, and issues. Columns carry name, ordinal, type, nullability, default kind, and optional identity/generated kind. Types carry relevant modifiers, collation, enum labels, and precision. |
| Keys and checks | Keys carry a name and ordered columns. FKs add the parent table and ordered referenced columns with equal arity, match mode, validation and deferrability flags, and referential actions. Uniques add their source and null semantics. Checks carry validation flags, capability, and normalized typed bounds where recognized. |
| `GenerationPlan` | `target`, `schema_fingerprint`, effective settings, `total_rows`, and ordered table plans. Each table gives identity, requested flag, rows, parents, key source, and ordered live/offline bindings. Each mode reports its executable flag and issues. |
| `GeneratedRecord` | `table`, zero-based `ordinal`, and ordered column `values`. Values are null, bool, int, string, Decimal, date, datetime, or UUID. Absent columns are omitted from writes. |
| `ValidationIssue` | String `code` and `message`, `severity` of `warning` or `error`, and optional `scope` with table, column, constraint, config path, or ordinal. |
| `ValidationResult` | `status` of `passed`, `failed`, or `skipped`, `issues`, and optional integer `rows_checked`. |
| `InsertionResult` | `outcome` of `committed`, `rolled_back`, `not_started`, or `unknown`. Include per-table counts only after acknowledged commit. |
| `ExportResult` | `format`, `directory`, `manifest`, relative artifact paths, and per-table counts. Return after manifest publication. |

Fingerprint canonical structural metadata with SHA-256 over ordered UTF-8 JSON. Exclude credentials, endpoint, catalog object IDs, and raw database expressions from the public fingerprint. Compare catalog identities and a private digest of relevant definitions during the live recheck. See the [CLI envelope](CLI_SPEC.md#json-contract).

## Dataset serialization

Preview and JSON table entries use `{table, columns, rows}`. Columns are ordered `{name, type}` descriptors and rows contain positional arrays in that order. Omit server-computed columns. Encode numeric/decimal values and bigint as decimal strings, other integers as JSON numbers, booleans as JSON booleans, and null as `null`. Use ISO 8601 dates and timestamps (UTC for aware values, no offset for naive ones) and canonical lowercase UUIDs.

`dataset.json` uses `{version: 1, tables: [...]}`. Every export has a `manifest.json` with `version`, `format`, `schema_fingerprint`, and ordered entries containing `table`, `columns`, `rows`, and relative `file`. SQL entries share `dataset.sql`, JSON entries share `dataset.json`, and CSV uses `table-0001.csv` onward in plan order. Record planned zero-row output tables. The manifest excludes connection details. See [SQL and export safety](SECURITY.md#sql-and-export-safety) for CSV nulls and import semantics.
