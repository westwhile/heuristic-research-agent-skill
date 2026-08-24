# Source provenance and rights boundary

- Status: `OSS-R0 / APACHE-2.0_SELECTED / RIGHTS_CONFIRMED / UNKNOWN_ZERO`
- Baseline commit: `b9a3b8268575fe32399b83295595710944c6a772`
- Review date: 2026-08-24
- Machine-readable source: [`SOURCE_PROVENANCE.json`](SOURCE_PROVENANCE.json)

This record defines the source and redistribution boundary for the repository's
Apache-2.0 implementation. It is not evidence of real scientific capability,
external adoption, Skill installation, a package release, or acceptance into an
OpenAI program.

## Rights confirmation

The maintainer `westwhile` confirmed ownership of, or authorization to license,
all files tracked at the baseline commit and repository-native work performed
under the maintainer's direction, including the two O6 application-evidence
files, thirteen Phase 6 L1 manifest files, two Phase 6 L2 runner files, three
Phase 6 L3 runner/selection files, and nine Phase 6 L4 study/case/matrix/report
files merged to `main` by PR #21, plus eleven Phase 6 R1 observation
schema/source/test/fixture files merged by PR #23, eleven Phase 6 R2
checkpoint-recovery schema/source/script/test/fixture files merged by PR #25,
eleven Phase 6 R3 same-host-reproducibility files merged by PR #26, and eleven
Phase 6 R4 controlled-interruption schema/source/script/test/fixture files
merged by PR #28, and twenty-three Phase 6 R5 portability-receipt/report
schema/source/script/test/fixture files merged by PR #30, plus thirty-eight
Phase 6 R6A external-trial protocol schema/source/script/test/fixture/governance
files merged by PR #32, under Apache-2.0. This confirmation does not extend to
excluded external payloads and does not waive obligations that accompany any
third-party material added later.

The same repository-native rule covers the twenty-nine Phase 7 P7A
candidate/closure/context schema, source, test, fixture, and ADR files prepared
under maintainer direction and merged by PR #34; no external payload or
third-party expression is added by P7A.

Repository-native material may have been drafted, reviewed, or mechanically
generated with AI or automation under maintainer direction. The maintainer is
responsible for the final form, source review, and rights decision. Tool or AI
assistance never supplies permission to copy third-party expression.

## Inventory

The Phase 7 P7A mainline inventory at merge commit
`9305d17c8abaf857774a4fdcd736312f4553bce0` contains 1007 files. Its tree
`7254d74546cb6134abaaf0dc5865f2c4f53ee84c` equals the exact PR #34 head tree
that passed the dual-interpreter archive suite, clean-install/demo, local CUDA
compatibility, and PR/main CI gates. R6B remains frozen at
`TARGET_FROZEN / ZERO_EXTERNAL_SUBMISSIONS`; P7A synthetic fixtures are not
external-source, semantic-review, adoption, installation, or publication
evidence:

| Source class | Count | Boundary |
|---|---:|---|
| `independently_authored` | 874 | Repository-native material covered by the maintainer confirmation |
| `generated` | 118 | Deterministic baseline, benchmark, report, and research-memory outputs |
| `design_inspired` | 13 | Independently implemented v8 compatibility code/tests and synthetic fixtures |
| `third_party_reused` | 2 | Canonical Apache-2.0 license text and adapted Contributor Covenant 3.0 text |
| `unknown` | 0 | No unresolved tracked file |

The machine-readable rules are ordered and use first-match precedence, so the
generated and design-inspired exceptions take priority over repository-wide
authorship rules. `scripts/verify_source_provenance.py` fails if any proposed
tracked file is uncovered, any count drifts, or `unknown` becomes non-zero.

The CR1 implementation proposal adds one independently authored private Core
scanner and otherwise modifies already covered repository-native paths. Its
working-tree inventory is 1008 files: 875 `independently_authored`, 118
`generated`, 13 `design_inspired`, 2 `third_party_reused`, and 0 `unknown`.
These proposal counts are not a claim that CR1 has merged to `main`.

## External-source decisions

### Canonical Apache-2.0 license text

`LICENSE` is the standard Apache License, Version 2.0 text, not project-authored
expression. It was obtained through GitHub's license API and compared
byte-for-byte after newline normalization. The text remains verbatim; the
project-specific identification is kept separately in `NOTICE`.

### Contributor Covenant 3.0

`CODE_OF_CONDUCT.md` adapts Contributor Covenant, version 3.0, under CC BY-SA
4.0. It retains the upstream attribution and license link, identifies that the
text was adapted, and replaces upstream reporting notes with project-specific
procedures. The attribution is also repeated in `NOTICE`.

### Citation File Format 1.2.0

`CITATION.cff` contains independently authored project metadata conforming to
the public CFF 1.2.0 schema. No CFF specification text or example payload is
vendored; the schema and repository are recorded as a non-vendored reference.

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

Hatchling and PyYAML are non-vendored MIT-licensed dependencies. PyTorch is a
caller-managed, non-vendored optional runtime: the project source describes its
license as BSD-style, while current official package metadata records the
complete installed distribution's composite SPDX expression. No PyTorch wheel,
CUDA payload, source, LICENSE, NOTICE, model, or fixture is redistributed by
this repository. The CI workflow
references commit-pinned MIT-licensed `actions/checkout` and
`actions/setup-python`; their source is not vendored. JSON Schema Draft 2020-12
is referenced by dialect URI and vocabulary only. These references do not add
third-party source payloads to this distribution.

The Codex for Open Source plan and O6 public evidence drafts link to OpenAI's
official project page, application form, and Program Terms. The repository
records independently written factual summaries of the live pages checked on
2026-08-23; it does not vendor or copy page or terms text. The live sources must
be checked again before any application submission.

## Change rule

Every PR that adds or changes an external source, generated artifact family,
compatibility fixture, template, substantial quotation, or vendored dependency
must update both provenance files. Unknown or unlicensed inputs fail closed:
exclude them, obtain compatible permission, or replace them with independently
authored material before distribution.

`LICENSE`, `NOTICE`, provenance clearance, package release, Git Tag/Release,
Skill installation, and external-program application remain distinct actions
with separate evidence and authorization gates.
