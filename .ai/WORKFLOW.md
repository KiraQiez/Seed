# Implementation workflow

## Before implementation

1. Read [AGENTS.md](../AGENTS.md), the [AI index](README.md), and the [rules](RULES.md).
2. Inspect the repository, requested task, existing behavior, and acceptance criteria. Confirm that its dependencies are verified.
3. Follow the relevant technical links from the [roadmap](../docs/ROADMAP.md) and [reading matrix](README.md#task-based-reading-matrix). Identify database safety implications and verification checks.
4. Outline the implementation and checks. Obtain maintainer approval at roadmap gates, for material architecture or safety changes, and before public release. Record approved [design decisions](../docs/ARCHITECTURE.md#decisions).

## During implementation

Implement the approved task and test changed behavior through its normal entry points. Keep its roadmap checkbox open and record any work in progress or blockers with the task.

## After implementation

1. Run the relevant tests and quality gates. Check each acceptance criterion and the [verification checklists](CHECKLIST.md).
2. Review database safety, data compatibility, and error handling. Update affected documentation.
3. Check off the task in the roadmap after verification passes. Record the commands, results, and unresolved limitations with the task and in the handoff.

Return the result for review at the task boundary. Follow-on tasks require their own scope and verified dependencies.
