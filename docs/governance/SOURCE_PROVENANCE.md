# Source provenance and rights boundary

- Status: `OSS-R0 / APACHE-2.0_SELECTED / RIGHTS_CONFIRMED / UNKNOWN_ZERO`
- Baseline commit: `bd53d195344df3a1457e6185b0f5968444b81a35`
- Review date: 2026-08-23
- Machine-readable source: [`SOURCE_PROVENANCE.json`](SOURCE_PROVENANCE.json)

This record defines the source and redistribution boundary for the repository's
Apache-2.0 implementation. It is not evidence of real scientific capability,
external adoption, Skill installation, a package release, or acceptance into an
OpenAI program.

## Rights confirmation

The maintainer `westwhile` confirmed ownership of, or authorization to license,
all files tracked at the baseline commit and the PR-A implementation files under
Apache-2.0. This confirmation does not extend to excluded external payloads and
does not waive obligations that accompany any third-party material added later.

Repository-native material may have been drafted, reviewed, or mechanically
generated with AI or automation under maintainer direction. The maintainer is
responsible for the final form, source review, and rights decision. Tool or AI
assistance never supplies permission to copy third-party expression.

## Inventory

The proposed PR-A tree contains 828 files:

| Source class | Count | Boundary |
|---|---:|---|
| `independently_authored` | 696 | Repository-native material covered by the maintainer confirmation |
| `generated` | 118 | Deterministic baseline, benchmark, report, and research-memory outputs |
| `design_inspired` | 13 | Independently implemented v8 compatibility code/tests and synthetic fixtures |
| `third_party_reused` | 1 | Canonical Apache-2.0 license text only |
| `unknown` | 0 | No unresolved tracked file |

The machine-readable rules are ordered and use first-match precedence, so the
generated and design-inspired exceptions take priority over repository-wide
authorship rules. `scripts/verify_source_provenance.py` fails if any proposed
tracked file is uncovered, any count drifts, or `unknown` becomes non-zero.

## External-source decisions

### Canonical Apache-2.0 license text

`LICENSE` is the standard Apache License, Version 2.0 text, not project-authored
expression. It was obtained through GitHub's license API and compared
byte-for-byte after newline normalization. The text remains verbatim; the
project-specific identification is kept separately in `NOTICE`.

### math-research-solve v8 / 1.0.0–1.0.1

The repository distributes generated manifests, hashes, environment and
acceptance facts, plus an independently implemented synthetic compatibility
fixture. It does not distribute the external installed or portable Skill
payload. Its source URL and payload license are not recorded, so the payload
remains excluded and the published v8/1.0.1 baseline remains immutable.

### Pika toolkit 1.11 / math-research-solve v13

The original user-provided artifact was unavailable during OSS-R0 and no
compatible license was established. The previous detailed mechanism plan was
therefore replaced by a short, independently written source-boundary note. No
Pika/v13 source, schema, fixture, template, payload, or detailed descriptive
expression is distributed. Future evaluation requires a newly registered
artifact, license decision, and separate implementation authorization.

### Referenced dependencies and services

Hatchling and PyYAML are non-vendored MIT-licensed dependencies. The CI workflow
references commit-pinned MIT-licensed `actions/checkout` and
`actions/setup-python`; their source is not vendored. JSON Schema Draft 2020-12
is referenced by dialect URI and vocabulary only. These references do not add
third-party source payloads to this distribution.

## Change rule

Every PR that adds or changes an external source, generated artifact family,
compatibility fixture, template, substantial quotation, or vendored dependency
must update both provenance files. Unknown or unlicensed inputs fail closed:
exclude them, obtain compatible permission, or replace them with independently
authored material before distribution.

`LICENSE`, `NOTICE`, provenance clearance, package release, Git Tag/Release,
Skill installation, and external-program application remain distinct actions
with separate evidence and authorization gates.
