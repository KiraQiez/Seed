# Engineering rules

1. Use Python 3.12 or newer within the supported version matrix.
2. Follow PEP 8 and the repository formatter.
3. Use descriptive names.
4. Type public functions and interfaces.
5. Prefer simple functions and composition.
6. Give each module a clear responsibility.
7. Separate CLI presentation from business logic.
8. Separate synthetic generation from database insertion.
9. Use structured exceptions and issues.
10. Classify unsupported constraints explicitly and refuse affected operations as specified.
11. Keep database safety checks mandatory on every apply path.
12. Keep credentials and sensitive values out of diagnostics and artifacts.
13. Bind SQL data values through the database API.
14. Quote database identifiers through supported SQL composition APIs.
15. Enforce explicit generation retry limits.
16. Stream batches and bound retained state according to the generation contract.
17. Preserve deterministic behavior where the contract promises it.
18. Make transaction boundaries and outcomes explicit.
19. Write or update tests for new behavior.
20. Keep canonical documentation consistent with the implementation.
21. Keep refactoring within the approved task.
22. Add dependencies only with a clear approved purpose.
23. Implement approved features and scope only.
24. Report only actual test and check results.
25. Mark completion only after verification.
26. Use dedicated development or test databases. Never use production for development or automated testing.
27. Surface conflicting requirements for resolution.
28. Prefer backward-compatible changes.
29. Document breaking changes and migration implications.
30. Keep Seed independently installable and runnable.

Prioritize correctness, simplicity, security, and maintainability. The [security specification](../docs/SECURITY.md) supplies mandatory database safety details. The [workflow](WORKFLOW.md) defines verification and reporting.
