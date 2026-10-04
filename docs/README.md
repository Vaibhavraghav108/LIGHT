# LIGHT Documentation Map

This directory is LIGHT's maintained engineering knowledge base. Code and tests
remain the authority for behavior; these documents explain the verified
`v0.5.0` baseline and identify work that is partial, environment-dependent, or
planned.

## Source-of-truth map

| Question | Canonical document |
| --- | --- |
| What is LIGHT supposed to do? | [PRODUCT_SPEC.md](PRODUCT_SPEC.md) |
| How does the runtime work? | [ARCHITECTURE.md](ARCHITECTURE.md) |
| What exists, and how well is it verified? | [FEATURES.md](FEATURES.md) |
| What may never be weakened? | [SAFETY.md](SAFETY.md) |
| Why were major designs chosen? | [DECISIONS.md](DECISIONS.md) |
| How is the project tested? | [TESTING.md](TESTING.md) |
| What failed before, and how was it fixed? | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| What changed in each milestone? | [CHANGELOG.md](CHANGELOG.md) |
| What is complete or next? | [ROADMAP.md](ROADMAP.md) |
| How must contributors work? | [../AGENTS.md](../AGENTS.md) |
| How does a new user install and run it? | [../README.md](../README.md) |

## Document inventory

All maintained Markdown files are listed above. There are no archived or
duplicate design documents in the repository at `v0.5.0`. `logs/.gitkeep` only
preserves the runtime-log directory; actual logs, `.env`, browser profiles,
virtual environments, and scratch diagnostics are intentionally ignored and
are not historical sources of truth.

## Evidence labels

- **Implemented**: present in source and covered by automated tests.
- **Partial**: implemented, but important real-host, end-to-end, or failure
  behavior is not fully verified.
- **Experimental**: available but dependency- or environment-sensitive.
- **Planned**: roadmap intent; not implemented.
- **Not implemented**: explicitly absent from the current release.

An automated test with mocked OS calls is not physical-host validation. GitHub
Actions macOS coverage is not a claim that microphone, Accessibility, Screen
Recording, Retina, or multi-monitor behavior was exercised on a user's Mac.

## Maintenance rules

1. Update the smallest canonical document; link to it instead of duplicating
   detailed prose elsewhere.
2. Treat release counts and CI status as dated snapshots, not timeless facts.
3. Preserve historical ADRs and troubleshooting records. Mark superseded
   material rather than silently rewriting history.
4. Use repository-relative links. Do not commit machine-specific paths,
   credentials, runtime logs, or local `.env` files.
5. Verify feature claims against source and tests. State environmental limits
   explicitly.

Last consolidated against tag `v0.5.0` (`8524bde`) on 2026-10-04.
