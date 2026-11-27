# Roadmap and implementation checklist

Phase 1 starts after approval of the planning package. A task is eligible after its dependencies are complete.

## Milestones

| Phase | Tasks | Exit criteria |
|---|---|---|
| [1. Project foundation](#phase-1-project-foundation) | SEED-101–SEED-105 | Installable package, starter configuration, and passing local quality gates. [Development guide](DEVELOPMENT.md) |
| [2. Connectivity and schema inspection](#phase-2-connectivity-and-schema-inspection) | SEED-201–SEED-205 | Read-only metadata and capabilities verified against disposable PostgreSQL fixtures. [Support matrix](DATA_MODEL.md#postgresql-support) |
| [3. Dependency resolution and planning](#phase-3-dependency-resolution-and-planning) | SEED-301–SEED-304 | Stable plan for the reference schema, with selected counts, dependencies, and compatibility. [Execution flow](ARCHITECTURE.md#execution-flow) |
| [4. Data generation](#phase-4-data-generation) | SEED-401–SEED-405 | Deterministic typed values, relational keys, and bounded batches from the core. [Generation](ARCHITECTURE.md#generation) |
| [5. Preview and validation](#phase-5-preview-and-validation) | SEED-501–SEED-503 | Read-only samples and staged validation with stable errors and JSON. [CLI](CLI_SPEC.md) |
| [6. Safe database insertion](#phase-6-safe-database-insertion) | SEED-601–SEED-605 | Confirmed and locked apply, guarded append, and verified rollback under failure and concurrency. [Apply safety](SECURITY.md#apply-safety) |
| [7. Export](#phase-7-export) | SEED-701–SEED-704 | Relational SQL, CSV, and JSON files with fresh-schema round trips and sequence checks. [Export safety](SECURITY.md#sql-and-export-safety) |
| [8. Production readiness](#phase-8-production-readiness) | SEED-801–SEED-804 | Full suites, cross-platform installs, security review, and reference benchmarks pass. [Benchmarks](DEVELOPMENT.md#benchmark) |
| [9. Release](#phase-9-release) | SEED-901–SEED-905 | Approved names, licence, and verified artifacts available through the planned channels. [Release guide](RELEASE.md) |

## Implementation checklist

P0 marks core, safety, or release gates. P1 marks other required MVP work. Requirement IDs are defined in the [PRD](PRD.md#functional-requirements). Check off a task only after its acceptance criteria and relevant [quality gates](DEVELOPMENT.md#tooling-and-quality-gates) pass. Record the command and outcome with the completed task.

### Phase 1 Project foundation

- [x] **SEED-101 · Scaffold the Python package** · P0
  - **Dependencies** None · **Requirements** `NFR-004`, `NFR-005`
  - Create the minimal functional `src` package, version metadata, Hatchling build configuration and uv lockfile. **Verify.** Build a wheel and sdist with `uv build`. Install the wheel in isolation and import the versioned package.
  - **Verified.** Built the wheel and sdist with `uv build` and imported version 0.1.0 from a clean Python 3.15 wheel install.
- [x] **SEED-102 · Establish CLI and terminal rendering** · P1
  - **Dependencies** `SEED-101` · **Requirements** `FR-009`, `NFR-004`
  - Add the provisional `seed` entry point and Typer/Rich boundary with help, version, and separate result and diagnostic streams. **Verify.** `uv run seed --help` and `uv run seed --version` succeed. CLI parser tests cover invalid invocation and captured streams.
  - **Verified.** Installed help and version worked. Sixteen unit cases passed on Python 3.15, including parser and output-channel checks.
- [x] **SEED-103 · Validate versioned TOML** · P0
  - **Dependencies** `SEED-101` · **Requirements** `FR-001`, `FR-006`, `NFR-003`
  - Implement the TOML loader and Pydantic models with defaults, strict fields, override inputs, and sanitized issues. **Verify.** `uv run pytest tests/unit` covers the documented examples, unsupported versions, unknown keys, incompatible rule parameters, and absent credentials.
  - **Verified.** Thirteen unit cases passed on Python 3.15, including the documented example, override validation, missing credentials, and redaction.
- [ ] **SEED-104 · Add idempotent initialization** · P1
  - **Dependencies** `SEED-102`, `SEED-103` · **Requirements** `FR-001`, `FR-009`
  - Add `init` with a validated starter file and exclusive creation. **Verify.** Run `uv run pytest tests/unit`. Repeated `init` leaves original bytes intact and handles an existing symlink or directory safely.
- [ ] **SEED-105 · Establish developer quality gates** · P0
  - **Dependencies** `SEED-102`, `SEED-103` · **Requirements** `NFR-004`, `NFR-005`
  - Configure pytest, Ruff, Mypy, Just, and GitHub Actions for lint, typing, unit tests, and builds. **Verify.** Run the documented direct quality commands and their Just equivalents. CI exercises the planned Python matrix with no database required.

### Phase 2 Connectivity and schema inspection

- [ ] **SEED-201 · Provision disposable PostgreSQL test fixtures** · P0
  - **Dependencies** `SEED-105` · **Requirements** `NFR-003`, `NFR-005`
  - Add isolated Compose and pytest fixtures with generated credentials, loopback access, and owned teardown. **Verify.** `just test-integration` starts and cleans up its own database. Exercise each planned major and verify fixture failure closes safely.
- [ ] **SEED-202 · Resolve and connect to PostgreSQL** · P0
  - **Dependencies** `SEED-103`, `SEED-201` · **Requirements** `FR-001`, `NFR-003`
  - Parse the configured URL, enforce endpoint and TLS rules, implement timeouts and read-only sessions, and map connection errors to redacted issues. **Verify.** `just test-integration` checks the selected database and read-only state. Unit tests reject unsupported URL options and ensure both output modes redact secrets.
- [ ] **SEED-203 · Reflect and normalize schema metadata** · P1
  - **Dependencies** `SEED-202` · **Requirements** `FR-002`, `NFR-004`
  - Add normalized models and SQLAlchemy Core reflection for columns, types, constraints, and keys, including ordered composite metadata. **Verify.** `just test-integration` compares enum, key tuple, nullability, and type metadata with fixtures. Serialization and fingerprint ordering are stable.
- [ ] **SEED-204 · Classify PostgreSQL-specific capabilities** · P0
  - **Dependencies** `SEED-203` · **Requirements** `FR-002`, `NFR-003`
  - Supplement reflection with catalog features, make structural and live fingerprints, and implement the support matrix including trusted numeric shape recognition. **Verify.** `just test-integration` distinguishes ordinary and specialized constraints, sequence ownership, generated columns, triggers, and missing metadata on supported majors.
- [ ] **SEED-205 · Expose read-only schema inspection** · P1
  - **Dependencies** `SEED-102`, `SEED-204` · **Requirements** `FR-002`, `FR-009`
  - Implement `inspect` rendering and safe serialized schema output, with display filtering. **Verify.** `just test-integration` verifies read-only inspection and correct classifications. CLI tests compare `inspect --json` with the versioned envelope.

### Phase 3 Dependency resolution and planning

- [ ] **SEED-301 · Resolve table selections and row counts** · P1
  - **Dependencies** `SEED-103`, `SEED-203` · **Requirements** `FR-003`
  - Resolve exact table names, schema-qualified CLI input, configured selections, and effective counts. **Verify.** `uv run pytest tests/unit` covers precedence, quoting, wrong qualifiers, zero rows, and unknown tables.
- [ ] **SEED-302 · Analyze dependency graphs** · P0
  - **Dependencies** `SEED-204`, `SEED-301` · **Requirements** `FR-003`
  - Expand required parents and compute stable parent-first ordering with issues for missing or unsupported edges. **Verify.** `uv run pytest tests/unit` covers multi-parent junctions, composite edges, filtered selection, missing parents, self references, and cycles.
- [ ] **SEED-303 · Build generation plans** · P1
  - **Dependencies** `SEED-302` · **Requirements** `FR-003`, `FR-006`, `NFR-002`
  - Build typed plans with effective settings, table counts, planned bindings, mode-specific key sources, and issues. **Verify.** `uv run pytest tests/unit` checks stable plans, an estimated 26,500-row total for the reference fixture, row limits, and mode-specific rejection.
- [ ] **SEED-304 · Expose the plan command** · P1
  - **Dependencies** `SEED-205`, `SEED-303` · **Requirements** `FR-003`, `FR-009`
  - Render the plan, including dependency counts, bindings, and warnings, in terminal and JSON. **Verify.** `just test-integration` exercises a valid plan and a blocked plan. Confirm read-only execution and documented statuses and outputs.

### Phase 4 Data generation

- [ ] **SEED-401 · Establish deterministic streaming** · P0
  - **Dependencies** `SEED-303` · **Requirements** `FR-004`, `NFR-001`, `NFR-002`
  - Implement run context, seeded streams, ordered row and batch interfaces, and retry budgets. **Verify.** `uv run pytest tests/unit` proves stable draw order across batch sizes and bounded attempts without global random state.
- [ ] **SEED-402 · Generate generic typed values** · P1
  - **Dependencies** `SEED-401` · **Requirements** `FR-004`, `NFR-001`
  - Add scalar generators for supported types, enum labels, exact numeric bounds and precision, temporal types, UUIDs, and nullable values. **Verify.** `uv run pytest tests/unit` covers scalar types, boundaries, exact decimal rounding cases, UTC/reference handling, and typed nullability.
- [ ] **SEED-403 · Resolve semantic inference and explicit rules** · P1
  - **Dependencies** `SEED-402` · **Requirements** `FR-004`, `NFR-001`, `NFR-003`
  - Connect Faker and the built-in registry to explicit and inferred bindings, including reserved synthetic contact details. **Verify.** `uv run pytest tests/unit` checks precedence, locale compatibility, typing, reserved contact values, short columns, and fallback or refusal.
- [ ] **SEED-404 · Generate offline keys and relationships** · P0
  - **Dependencies** `SEED-302`, `SEED-402` · **Requirements** `FR-004`, `FR-008`, `NFR-001`
  - Add explicit offline identity allocation, FK tuple pools, row correlation inputs, and nullable edge handling. **Verify.** `uv run pytest tests/unit` covers owned keys, UUID and string parents, composite tuple matching, depleted and nullable parents, and junction records.
- [ ] **SEED-405 · Enforce supported record constraints** · P0
  - **Dependencies** `SEED-403`, `SEED-404` · **Requirements** `FR-004`, `FR-006`, `NFR-002`
  - Validate generated rows against required values, checks, key membership, and supported uniqueness. Reserve accepted tuples and report bounded exhaustion. **Verify.** `uv run pytest tests/unit` covers numeric conjunctions, impossible ranges, composite uniqueness, `NULLS NOT DISTINCT`, and unique FK capacity.

### Phase 5 Preview and validation

- [ ] **SEED-501 · Add staged validation** · P0
  - **Dependencies** `SEED-304`, `SEED-405` · **Requirements** `FR-006`, `FR-009`
  - Expose `validate` with subordinate configuration, plan, and dataset stages. Stream full offline validation when requested. **Verify.** `just test-integration` distinguishes stage failures and skipped stages. Full validation counts rows without inserting or retaining the dataset.
- [ ] **SEED-502 · Add preview** · P1
  - **Dependencies** `SEED-501` · **Requirements** `FR-005`, `NFR-001`
  - Expose plans and per-table sample rows, with display limits and necessary parent pool generation. **Verify.** `just test-integration` checks sample limit and selection, repeatability, and unchanged rows and sequences.
- [ ] **SEED-503 · Verify machine-readable command contracts** · P1
  - **Dependencies** `SEED-501`, `SEED-502` · **Requirements** `FR-009`, `NFR-003`
  - Cover the versioned response, exit statuses, diagnostics placement, and redaction across implemented commands. **Verify.** `uv run pytest tests/unit` parses JSON output and checks success, blocked plans, error envelope shape, and sensitive value removal.

### Phase 6 Safe database insertion

- [ ] **SEED-601 · Implement apply preflight and confirmation** · P0
  - **Dependencies** `SEED-503` · **Requirements** `FR-007`, `FR-009`, `NFR-003`
  - Add target verification, existence probes, target summary, dry-run, and per-invocation confirmation handling. **Verify.** `just test-integration` checks environment and target mismatches, non-empty refusals, and unchanged state after dry-run. CLI tests cover TTY, decline, EOF, and `--yes`.
- [ ] **SEED-602 · Lock targets and recheck approved plans** · P0
  - **Dependencies** `SEED-601` · **Requirements** `FR-007`, `NFR-003`
  - Implement strict lock acquisition, timeout, role checks, and post-confirmation checks of schema and table state. **Verify.** `just test-integration` uses two connections to verify write blocking, changed state, missing permissions, timeout, and safe refusal before insertion.
- [ ] **SEED-603 · Insert batches and report transaction outcomes** · P0
  - **Dependencies** `SEED-602`, `SEED-405` · **Requirements** `FR-007`, `NFR-006`
  - Add ordered parameterized inserts, live identity capture, one transaction, rollback, and outcome reporting. **Verify.** `just test-integration` checks live parent keys and rollback of earlier batches. Simulate unknown commit acknowledgement and confirm counts and replay are suppressed.
- [ ] **SEED-604 · Implement guarded append and parent reuse** · P0
  - **Dependencies** `SEED-603` · **Requirements** `FR-004`, `FR-007`, `NFR-002`, `NFR-003`
  - Add bounded existing key pools and indexed, typed collision probes under the apply transaction. **Verify.** `just test-integration` verifies independently opted-in append and reuse, null comparison, bounded lookups, and rollback when a reused key disappears.
- [ ] **SEED-605 · Expose the complete apply workflow** · P0
  - **Dependencies** `SEED-604` · **Requirements** `FR-007`, `FR-009`, `NFR-006`
  - Wire the apply CLI to preflight, confirmation, guarded execution, and safe result rendering. **Verify.** `just test-e2e` covers successful empty-target apply, confirmed append, non-interactive invocation, refusal, and failure with no misleading row counts.

### Phase 7 Export

- [ ] **SEED-701 · Publish exports safely** · P0
  - **Dependencies** `SEED-501` · **Requirements** `FR-008`, `NFR-003`, `NFR-006`
  - Add export directory creation, sanitized paths, manifest publication, and owned cleanup. **Verify.** `uv run pytest tests/unit` covers existing destination, symlink, incomplete output, failed writes, and manifest publication after artifacts close.
- [ ] **SEED-702 · Serialize CSV and JSON datasets** · P1
  - **Dependencies** `SEED-701` · **Requirements** `FR-008`, `NFR-001`
  - Stream per-table CSV and the versioned JSON dataset using typed values and stable columns. **Verify.** `uv run pytest tests/unit` checks exact CSV null and multiline handling, JSON decimal and bigint precision, and FK tuple references.
- [ ] **SEED-703 · Serialize PostgreSQL SQL datasets** · P0
  - **Dependencies** `SEED-701`, `SEED-404` · **Requirements** `FR-008`, `NFR-003`
  - Stream transactional INSERT statements with safely typed literals, exact identifiers, and explicit generated-always IDs. **Verify.** `just test-integration` loads a matching empty fixture and checks identities, relationships, quote-heavy values, and absence of destructive statements.
- [ ] **SEED-704 · Wire export and verify round trips** · P0
  - **Dependencies** `SEED-702`, `SEED-703` · **Requirements** `FR-008`, `FR-009`, `NFR-006`
  - Add `export` format dispatch and artifact output, plus round-trip checks for SQL and CSV and JSON relational validation. **Verify.** `just test-e2e` verifies all three formats, preview-to-export prefixes, sequence reconciliation and follow-up inserts, and source database immutability.

### Phase 8 Production readiness

- [ ] **SEED-801 · Verify integrated CLI acceptance** · P0
  - **Dependencies** `SEED-605`, `SEED-704` · **Requirements** `FR-005`, `FR-006`, `FR-007`, `FR-008`, `FR-009`, `NFR-006`
  - Complete the installed CLI suite and CI coverage for the supported PostgreSQL majors. **Verify.** Run `just test-integration` and `just test-e2e` on the documented matrix. Verify counts, errors, and non-mutation properties.
- [ ] **SEED-802 · Benchmark the reference dataset** · P0
  - **Dependencies** `SEED-801` · **Requirements** `NFR-001`, `NFR-002`
  - Provide a repeatable benchmark fixture and procedure for apply, JSON export, and append measurement. **Verify.** Run the documented three-trial procedure, verify all 26,500 rows and references, and report measured time, peak RSS, and append behavior.
- [ ] **SEED-803 · Verify portability and package installation** · P0
  - **Dependencies** `SEED-801` · **Requirements** `NFR-004`, `NFR-005`
  - Exercise builds, interpreter versions, and clean installation smoke checks on Linux, macOS, and Windows. **Verify.** `uv build` succeeds, the sdist rebuilds, and the documented `--version`, `--help`, and `init` checks pass from installed wheels.
- [ ] **SEED-804 · Complete security and documentation review** · P0
  - **Dependencies** `SEED-801`, `SEED-802`, `SEED-803` · **Requirements** `NFR-003`, `NFR-006`
  - Walk through the README and review configuration, redaction, SQL boundaries, lock requirements, and supported capabilities. **Verify.** Record the walkthrough, test evidence, benchmark results, and resolved or approved risks. Verify documentation examples against the released interfaces.

### Phase 9 Release

- [ ] **SEED-901 · Resolve distribution names and licence** · P0
  - **Dependencies** `SEED-804` · **Requirements** `NFR-005`
  - Verify product, executable, import, distribution, and tap names and finalize the licence decision. **Verify.** Record the maintainer-approved choices and evidence of naming checks. Ensure metadata and documentation match and include the approved licence.
- [ ] **SEED-902 · Prepare release and contributor material** · P1
  - **Dependencies** `SEED-901` · **Requirements** `NFR-004`, `NFR-005`
  - Add the changelog, versioned release notes, installation guidance, and open-source contribution instructions. **Verify.** Review version/tag correspondence, installation steps, the contribution workflow, and documented limits.
- [ ] **SEED-903 · Validate release automation** · P0
  - **Dependencies** `SEED-902` · **Requirements** `NFR-005`, `NFR-006`
  - Prepare the protected GitHub Actions build and PyPI Trusted Publishing workflow with artifact hashes and scoped permission. **Verify.** Run a staged release, with TestPyPI if approved. Verify that tested packages match the intended artifacts and that the publish job alone can request its OIDC token.
- [ ] **SEED-904 · Publish the approved release** · P0
  - **Dependencies** `SEED-903` · **Requirements** `NFR-005`
  - After release authorization, create the tag and GitHub Release and publish corresponding artifacts to PyPI. **Verify.** Compare published hashes and install the published version in a clean environment. Verify executable version, help, and config initialization.
- [ ] **SEED-905 · Release the Homebrew tap** · P1
  - **Dependencies** `SEED-904` · **Requirements** `NFR-005`
  - Author and publish the approved maintainer-owned tap formula tied to an artifact checksum. **Verify.** Test tap installation and run the documented CLI smoke checks on supported Homebrew platforms.

## Future direction

Review PostgreSQL capability gaps after the MVP. Additional engines, advanced relationship rules, generator plugins, and anonymization require separate planning.
