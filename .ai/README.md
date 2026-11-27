# AI development guide

This directory defines how agents work on Seed. Start at [AGENTS.md](../AGENTS.md) and use the [documentation index](../README.md#documentation) for technical contracts.

## Required reading order

1. Read [AGENTS.md](../AGENTS.md), then this guide.
2. Read the [engineering rules](RULES.md) and [implementation workflow](WORKFLOW.md).
3. Find the requested task in the [roadmap](../docs/ROADMAP.md#implementation-checklist) and read the applicable [checklist](CHECKLIST.md).
4. Read the technical references for the current task and follow additional references when their contracts affect the work.

## Task-based reading matrix

| Task | Technical references |
|---|---|
| Product or scope | [PRD](../docs/PRD.md), [roadmap](../docs/ROADMAP.md), [decisions](../docs/ARCHITECTURE.md#decisions) |
| CLI and output | [CLI specification](../docs/CLI_SPEC.md), [architecture](../docs/ARCHITECTURE.md), [data model](../docs/DATA_MODEL.md) |
| Configuration | [Configuration](../docs/DATA_MODEL.md#configuration), [security](../docs/SECURITY.md) |
| Connectivity and reflection | [PostgreSQL support](../docs/DATA_MODEL.md#postgresql-support), [security](../docs/SECURITY.md) |
| Dependency planning and generation | [Architecture](../docs/ARCHITECTURE.md#generation), [data model](../docs/DATA_MODEL.md) |
| Insertion and export | [Security](../docs/SECURITY.md), [data model](../docs/DATA_MODEL.md) |
| Testing | [Development guide](../docs/DEVELOPMENT.md) and the contract under test |
| Packaging and release | [Release](../docs/RELEASE.md), [quality gates](../docs/DEVELOPMENT.md#tooling-and-quality-gates) |

## Selection and ownership

Work on the requested task. When asked to select one, choose the earliest eligible phase and the highest priority unchecked task with verified dependencies, using task ID to break ties. The roadmap records task status and evidence.

Resolve changes to contracts, safety policy, approved scope, or acceptance criteria with the maintainer. Follow mandatory database safety and use the canonical spec for routine choices. Update the owning document when verified behavior changes, and record material [design decisions](../docs/ARCHITECTURE.md#decisions).
