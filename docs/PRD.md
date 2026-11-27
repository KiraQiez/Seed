# Product requirements

## Context and objectives

Development databases need enough representative data to exercise joins, test workflows, and demonstrate features. Maintained factories and hand-written inserts duplicate schema knowledge. Seed should turn database metadata and a small configuration into a predictable dataset, surface schema limits early, and make writing to the wrong target difficult.

| Persona | Story | Outcome |
|---|---|---|
| Backend or full-stack developer | I want to populate a newly migrated development database. | I can get a useful dataset from a connection and row counts without writing model factories. |
| QA engineer | I want to reproduce a test dataset across runs. | I can record a seed, configuration, reference timestamp, and tool version and reproduce supported synthetic values. |
| Database or data engineer | I want to know what Seed can generate before granting write access. | Read-only inspection and planning identify unsupported types, constraints, and dependencies. |
| Demo maintainer | I want a repeatable dataset to load on another machine. | SQL, CSV, and JSON exports preserve supported relationships without copying database contents. |

## MVP workflow

Inspect a PostgreSQL schema, select tables and counts, review the plan and data, then export or apply to a development or test database. [PostgreSQL support matrix](DATA_MODEL.md#postgresql-support)

For the e-commerce reference scenario, seed 1,000 customers, 500 products, 5,000 orders, 15,000 order items, and 5,000 payments. Customers and products precede their dependents. Orders precede order items and payments. Order items link orders and products. A compatible schema and configuration produce 26,500 rows; accounting totals, payment cardinality, and inventory workflows require an enforced supported constraint or a future explicit rule.

## Functional requirements

| ID | Requirement | Acceptance criteria |
|---|---|---|
| FR-001 | Configure and connect to PostgreSQL | A versioned config and one named environment variable resolve the connection; schema selection is explicit after defaults; a missing variable, timeout, or invalid credential produces a structured, redacted error. |
| FR-002 | Inspect and classify schema metadata | A fixture covering types, primary and foreign keys, unique and check constraints, identities, defaults, generated columns, and enums is classified by operation without modifying the database. |
| FR-003 | Resolve dependencies and build a plan | Selected tables resolve to a stable parent-first graph with effective counts, rules, generator selections, capability issues, and total rows. Missing parents and unsupported relationships receive actionable diagnostics. |
| FR-004 | Generate compatible synthetic data | For supported schemas, inference and explicit rules generate type-valid rows with correct lengths, precision, nullability, FK tuples, and uniqueness. Retries and capacity are bounded. |
| FR-005 | Preview records | Users can request samples from specific tables with a display limit, review the generator choices and plan, and see validation findings. The database and its sequences remain unchanged. |
| FR-006 | Validate configuration, plan, and dataset | Configuration or plan problems are distinguishable from dataset failures. Full offline validation streams all planned rows and reports supported constraint violations before export. Database enforcement remains authoritative during apply. |
| FR-007 | Apply safely | Confirm the authorized target and counts, refuse non-empty targets by default, and require explicit append/reuse settings. Inserts follow dependency order in one transaction, roll back on failure, and report counts after commit acknowledgment. |
| FR-008 | Export related data | SQL, CSV, and JSON preserve generated key relationships, include the information required to import the dataset, and leave existing files and the database intact. |
| FR-009 | Provide predictable CLI results | Commands publish documented human and machine-readable results, exit statuses, and issue codes. Automation can acknowledge confirmation per invocation while every safety gate still runs. |

## Non-functional requirements

| ID | Requirement | Acceptance criteria |
|---|---|---|
| NFR-001 | Deterministic generation | Repeated offline runs with identical relevant inputs and different supported batch sizes produce identical logical rows. Database-owned values and external state have documented reproducibility limits. |
| NFR-002 | Bounded resources | The reference fixture meets the release benchmark; tests exercise configured volume and batch limits, bounded retries, bounded parent pools, and streaming generation. |
| NFR-003 | Security and local execution | Tests show that credentials and server error details are redacted, read operations leave fixtures unchanged, and write safety holds under mismatched targets and concurrent writers. Generation performs no network I/O. |
| NFR-004 | Maintainable boundaries | Generation tests run without a database or terminal. Runtime dependencies have documented purposes and quality gates check formatting, linting, and types. |
| NFR-005 | Portability and distribution | The supported Python and PostgreSQL matrix is documented and verified. Clean macOS, Linux, and Windows environments pass the applicable installation smoke tests. |
| NFR-006 | Reliable failure and recovery | A failed batch rolls back prior inserts, unsupported objects are explicit, and lost commit acknowledgment has a distinct status with no success count or automatic replay. |

## Success measures and limits

- The documented workflow works end to end on the simple and e-commerce fixtures. On a disposable pre-migrated fixture, a first-time user should be able to inspect, preview, and begin a safe apply in under ten minutes. Validate this with a timed README walkthrough before release.
- The reference run commits all 26,500 rows with zero orphaned records and meets the elapsed time and memory targets. [Benchmark](DEVELOPMENT.md#benchmark)
- Release acceptance requires passing the safety and rollback scenarios with zero unintended target writes, credential disclosures, or false success reports. Local acceptance checks supply these measures without telemetry.
- Main risks are incomplete metadata reflection, PostgreSQL grant and lock requirements, sparse key domains, and sequence reconciliation after import. [Design decisions](ARCHITECTURE.md#decisions) · [Milestones](ROADMAP.md#milestones)

## Non-goals

The MVP is limited to PostgreSQL and a standalone CLI. Web UI, hosted services, accounts, cloud sync, AI generation, distributed execution, toolkit integration, generator plugins, complex cycles, business-rule inference, schema migration, destructive database operations, arbitrary configured SQL, production data anonymization, and replication are outside scope. MySQL, SQLite, and advanced generation rules are candidates for future releases.
