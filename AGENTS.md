# Agent instructions for Seed

Seed is a standalone, schema-aware PostgreSQL seeder for development and testing. The roadmap records verified work and dependencies. Check the task scope before starting the next phase.

## Read in order

1. [AI index](./.ai/README.md) for topic ownership and the task-specific reading matrix.
2. [Engineering rules](./.ai/RULES.md) and [implementation workflow](./.ai/WORKFLOW.md).
3. The relevant task in the [roadmap](docs/ROADMAP.md#implementation-checklist) and the [verification checklists](./.ai/CHECKLIST.md).
4. Use the [documentation index](README.md#documentation) to find the task's technical contracts. Read [database safety](docs/SECURITY.md) before connectivity, data access, insertion, or SQL export work.

## Execution and verification

- Inspect existing work and dependencies before editing. Work within the requested task and its acceptance criteria. Raise material product or architecture conflicts with the maintainer and record approved [design decisions](docs/ARCHITECTURE.md#decisions).
- Use only dedicated development or test databases. Only `apply` may insert data and every write must pass the configured safety checks. Protect credentials, bind SQL values, safely quote identifiers, preserve constraints, and keep data mutations within the documented transaction. Automated tests use isolated fixtures.
- Run the applicable tests and quality checks. Update affected canonical documentation and the task status. Report actual results and any gaps in verification.
