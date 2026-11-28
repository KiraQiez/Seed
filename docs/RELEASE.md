# Release strategy

## Naming, licence, and versions

The project is Seed. The executable and Python import are both `seed`, the PyPI distribution is `seed-dev-db`, and the Homebrew formula is `KiraQiez/tap/seed`. Seed is licensed under Apache-2.0. Copyright 2026 KiraQiez. [Licence](../LICENSE)

Use SemVer tags such as `v0.1.0`. Match the tag to the CLI version, changelog, and versioned release notes. The configuration and JSON contract have their own versions.

## Release checklist

1. Push the candidate to `staging`. Check the Quality and Release workflows, including the database suites, reference benchmark, package metadata, hashes, clean installs, and temporary Homebrew tap. Promote the verified commit to `main` and wait for its quality checks.
2. For the first release, recheck the [PyPI project name](https://pypi.org/project/seed-dev-db/) and register a pending publisher for `KiraQiez/Seed`, workflow `release.yml`, and environment `pypi`. Restrict the GitHub environment to release tags and require maintainer review. [PyPI publisher setup](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
3. Push the matching tag from the verified `main` commit. Review the protected deployment after the release checks pass. The pipeline publishes the same tested wheel and source distribution to PyPI and attaches both files, release notes, and `SHA256SUMS` to the GitHub Release.
4. Download the public files from both channels and compare their SHA-256 hashes with the release manifest. Install the exact version with uv and pipx in isolated environments and run `seed --version`, `seed --help`, and `seed init`.
5. Render the Homebrew formula against the verified PyPI source URL and checksum. Publish it to [the maintainer tap](https://github.com/KiraQiez/homebrew-tap) after the candidate checks pass on Apple Silicon, Intel macOS, and Linux x86-64. Confirm `brew install KiraQiez/tap/seed` and `brew test KiraQiez/tap/seed`.
6. Record the release, install checks, and any pending channels in the [roadmap](ROADMAP.md).

For a bad package release, document recovery steps and yank the affected PyPI version where appropriate. Publish corrected artifacts under a new version and update the tap to match.
