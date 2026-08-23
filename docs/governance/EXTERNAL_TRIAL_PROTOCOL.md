# O5 external Quick Start trial protocol

- Status: `LAUNCH_READY / NO_EXTERNAL_RESULTS_YET`
- Release under trial: [`v0.6.1`](https://github.com/westwhile/heuristic-research-agent-skill/releases/tag/v0.6.1)
- Release commit: `5af73595f847702930e0c1966986f3d06d3c1c35`
- Intended public window: 2–4 weeks after this protocol enters `main`

This protocol opens a bounded path for independent users to try the synthetic
Quick Start and report installation, documentation, or interpretation friction.
Publishing the protocol is not external-adoption evidence. The repository must
continue to say `NO_EXTERNAL_RESULTS_YET` until qualifying attempts actually
exist.

## Who and what this trial is for

The target is two or three people who were not involved in building or releasing
this repository, preferably research-software maintainers or practitioners in
mathematics, quantitative research, or ML evaluation. Each participant should
use their own supported Windows or Ubuntu environment and Python 3.12 or 3.14.

The trial covers only the source-install Quick Start and its two synthetic paths:

1. the valid demo must produce a hash-bound engineering record;
2. the tampered demo must be rejected with exit code 1.

It does not test real research, real market data, model training, a packaged
Skill, production deployment, or the Codex for Open Source application.

## Participant path

1. Start from the annotated `v0.6.1` tag or its checksum-bound source asset.
2. Follow the repository [five-minute Quick Start](../../README.md#五分钟-quick-start)
   without using maintainer-local files or an existing development environment.
3. Record the exact tag or commit, OS, Python version, elapsed minutes, outcome,
   and any confusing or failing step.
4. Submit the
   [Quick Start trial feedback form](https://github.com/westwhile/heuristic-research-agent-skill/issues/new?template=quick_start_trial.yml).
5. Report suspected vulnerabilities privately under [SECURITY.md](../../SECURITY.md),
   never through the public form.

Public issues must not contain credentials, private paths, personal or market
data, hidden cases, vulnerability details, or third-party restricted material.
Participants may use a pseudonymous GitHub account; identity beyond what they
choose to publish is not required.

## Evidence record and counting rules

For each qualifying attempt, the public or consented-to-be-public record should
capture:

- issue or public feedback URL and submission time;
- self-reported relationship to the project;
- tested tag or commit, OS, Python version, and elapsed time;
- success, install failure, demo failure, or interpretation problem;
- maintainer triage and the fix, rejection, deferral, or documentation response;
- linked PR or commit when feedback changes the repository.

A participant counts as independent only when the attempt comes from a real
person other than the maintainer and is not bot-generated, paid-for engagement,
a duplicate identity, or an interaction manufactured for application metrics.
One participant may provide multiple findings, but still counts as one user.

The following do **not** count as external adoption:

- maintainer or bot issues, reviews, CI runs, and self-tests;
- stars, forks, clones, page views, or asset downloads without a qualifying
  attempt record;
- the maintainer's release-asset redownload and checksum verification;
- synthetic demo success by itself;
- private praise or usage claims that cannot be published or independently
  audited.

Private feedback may be retained outside the repository. It may contribute to a
public aggregate only when the participant consents to the exact disclosed
facts; names and raw messages remain private unless separately authorized.

## Exit Gate

O5 is complete only when all of the following are true:

- at least two independent external users completed or seriously attempted the
  Quick Start;
- at least three genuine findings entered public or consented, sanitized triage;
- at least one finding drove a reviewed documentation, test, or code improvement;
- evidence shows 2–4 weeks of responsive maintenance after public launch;
- every counted claim links to evidence and avoids inflating downloads or
  maintainer activity into adoption.

Until then, the accurate status is `EARLY_STAGE / EXTERNAL_EVIDENCE_PENDING`.
Meeting this Gate does not guarantee acceptance into any OpenAI program, and
submitting an application remains a separate maintainer authorization.
