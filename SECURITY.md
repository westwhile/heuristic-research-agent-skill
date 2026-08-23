# Security Policy

## Supported versions

Security support is provided on a best-effort basis for the following source
states:

| Version or branch | Supported |
|---|---|
| `main` | Yes |
| Latest GitHub Release (`v0.6.0` at the time of this policy) | Yes |
| `v0.5.x` and earlier | No |

This repository is not published on PyPI, does not distribute an installed
Skill payload, and does not claim production-agent readiness. A GitHub Release
is source and engineering evidence, not evidence of deployment or operational
security certification.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or include exploit,
credential, personal-data, or embargoed details in a public discussion.

Send a private report to **wejiaabby@outlook.com** with the subject
`[heuristic-research-agent-skill security]`. Include, when available:

- the affected commit, tag, file, or interface;
- the impact and realistic attack preconditions;
- minimal reproduction steps or a proof of concept;
- whether any credentials or private data may be exposed;
- suggested mitigations and your preferred disclosure timeline.

The maintainer will try to acknowledge a complete report within three business
days and provide an initial triage assessment within seven business days. These
are best-effort targets, not guaranteed resolution times. Please allow time for
verification and a coordinated fix before public disclosure.

## Scope and handling

Reports concerning source code, packaging, release artifacts, GitHub Actions,
schemas, or repository automation are in scope. Reports about excluded external
payloads, unavailable third-party services, or hypothetical future Phase 6/v13
components may be redirected or closed as out of scope, but boundary failures
that accidentally expose or distribute such content remain in scope.

The maintainer will minimize access to report material, preserve relevant
evidence, and coordinate disclosure with the reporter when practical. A valid
report does not guarantee a bounty, credit, a particular remediation, or a
specific release date.
