# Release strategy

## Naming, licence, and versions

Treat Seed, the executable, import package, and distribution names as provisional. Before the first public tag, verify PyPI and GitHub availability, platform collisions, and Homebrew formula and tap names. Approve Apache-2.0 or record the chosen licence and include it in the source and distributions. Update examples, artifacts, and [ADR-017](ARCHITECTURE.md#decisions).

Use SemVer. Start with approved `0.x` releases, publish pre-release candidates when compatibility or packaging needs wider validation, and call out breaking changes even during `0.x`. Treat configuration and JSON contract versions separately from package versions. Promote to `1.0.0` when the documented interfaces and support matrix are ready to be maintained as stable contracts.

## Build and validation

1. Review the [release checklist](../ai/CHECKLIST.md#before-release), run the full tests and benchmarks, and review the support matrix and limitations.
2. Update the changelog with features, fixes, security changes, compatibility notes, and relevant upgrades. Ensure the package version, changelog, and intended Git tag agree.
3. Build the wheel and source distribution with `uv build` using Hatchling. Inspect included files, package metadata, dependency declarations, licence, and entry point. Build a wheel from the sdist to verify a complete source artifact.
4. Run a clean wheel install and the [smoke tests](DEVELOPMENT.md#tooling-and-quality-gates) on supported platforms. Record versions, results, and artifact hashes.

## Distribution

- **GitHub Releases.** Create a versioned release from an approved tag, attach the verified wheel and sdist and their SHA-256 checksums, and include changelog highlights, availability, and known limits.
- **PyPI.** Configure Trusted Publishing for the exact repository, workflow, and protected environment. Grant OIDC token permission only to the publish job. Test with TestPyPI where useful and publish the same artifacts validated in CI. Verify artifact hashes and a clean install from the index after publishing. [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
- **Homebrew.** Use a maintainer-owned tap after name and dependency verification. Pin the formula to a release artifact and checksum, and verify it with tap install and executable smoke tests. Homebrew Core submission is outside this rollout. [Homebrew taps](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap)

Once published, document installation with `pipx install <distribution>` or `uv tool install <distribution>`, plus `brew install <owner>/<tap>/<formula>` once the tap is available. Replace placeholders with verified names before publishing user-facing installation instructions. Verify Linux and macOS tap behavior where supported, and use Python installation instructions for Windows.

For a bad release, record the affected version and provide recovery instructions. Yank a broken PyPI release where appropriate and issue a corrected version with fresh artifacts. Keep tags, changelog, and release notes aligned.
