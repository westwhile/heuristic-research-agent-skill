# Contributing

Thank you for helping improve Heuristic Research Agent Skill. This repository
accepts focused fixes, documentation, tests, schema/contract proposals, and
evidence-boundary corrections. Read [GOVERNANCE.md](GOVERNANCE.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md) before participating.

## Before opening a change

1. Search existing issues and pull requests.
2. Use the matching issue form for bugs, schema/contract proposals,
   documentation, or research-boundary concerns.
3. Do not post credentials, private data, hidden evaluator material,
   vulnerability details, private paths, or third-party restricted payloads.
4. Keep one pull request centered on one auditable problem.

Security vulnerabilities follow [SECURITY.md](SECURITY.md), not a public issue.

## Development setup

Python 3.12 or newer is required. The required public lanes are recorded in the
[support matrix](docs/governance/SUPPORT_MATRIX.json).

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install .
$env:PYTHONPATH = "src"
$env:PYTHONDONTWRITEBYTECODE = "1"
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p "test_*.py" -v
```

On Ubuntu, use `.venv/bin/python` instead of the Windows interpreter path.
The package has no PyPI publication; these commands install from the checked-out
source tree.

## Required validation

Run checks proportionate to the change and report exact commands and outcomes:

```powershell
python -B scripts/verify_source_provenance.py
python -B -m unittest discover -s tests -p "test_*.py" -v
git diff --check
```

After creating a commit, changes that affect packaging, fixtures, CI, schemas,
or release behavior must also pass:

```powershell
python -B scripts/verify_archive_install.py
python -B scripts/verify_archive_suite.py 'C:\path\to\a\second\python.exe'
```

The second command requires two distinct interpreter paths. Archive test skips
must be reported; the single expected skip is the Git tracking check when
`.git` is absent.

## Contracts, schemas, and ADRs

- Published schema bytes and semantics are immutable. Follow
  [SCHEMA_COMPATIBILITY.md](docs/governance/SCHEMA_COMPATIBILITY.md) and add a
  successor version, fixtures, golden pins, and compatibility tests.
- Changes to Core/Adapter seams, authority, privacy, publication, promotion, or
  evidence semantics require an ADR in `docs/decisions/`.
- Core changes need at least two real domain consumers or must remain inside an
  Adapter/Executor boundary.
- Engineering tests, synthetic benchmarks, GitHub activity, and Releases must
  not be presented as real research, market, adoption, or Skill-installation
  evidence.

## Source and license discipline

Every contribution must be authored by you or submitted with compatible rights.
Do not copy unlicensed code, schemas, fixtures, templates, datasets, or long-form
text. A change that adds or changes an external source, generated artifact
family, compatibility fixture, template, quotation, or vendored dependency must
update both source-provenance files and satisfy `unknown=0`.

Unless a file states a separate license, contributions accepted into this
repository are distributed under Apache-2.0. By submitting a contribution, you
represent that you have the right to provide it on those terms. No contributor
license agreement or copyright assignment is currently required.

## Pull request checklist

- Explain the single problem, scope, and rollback.
- Link an issue when one exists.
- List changed public contracts and migration impact.
- State what the evidence supports and explicitly does not support.
- Record tests, versions, skipped/not-run items, and relevant hashes.
- Complete the source/license and privacy sections of the PR template.
- Wait for all required checks; maintainers merge with a merge commit unless a
  documented exception is approved.

Maintainers may request narrower commits, additional adversarial tests,
provenance evidence, or an ADR before review can complete.
