# Phase 6 R6A external-trial protocol

- Protocol ID: `dl-external-trial-protocol/v1`
- Status: `PROTOCOL_READY / ZERO_ACCEPTED_EXTERNAL_SUBMISSIONS`
- Evidence type: engineering trial governance only
- Automatic invitation, upload, framework installation, and Skill installation: forbidden

This protocol prepares pseudonymous, public-safe submissions for a future
cross-environment trial. It does not invite anyone, accept a current
submission, prove an independent participant or host, complete the R5
technical comparison, establish external adoption, or authorize Phase 7.

## Frozen evidence levels

| Level | Meaning | What it does not mean |
|---|---|---|
| `not_verified` | No usable participant/coordinator record exists | Rejection, independence, or adoption |
| `self_declared` | The participant accepted the protocol and made all required declarations | Coordinator-confirmed identity or host independence |
| `coordinator_verified` | The coordinator matched nonce-hardened private record hashes and recorded explicit review decisions | Independent audit, technical reproducibility, adoption, or production readiness |

`coordinator_verified` is a governance fact about the coordinator's review.
It is not a cryptographic proof that a person or host is independent.

## Private records and nonce hardening

The participant and coordinator keep the following records outside the
repository and outside every public submission:

- identity/independence record;
- publication-consent record;
- host-independence record;
- a separate random nonce of at least 128 bits for each record.

Each public hash must be computed over a private record that includes its
random nonce. Never hash a raw name, email address, device serial number, or
other low-entropy identifier directly: an unsalted SHA-256 can be guessed by
dictionary attack. The raw records and nonces must not be committed, attached
to a PR, placed in an Issue, copied into a receipt, or sent to an agent.

## Coordinator preparation

Before accepting any material, the coordinator publishes one immutable trial
target containing all of the following:

1. exact Git commit and tree object IDs;
2. independently computed `git archive` SHA-256;
3. SHA-256 of this protocol file from that exact archive;
4. required Python/PyTorch/CUDA envelope and the R5 fixed seeds;
5. an out-of-repository transfer channel selected by the human participants.

R6A does not select a participant, send an invitation, create an account, or
operate a participant's machine.

## Participant procedure

The participant performs every execution step on a host they control:

1. obtain the exact source commit and independently create/verify its
   `git archive`;
2. use a caller-managed Python and PyTorch/CUDA installation—do not ask the
   repository scripts to install a framework or driver;
3. run `scripts/verify_dl_portability_trial.py` from the exact archive and
   write the R5 receipt to a new path outside the repository;
4. inspect the receipt locally and stop if it contains a path, credential,
   email, hostname, serial number, raw environment dump, or other identifier;
5. create the private nonce-hardened identity and consent records outside the
   repository, then prepare a `dl-external-trial-attestation/v1` JSON document
   containing only the pseudonym and record hashes;
6. run `scripts/prepare_dl_external_trial_submission.py` with the R5 receipt,
   attestation, and a new out-of-repository output path;
7. inspect the generated submission before choosing whether to transfer it.

The public participant ID must be a randomly generated value of the form
`participant-` plus sixteen lowercase hexadecimal characters. It must not be
derived from a name, email address, username, hostname, or device identifier.

The submission script performs no network request or upload. A successful
submission remains `submitted_unreviewed`, and its independence fields remain
false even though the participant declarations are `self_declared`.

## Coordinator review procedure

For each transferred submission, the coordinator works from the private
records outside Git and prepares one strict
`dl-external-trial-cohort-review-plan/v1` record. Every row must bind:

- exact submission SHA-256 and public participant ID;
- nonce-hardened private identity and consent record hashes already present in
  the submission;
- a nonce-hardened private host record hash;
- receipt binding, participant independence, host independence, and consent
  review decisions;
- an `accepted` or `rejected` disposition.

The coordinator then runs `scripts/review_dl_external_trial_cohort.py` locally.
Duplicate submission, receipt, pseudonym, identity record, or consent record
bindings fail closed. A repeated private host record or repeated normalized R5
environment prevents cross-environment eligibility.

Eligibility requires at least two accepted pseudonymous participants, at least
two distinct R5 environment hashes, distinct private host record hashes, and
`verified` receipt/identity/host/consent decisions for every accepted row.
Eligibility only opens a separate R5 technical comparison Gate; it does not
complete that comparison.

## Publication and evidence boundary

No submission or review artifact may enter Git until the coordinator confirms
the corresponding public-consent hash and separately authorizes publication.
Raw private records never enter Git, even with consent.

After an eligible cohort exists, a later R6C authorization must independently:

1. load the exact R5 receipts referenced by the accepted submissions;
2. run `build_cross_environment_report` with the preregistered tolerance;
3. bind the R5 report SHA-256 to the cohort review;
4. publish only consented public-safe material or a consented aggregate;
5. retain `external_adoption_verified=false` and
   `production_reliability_verified=false`.

Trial participation is not product adoption. R5/R6 engineering evidence is not
real-data validation, scientific validity, predictive performance, production
reliability, Skill installation, or a release Gate.

## Immediate stop conditions

Stop without accepting or publishing material if any of these occurs:

- commit, tree, archive, protocol, receipt, submission, or review hash drift;
- missing consent or a declaration that the maintainer operated the run;
- raw identity/consent/host records or their nonces appear in public material;
- any path, credential shape, email, hostname, serial number, or raw environment
  dump appears in an artifact;
- duplicate participant/private-record binding, repeated host record, or too
  few distinct environments;
- an attempt to treat trial participation as adoption or production evidence.
