# Verification checklists

Use the applicable checklist for each task. Record the command or other evidence for completed checks. Leave unexecuted checks open and explain any verification gaps in the task report.

## Before implementation

- [ ] Requirements and acceptance criteria are understood.
- [ ] Task dependencies are satisfied and the scope is approved.
- [ ] Relevant canonical documents and existing behavior are reviewed.
- [ ] Work boundaries and compatibility implications are identified.
- [ ] Database safety implications and test isolation are understood.

## Before task completion

- [ ] Acceptance criteria and intended architecture are satisfied.
- [ ] Relevant tests are added or updated and have passed.
- [ ] Applicable Ruff lint and format checks have passed.
- [ ] Applicable Mypy checks have passed.
- [ ] Database safety requirements are verified and credentials remain protected.
- [ ] Changes stay within task scope and affected documentation is current.
- [ ] Task status reflects actual evidence and known limitations are reported.

## Before release

- [ ] Full test suite and PostgreSQL integration and end-to-end gates have passed.
- [ ] Security review is complete and performance benchmark results are reviewed.
- [ ] Package builds and isolated installation smoke tests are verified.
- [ ] Version, changelog, licence, and distribution names are confirmed.
- [ ] User documentation and known limitations are current.
- [ ] Artifacts, checksums, and release workflow are verified and publication is authorized.
