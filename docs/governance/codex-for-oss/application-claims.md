# Codex for Open Source application claims

- Status: `PREPARATION_ONLY / O5_WAITING_FOR_EXTERNAL_PARTICIPANTS`
- Evidence snapshot: 2026-08-23 06:37:42 UTC
- Public evidence: [`application-evidence.json`](application-evidence.json)
- Submission: `NOT_AUTHORIZED / NOT_READY`

This is a public, non-confidential preparation artifact. It does not constitute
an application, an acceptance decision, or external-adoption evidence. OpenAI
Organization ID, ChatGPT account details, private correspondence, unconsented
participant identities, and final form captures must remain outside the public
repository.

## O5 pause marker

The maintainer decided on 2026-08-23 to select and invite external participants
later. The public trial protocol and feedback form remain available, but the
current counts are zero participants, zero qualifying attempts, zero genuine
findings, and zero feedback-driven changes. O5 therefore remains
`WAITING_FOR_EXTERNAL_PARTICIPANTS / NO_EXTERNAL_RESULTS_YET`.

This pause does not prevent preparation of public O6 facts and drafts. It does
prevent marking O5 complete, claiming adoption, or treating the recommended
application Gate as satisfied.

## Current official conditions

The current official [program page](https://developers.openai.com/community/codex-for-oss)
invites core maintainers or maintainers of widely used public projects to apply,
and says projects with another important ecosystem role may explain that role.
It describes API credits, six months of ChatGPT Pro with Codex, and conditional
Codex Security access; none is guaranteed.

The current [Program Terms](https://learn.chatgpt.com/docs/codex-for-oss-terms)
require a valid ChatGPT account and accurate information about the applicant,
repository, and maintainer role. OpenAI may verify identity, repository
affiliation, maintainer status, permissions, or control. Submission does not
guarantee selection, funding, credits, or access. Submitting an application or
accepting a benefit agrees to the Program Terms.

The official [application form](https://openai.com/form/codex-for-oss/) was last
verified on 2026-08-23. A same-day non-interactive recheck reached an anti-bot
challenge rather than the form body, so every field, character limit, review
statement, and agreement must be rechecked in an interactive browser immediately
before submission. The three drafts below use the last verified 500-character
limits but are not frozen form answers.

## Dated repository snapshot

| Fact | Snapshot | Evidence and boundary |
|---|---:|---|
| Visibility / license | public / Apache-2.0 | [repository](https://github.com/westwhile/heuristic-research-agent-skill), `LICENSE`, `NOTICE`; public is not by itself adoption |
| Default branch | `main` at `b9a3b8268575fe32399b83295595710944c6a772` | [PR #19](https://github.com/westwhile/heuristic-research-agent-skill/pull/19) merge commit |
| Releases / tags | 7 / 8 | latest is [`v0.6.1`](https://github.com/westwhile/heuristic-research-agent-skill/releases/tag/v0.6.1) |
| CI | 4/4 required jobs succeeded | [main push run 32622282409](https://github.com/westwhile/heuristic-research-agent-skill/actions/runs/32622282409); engineering evidence only |
| Stars / forks | 1 / 0 | dated signal only, not a qualifying trial |
| Issues | 0 total | no feedback record exists yet |
| Pull requests | 19 total, 19 merged | maintainer activity, not independent adoption |
| Contributors | 1 authenticated maintainer account; 0 independent external contributors | the extra anonymous Git attribution is under the same maintainer name and is not a second person |
| Release asset downloads | six assets, 1 each | maintainer checksum verification; not external adoption |
| O5 trial | 0 participants, 0 attempts, 0 findings, 0 feedback-driven changes | `WAITING_FOR_EXTERNAL_PARTICIPANTS` |

## Draft 1: why the repository qualifies

Character count: **402 / 500**.

```text
heuristic-research-agent-skill is an Apache-2.0, audit-first toolkit for evidence governance, evaluation, and controlled evolution in research agents. It has seven public releases, reproducible Windows/Ubuntu CI across Python 3.12/3.14, an unknown-zero source inventory, and a synthetic Quick Start. It is early-stage: external trials are pending, and current evidence supports engineering claims only.
```

| Draft sentence | Evidence |
|---|---|
| Apache-2.0, audit-first toolkit | `LICENSE`, `NOTICE`, [`SOURCE_PROVENANCE.json`](../SOURCE_PROVENANCE.json), [research claim governance](../RESEARCH_CLAIM_GOVERNANCE.md) |
| Seven public releases | [GitHub Releases](https://github.com/westwhile/heuristic-research-agent-skill/releases); dated snapshot only |
| Windows/Ubuntu and Python 3.12/3.14 CI | [`SUPPORT_MATRIX.json`](../SUPPORT_MATRIX.json), [run 32622282409](https://github.com/westwhile/heuristic-research-agent-skill/actions/runs/32622282409) |
| Unknown-zero inventory | [`SOURCE_PROVENANCE.json`](../SOURCE_PROVENANCE.json) and `scripts/verify_source_provenance.py` |
| Synthetic Quick Start | [`README.md`](../../../README.md#五分钟-quick-start); it is not real research evidence |
| Early-stage and trials pending | [`EXTERNAL_TRIAL_PROTOCOL.md`](../EXTERNAL_TRIAL_PROTOCOL.md); all O5 counts remain zero |

## Draft 2: how API credits would be used

Character count: **425 / 500**.

```text
We would use API credits for bounded OSS maintenance: independent PR review, adversarial and mutation test generation, issue triage, documentation updates, clean-archive release verification, and security/provenance scans. Runs would be commit-bound and human-reviewed. Credits would not auto-approve changes, auto-promote Skills, process restricted data, make trading decisions, or turn synthetic tests into research claims.
```

| Draft sentence | Evidence or control |
|---|---|
| Bounded maintenance uses | [application plan](../../plans/CODEX_FOR_OSS_APPLICATION_PLAN.md#6-建议的-credits-使用方案) budget and deliverable table |
| Commit-bound, human-reviewed runs | [`GOVERNANCE.md`](../../../GOVERNANCE.md), [Git release process](../GIT_RELEASE_PROCESS.md) |
| No self-approval or automatic Skill promotion | [`PERMISSION_MATRIX.md`](../PERMISSION_MATRIX.md), [`AGENTS.md`](../../../AGENTS.md) |
| No restricted data or trading decisions | [`SECURITY.md`](../../../SECURITY.md), [`CONTRIBUTING.md`](../../../CONTRIBUTING.md) |
| Synthetic evidence remains engineering-only | [claim governance](../RESEARCH_CLAIM_GOVERNANCE.md), [`README.md`](../../../README.md) |

## Draft 3: anything else

Character count: **379 / 500**.

```text
The repository publishes an Apache-2.0 license, provenance manifest, support matrix, source-install demo, governance policies, and checksum-bound release evidence. The demo is synthetic; the project has no real ML executor, real research validation, packaged Skill, or production deployment. A 2-4 week external Quick Start trial is open, but no external results are claimed yet.
```

| Draft sentence | Evidence |
|---|---|
| Public governance and release artifacts | `LICENSE`, `NOTICE`, [`SOURCE_PROVENANCE.json`](../SOURCE_PROVENANCE.json), [`SUPPORT_MATRIX.json`](../SUPPORT_MATRIX.json), [`GOVERNANCE.md`](../../../GOVERNANCE.md), [`v0.6.1`](https://github.com/westwhile/heuristic-research-agent-skill/releases/tag/v0.6.1) |
| Capability exclusions | [`README.md`](../../../README.md), [project implementation plan](../../plans/PROJECT_IMPLEMENTATION_PLAN.md) |
| External trial is open with no results | [`EXTERNAL_TRIAL_PROTOCOL.md`](../EXTERNAL_TRIAL_PROTOCOL.md), [feedback form](https://github.com/westwhile/heuristic-research-agent-skill/issues/new?template=quick_start_trial.yml) |

## Submission Gate

- [ ] At least two independent external users complete or seriously attempt the Quick Start.
- [ ] At least three genuine findings receive public or consented sanitized triage.
- [ ] At least one finding drives a reviewed documentation, test, or code improvement.
- [ ] Two to four weeks of responsive maintenance are evidenced.
- [ ] Repository metrics and application fields are re-fetched on the submission date.
- [ ] The maintainer confirms authority to apply and supplies private account fields outside the repository.
- [ ] A fact checker and privacy/license review approve the final wording.
- [ ] The maintainer reviews the current official pages and Program Terms.
- [ ] The maintainer separately authorizes the final submission action.

Until every applicable item is complete, the correct decision is
`HOLD_FOR_EXTERNAL_EVIDENCE / DO_NOT_SUBMIT`.
