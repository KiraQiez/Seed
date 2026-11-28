# CLI specification

Help, version, `init`, `inspect`, `plan`, `preview`, `validate`, `apply`, and `export` are available. `seed --help` lists the commands, `seed COMMAND --help` shows supported options, and `seed --version` prints the package version. Place command options after the subcommand. Commands take no positional arguments. Help and version are plain text informational requests.

## Commands

| Command | Specific options | Result |
|---|---|---|
| `seed init` | `--interactive` | Create a starter configuration with no embedded credentials. Publish the complete file exclusively on filesystems that support hard links. An existing regular file yields `created: false`; directories and symlinks yield a file error. |
| `seed inspect` | `--schema NAME`, repeatable `--table NAME` | Show tables, columns, types, PKs, FKs, defaults and constraints, and their capability classifications. The terminal summary shows schema and table counts. Use `--table` for the selected table's columns and constraints or `--verbose` for full details on stderr. Inspect filters the display without expanding parents. Its fingerprint describes the selected schema before display filtering. |
| `seed plan` | Selection and generation overrides | Report requested and required tables, counts, key sources, dependency order, generators, operation-specific compatibility, and warnings. |
| `seed preview` | Selection and generation overrides, `--limit N` | Generate an offline sample and show its plan and validation issues. Show up to `N` rows per explicitly selected table, default 5 and allowed range 1–100. Parents needed for sampled descendants generate their full key pools. Output still respects the sample limit. |
| `seed validate` | Selection and generation overrides, `--dataset` | Check the configuration and selected schema for generation compatibility. `--dataset` also generates and validates the entire offline dataset in batches, discards rows, and reports counts and issues for each stage. |
| `seed apply` | Selection and generation overrides, `--dry-run`, `--yes` | Preflight the live plan, request confirmation for a real write, and report committed counts. Dry-run stops after the read-only preflight. Combining `--dry-run` with `--yes` is a usage error. |
| `seed export` | Selection and generation overrides, required `--format sql\|csv\|json`, `--output DIR` | Write the selected offline format to a new directory under an existing parent, `./seed-export` by default, and report its artifact inventory. |

Guided setup asks for a schema and one or more table row counts. It defaults to `public` and 10 rows per table within the total row limit. It creates a config only after input is complete. New sessions need terminal stdin and stderr. Use `--interactive` separately from `--json`. An existing regular config is preserved without prompts.

All commands accept `--config PATH` (default `./seed.toml`), `--json`, and `--verbose`. Selection and generation overrides are `--schema`, repeatable `--table`, `--rows`, `--random-seed`, and `--locale`. `--rows` requires exactly one `--table`. Verbose diagnostics go to stderr. Previewed rows are a prefix of the equivalent export for that table. Live apply uses actual returned server keys. [Configuration precedence and name syntax](DATA_MODEL.md#configuration)

`inspect` succeeds when it can classify metadata, even when it finds unsupported features. `plan` and base `validate` report issues by affected mode and fail when both live and offline generation are blocked. A blocked `plan` returns status 4 with the partial plan in `data.plan`, and its issues identify the affected mode. Planning reads schema metadata in a read-only transaction. `preview`, dataset validation, and `export` require a usable offline plan. Apply and its dry-run require a usable live plan. Model all three validation stages as `passed`, `failed`, or `skipped` with distinct diagnostics.

In `validate --dataset`, a live-only plan passes the plan stage and fails the offline dataset stage. `rows_checked` counts rows in successfully received batches, so a failed batch contributes zero rows. An issue can identify the failing row by its table-local ordinal. Preview shows a bounded sample. Full validation can find problems beyond that sample.

## Confirmation and output channels

Apply prints the configured target host, port, database, schema, write tables, parent source choices, and counts to stderr before prompting or acting on `--yes`. An interactive prompt requires terminal stdin and stderr, uses a default of no, and accepts `y` or `yes` case-insensitively. EOF, decline, and non-interactive operation without `--yes` refuse the operation. JSON automation can use `apply --yes --json`; target checks, plan checks, and lock checks still apply. Follow the [write contract](SECURITY.md#apply-safety).

By default stdout carries results, and stderr carries prompts, progress, diagnostics, and errors. When `--json` is recognized on a valid command, stdout contains one UTF-8 JSON document followed by a newline. Informational help/version requests and parser errors before a command can be resolved follow the CLI framework's text conventions. Machine consumers route by issue code and exit status. Database errors, connection strings, and values used in failed inserts stay out of CLI diagnostics.

## JSON contract

| Field | Type | Meaning |
|---|---|---|
| `version` | integer | Response contract version, initially `1` |
| `command` | string | Resolved command name |
| `ok` | boolean | True when the exit status is `0` |
| `data` | object or null | Command result or safe partial result, such as a blocked plan |
| `issues` | object array | Stable `code`, `severity`, `message`, and optional `scope`. [Issue model](DATA_MODEL.md#schema-plans-and-records) |

Use the following `data` payloads. Their component fields and typed values are defined in the [data model](DATA_MODEL.md).

| Command | Data |
|---|---|
| `init` | `{path, created}` |
| `inspect` | `{schema}` with normalized and safely serialized metadata |
| `plan` | `{plan}` |
| `preview` | `{plan, tables}` with ordered sample datasets |
| `validate` | `{config, plan, dataset}` stage results |
| `apply` | `{dry_run, plan, insertion}`. Dry-run returns `insertion: null`. Real runs include the outcome, and only acknowledged commits include `counts` with `{table, rows}` entries. |
| `export` | `{export}` with `format`, `directory`, `manifest`, relative `artifacts`, and per-table `counts`. Failure returns null data |

## Exit status

| Status | Meaning | Representative issue codes |
|---|---|---|
| `0` | Requested operation completed | Warnings can be present |
| `2` | Usage or configuration error | `USAGE_ERROR`, `CONFIG_INVALID` |
| `3` | Connection or authentication error before writing | `CONNECTION_FAILED`, `CONNECTION_TIMEOUT` |
| `4` | Schema, plan, generator, or dataset rejected | `SCHEMA_UNAVAILABLE`, `TABLE_UNAVAILABLE`, `UNSUPPORTED_CONSTRAINT`, `DEPENDENCY_CYCLE`, `RETRY_EXHAUSTED` |
| `5` | Safety refusal or declined confirmation | `TARGET_MISMATCH`, `TARGET_NOT_EMPTY`, `LOCK_UNAVAILABLE`, `CONFIRMATION_REQUIRED`, `CANCELLED`, `NO_ROWS_PLANNED` |
| `6` | Execution, file, or commit outcome error | `INSERT_FAILED`, `COMMIT_OUTCOME_UNKNOWN`, `OUTPUT_EXISTS`, `EXPORT_FAILED`, `INIT_FAILED` |
| `130` | Interrupted with a known pre-commit outcome | `INTERRUPTED` |

An interrupted or failed commit with unknown outcome uses `6`. After an acknowledged commit, the outcome is `committed` even if rendering subsequently fails. If an error occurs after a write starts, report the known outcome without exposing input values. Record additional specific issue codes alongside their introducing feature.

## Example interactions

```console
$ seed preview --table customers --limit 1
public.customers · 1 of 100 rows
  email
  alex-4vj2@example.com
$ seed apply --yes --json
{"version":1,"command":"apply","ok":false,"data":{"dry_run":false,"plan":null,"insertion":{"outcome":"not_started"}},"issues":[{"code":"TARGET_MISMATCH","severity":"error","message":"Connected database does not match the configured write target."}]}
```

The JSON example exits with status `5`. The preview's exact displayed columns and generated values depend on the inspected table and configuration.
