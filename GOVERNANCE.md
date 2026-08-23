# Project governance

## Scope and current roles

This is a maintainer-led project. `westwhile` is the current primary maintainer
and release authority. Contributors propose changes; reviewers evaluate scope,
contracts, provenance, tests, and claim boundaries. A bot-authored review or a
maintainer's own pull request is engineering activity, not independent external
adoption.

No foundation, steering committee, employer, or multi-maintainer quorum is
claimed. If maintainership changes, this file and `CITATION.cff` must be updated
in a reviewed pull request.

## Decisions

- Routine changes are decided through public issues and pull requests.
- Core interfaces, authority boundaries, schema compatibility, privacy/export,
  publication, promotion, and support policy changes require an ADR.
- Published schemas evolve by successor version; existing released schema bytes
  and semantics are not changed in place.
- The maintainer has final merge and release responsibility, but cannot waive
  license, provenance, required-check, security, or evidence-boundary Gates.

Private vulnerability and conduct reports are handled outside public issues.
Only the minimum non-sensitive outcome needed to protect users is published.

## Review and merge

Pull requests should be small enough to audit and use the repository template.
Review checks the proposed diff, tests, generated evidence, source rights,
rollback, and non-entailments. All required CI checks must pass against the exact
head. Merge commits preserve the reviewed branch identity unless an explicitly
documented exception is approved.

Self-review can establish internal engineering acceptance when no other
maintainer exists; it must not be described as independent community review.
External contributors retain credit for accepted contributions.

## Releases and support

The machine-readable [support matrix](docs/governance/SUPPORT_MATRIX.json) is the
authority for required OS/Python lanes. A Tag, GitHub Release, PyPI publication,
or Skill installation is a separate action and requires its own Gate. Version
metadata on `main` may be an unreleased candidate and must not be presented as a
published package.

Release history is summarized in [CHANGELOG.md](CHANGELOG.md); immutable Tags,
release assets, checksums, and detailed acceptance reports remain the primary
evidence. Deprecation or removal of a public contract requires a migration path,
tests, documentation, and an ADR when architectural authority changes.

## Changes to governance

Governance changes use the same pull-request, provenance, and required-check
process as code. Material changes must explain their effect on contributors,
security reporters, release authority, and existing contracts.
