# Security and database safety

## Threat model

Protect against wrong-target writes, races with other writers, credential disclosure, untrusted SQL, and overwriting exports. Use dedicated development or test databases and scoped roles. Seed cannot reliably identify production or verify what lies behind every DNS name or proxy. The operator controls the network boundary and trusts the target schema and its database-defined code.

## Connection and credentials

- Read the connection only from the variable named in config. Accept `postgresql://` or `postgresql+psycopg://` for one explicit TCP endpoint, with username, password, host, database, and optional port (default 5432). Reject socket paths, multi-host URLs, indirection, connection-affecting environment overrides, and URL parameters other than `sslmode` and `sslrootcert`. Apply the configured connection timeout.
- Verify remote TLS with `verify-full`. Permit and default to `disable` only on literal loopback addresses. Normalize host spelling and verify the configured logical endpoint, active database, and exact schema before writes.
- Allowlist diagnostic fields. Omit usernames, credentials, DSNs, query parameters, raw database exceptions, bound values, and raw schema expressions. Escape terminal controls in displayed metadata. Seed’s generation is local, with no telemetry or hosted generation. Read operations use qualified identifiers and read-only `REPEATABLE READ` transactions.

## Apply safety

1. In read-only preflight, require `development` or `test`, a matching independently configured host, port, database, and schema, a positive supported live plan, and `session_replication_role = origin`. Check target emptiness. Only `safety.allow_existing_data = true` permits appending. Reusing parent keys separately requires `reuse_existing = true` and `rows = 0`.
2. Show the target, table counts, and reused parents before confirmation. `--yes` skips the prompt only. `--dry-run` ends after preflight. Close the preflight transaction before prompting, keep the same connection, and require a new run if it is lost. See the [CLI confirmation rules](CLI_SPEC.md#confirmation-and-output-channels).
3. After approval, open one `READ COMMITTED` write transaction. Acquire `SHARE ROW EXCLUSIVE` locks on write tables and `ACCESS SHARE` on reused parents, in stable qualified-name order. Use a five-second lock timeout and 60-second statement timeout. Recheck identity, schema, plan, emptiness and parent pools before the first insert. Refuse on a changed plan, failed lock, or incomplete metadata.
4. Insert parameterized batches in dependency order and retain locks through commit. Query only bounded, ordered key tuples from opted-in parents. If a reused parent changes, let FK enforcement reject stale keys and roll back. Preserve existing rows, schema and constraints. Use no upserts, deletes, truncation, DDL, or constraint overrides.
5. Report counts only after commit acknowledgement. Roll back on pre-commit failures. Report a lost commit acknowledgement as unknown with no counts and inspect the target before retrying. Never replay automatically. Database-owned sequences may advance on rollback. [PostgreSQL sequence behavior](https://www.postgresql.org/docs/15/functions-sequence.html)

Use scoped connection, schema, read, insert, and sequence privileges. Strict write locks also require table-scoped `UPDATE` on PostgreSQL 15–16 or `MAINTAIN` on 17+. Reused parents need `SELECT`. Scope extra grants to the write tables and account for possible lock contention. [PostgreSQL 15 lock permissions](https://www.postgresql.org/docs/15/sql-lock.html) · [PostgreSQL 17 lock permissions](https://www.postgresql.org/docs/17/sql-lock.html)

## SQL and export safety

- Qualify and safely quote identifiers. Bind live values. Export SQL uses fixed transaction and INSERT templates, PostgreSQL-compatible typed literals, UTF-8, standard string settings, and `OVERRIDING SYSTEM VALUE` where required. Exports contain synthetic data and exclude existing parent keys, schema changes, and sequence maintenance. [Psycopg composition](https://www.psycopg.org/psycopg3/docs/api/sql.html) · [PostgreSQL INSERT](https://www.postgresql.org/docs/15/sql-insert.html)
- Create a fresh, exclusive output directory with restrictive permissions where available. Refuse an existing path or symlink. Use generated filenames and publish the completion manifest with a same-directory atomic rename after validating and closing data files. Clean up only files owned by the run on recoverable failure. A missing manifest indicates incomplete output.
- CSV uses UTF-8, commas, headers, LF record separators, and manifest column order. Quote non-null values, double internal quotes, and preserve quoted newlines. An unquoted empty field is null and `""` is empty text. Import as text in spreadsheets to avoid formula evaluation. [PostgreSQL COPY](https://www.postgresql.org/docs/15/sql-copy.html)
- Import into a matching empty development or test schema. Run SQL with `psql -X -v ON_ERROR_STOP=1` and apply CSV files in manifest order in one transaction. JSON consumers use the specified types and explicit keys. An authorized operator advances each owned sequence above its current allocation and the highest stored ID before enabling later writers. A separately executed import runs outside Seed's live target checks.
