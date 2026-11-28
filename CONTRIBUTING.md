# Contributing to Seed

Open an [issue](https://github.com/KiraQiez/Seed/issues) for a bug or feature. Include your Seed, Python, and PostgreSQL versions and a minimal schema or configuration with credentials removed. Use the [roadmap](docs/ROADMAP.md) for implementation status.

Base contributions on `staging` and open your pull request against that branch. Keep each change focused and update the relevant tests and documentation. Use a disposable development or test database for database changes.

```sh
just setup
just check
just test-integration
just test-e2e
```

The database suites use Docker Compose and manage their own PostgreSQL fixtures. See the [development guide](docs/DEVELOPMENT.md) for the test matrix and benchmark.
