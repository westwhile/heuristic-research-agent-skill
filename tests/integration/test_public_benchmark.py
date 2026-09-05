"""E8: the first public benchmark suites (plan Phase 3; ADR-0006).

Driven entirely by the public tree under ``benchmarks/public/``:

- tree integrity: registry -> suite -> case -> contract/input pins, the
  candidate manifests, and the contamination ledger all cross-check;
- the full L0/L1 pipeline runs both domains x both candidates x 12 cases
  through :func:`evaluate_case`, publishes every record into a temporary
  store, and ``verify_record_graph`` must report a clean graph;
- per-case ``comparison-report/v1`` payloads render in all three forms
  from the same structured data;
- the evaluator meta-test obligations (known-good/known-bad distinction
  and six known-bad mutation instances) run against the real machinery.

Every case, artifact, and report here is SYNTHETIC public data
(``[SYNTHETIC]`` titles; ``contamination-ledger.json``). Nothing in this
suite is real-market or real-archive evidence.
"""

import dataclasses
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research_evolution.core import (
    canonical_bytes,
    canonical_sha256,
    load_record,
    load_strict_json,
    publish_record,
    verify_record_graph,
)
from research_evolution.evaluation import (
    Envelope,
    GateConfig,
    MetricPolicy,
    SuiteComparePolicy,
    assemble_verdict,
    compare_suite,
    evaluate_case,
    evaluate_gates,
    known_pair_check,
    mutate_drop_condition,
    mutate_invert_verdict,
    mutate_relax_resource_limit,
    mutation_check,
    render_html,
    render_json,
    render_markdown,
    run_replay,
    runner_identity,
    score_with_oracle,
    scorer_identity,
    small_sample_limitation,
)

TREE = Path(__file__).resolve().parents[2] / "benchmarks" / "public"

GENERATED_AT = "2026-08-16T12:30:00Z"
ENVELOPE = Envelope(timeout_ms=5000, max_output_bytes=65536, seed=20260816)
DOMAINS = ("math", "quant")
CANDIDATES = ("champion", "challenger")
# The challenger artifacts that answer wrongly BY DESIGN (ledger-noted).
WRONG_BY_DESIGN = {
    "math": {"M-02", "M-08", "M-12"},
    "quant": {"Q-03", "Q-09", "Q-11"},
}

# Example suite policies: patterns are deliberately absent from every
# artifact so the configured gates report ``pass`` (never silently
# ``not_applicable``); the regression floor at 1.0 is what fails the
# wrong-by-design challenger artifacts.
_BASE_PATTERNS = {
    "forbidden_output_patterns": (r"BEGIN [A-Z ]*PRIVATE KEY",),
    "privacy_patterns": (r"\b\d{3}-\d{2}-\d{4}\b",),
    "expected_runner": (runner_identity()["tool"], runner_identity()["version"]),
}
GATE_CONFIGS = {
    "math": GateConfig(
        **_BASE_PATTERNS,
        regression_floors=(("exact_match:answer", 1.0),),
        expected_scorer_tool=scorer_identity("oracle")["tool"],
    ),
    "quant": GateConfig(
        **_BASE_PATTERNS,
        regression_floors=(("within_tolerance:value", 1.0),),
        expected_scorer_tool=scorer_identity("deterministic_checker")["tool"],
    ),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path) -> dict:
    return load_strict_json(path.read_bytes())


def _case_ids(domain: str) -> list[str]:
    return sorted(path.stem for path in (TREE / domain / "cases").iterdir())


def _scoring(contract: dict) -> dict:
    level = contract["scorer_level"]
    if level == "oracle":
        return {"level": level, "oracle": contract["oracle"]}
    return {"level": level, "spec": contract["spec"]}


_STATE: dict | None = None


def _state() -> dict:
    """Run the whole public benchmark once; memoized for all test classes."""
    global _STATE
    if _STATE is not None:
        return _STATE
    registry = _load_json(TREE / "registry.json")
    ledger = _load_json(TREE / "contamination-ledger.json")
    candidate_docs = {
        name: _load_json(TREE / "candidates" / f"{name}.json") for name in CANDIDATES
    }
    suites = {domain: _load_json(TREE / domain / "suite.json") for domain in DOMAINS}
    cases = {
        domain: {cid: _load_json(TREE / domain / "cases" / f"{cid}.json") for cid in _case_ids(domain)}
        for domain in DOMAINS
    }
    contracts = {
        domain: {
            cid: _load_json(TREE / domain / "contracts" / f"{cid}.json")
            for cid in _case_ids(domain)
        }
        for domain in DOMAINS
    }
    artifacts = {
        (domain, cand, cid): (TREE / domain / "artifacts" / cand / f"{cid}.json").read_bytes()
        for domain in DOMAINS
        for cand in CANDIDATES
        for cid in _case_ids(domain)
    }
    outcomes: dict = {}
    for domain in DOMAINS:
        for cand in CANDIDATES:
            for cid in _case_ids(domain):
                artifact = artifacts[(domain, cand, cid)]
                if candidate_docs[cand]["outputs"][cid] != _sha(artifact):
                    raise ValueError("candidate manifest does not bind replay artifact")
                outcome = evaluate_case(
                    run_id=f"{cid.lower()}-{cand}",
                    case=cases[domain][cid],
                    suite=suites[domain],
                    candidate={
                        "candidate_id": candidate_docs[cand]["candidate_id"],
                        "sha256": canonical_sha256(candidate_docs[cand]),
                    },
                    artifact=artifact,
                    artifact_sha256=_sha(artifact),
                    envelope=ENVELOPE,
                    scoring=_scoring(contracts[domain][cid]),
                    gate_config=GATE_CONFIGS[domain],
                    generated_at=GENERATED_AT,
                )
                outcomes[(domain, cand, cid)] = outcome
    reports: dict = {}
    for domain in DOMAINS:
        metrics = (
            (MetricPolicy("exact_match:answer", "higher", "primary", 0.0),)
            if domain == "math"
            else (
                MetricPolicy("within_tolerance:value", "higher", "primary", 0.0),
                MetricPolicy(
                    "absolute_error:value",
                    "lower",
                    "guardrail",
                    0.0,
                    noninferiority_margin=0.1,
                ),
            )
        )
        reports[domain] = compare_suite(
            suite=suites[domain],
            champion_candidate={
                "candidate_id": candidate_docs["champion"]["candidate_id"],
                "sha256": canonical_sha256(candidate_docs["champion"]),
            },
            challenger_candidate={
                "candidate_id": candidate_docs["challenger"]["candidate_id"],
                "sha256": canonical_sha256(candidate_docs["challenger"]),
            },
            champion_runs=[
                outcomes[(domain, "champion", cid)].run_payload
                for cid in _case_ids(domain)
            ],
            challenger_runs=[
                outcomes[(domain, "challenger", cid)].run_payload
                for cid in _case_ids(domain)
            ],
            policy=SuiteComparePolicy(
                seed=20260816,
                expected_seeds=(20260816,),
                metrics=metrics,
            ),
            comparison_id=f"public-{domain}-suite",
            title=f"Champion vs Challenger on the {domain} synthetic public suite",
            conclusion="Suite-level synthetic engineering comparison only.",
            limitations=(
                "Synthetic public benchmark; L0/L1 coverage only — no L2–L4 claim.",
            ),
            generated_at=GENERATED_AT,
        )
    _STATE = {
        "registry": registry,
        "ledger": ledger,
        "candidates": candidate_docs,
        "suites": suites,
        "cases": cases,
        "contracts": contracts,
        "artifacts": artifacts,
        "outcomes": outcomes,
        "reports": reports,
    }
    return _STATE


class TreeIntegrityTest(unittest.TestCase):
    """The public tree's hash-binding chain, end to end."""

    def test_registry_suite_case_contract_input_ledger_binding(self) -> None:
        state = _state()
        registry_by_domain = {
            entry["domain"]: entry for entry in state["registry"]["suites"]
        }
        ledger_by_id = {
            entry["evaluation_case_id"]: entry
            for entry in state["ledger"]["entries"]
        }
        self.assertEqual(len(ledger_by_id), 24)
        for domain in DOMAINS:
            suite_raw = (TREE / domain / "suite.json").read_bytes()
            suite = state["suites"][domain]
            # Registry pins the suite record hash; the file is canonical.
            entry = registry_by_domain[domain]
            self.assertEqual(entry["suite_id"], suite["suite_id"])
            self.assertEqual(entry["path"], f"{domain}/suite.json")
            self.assertEqual(entry["sha256"], load_record(suite_raw).sha256)
            self.assertEqual(suite_raw, canonical_bytes(load_strict_json(suite_raw)))
            self.assertEqual(len(suite["cases"]), 12)
            splits = {}
            for cid, case in state["cases"][domain].items():
                with self.subTest(domain=domain, case=cid):
                    case_raw = (TREE / domain / "cases" / f"{cid}.json").read_bytes()
                    case_sha = load_record(case_raw).sha256
                    # Suite pins the case record hash.
                    pin = [
                        item
                        for item in suite["cases"]
                        if item["evaluation_case_id"] == cid
                    ]
                    self.assertEqual(len(pin), 1)
                    self.assertEqual(pin[0]["sha256"], case_sha)
                    # Contract pin is the canonical contract hash.
                    contract_raw = (
                        TREE / domain / "contracts" / f"{cid}.json"
                    ).read_bytes()
                    self.assertEqual(
                        case["evaluation_contract"]["contract_sha256"],
                        canonical_sha256(load_strict_json(contract_raw)),
                    )
                    # Input pin binds the raw input bytes at the locator.
                    locator = case["input"]["locator"]
                    self.assertEqual(locator, f"{domain}/inputs/{cid}.json")
                    input_raw = (TREE / locator).read_bytes()
                    self.assertEqual(
                        case["input"]["content_sha256"], _sha(input_raw)
                    )
                    # Contamination ledger agrees with the case record.
                    self.assertEqual(
                        ledger_by_id[cid]["contamination_status"],
                        case["contamination_status"],
                    )
                    self.assertIn("[SYNTHETIC]", case["title"])
                    splits[case["split"]] = splits.get(case["split"], 0) + 1
            self.assertEqual(
                splits,
                {"smoke": 1, "development": 2, "regression": 3, "metamorphic-public": 6},
            )
        # Candidate manifests pin every artifact's raw bytes.
        for cand in CANDIDATES:
            outputs = state["candidates"][cand]["outputs"]
            self.assertEqual(len(outputs), 24)
            for domain in DOMAINS:
                for cid in _case_ids(domain):
                    with self.subTest(candidate=cand, case=cid):
                        self.assertEqual(
                            outputs[cid],
                            _sha(state["artifacts"][(domain, cand, cid)]),
                        )


class PublicBenchmarkPipelineTest(unittest.TestCase):
    """Both domains x both candidates x 12 cases through evaluate_case."""

    def test_every_run_pins_manifest_separately_from_scored_output(self) -> None:
        state = _state()
        for (domain, candidate, case_id), outcome in state["outcomes"].items():
            with self.subTest(domain=domain, candidate=candidate, case=case_id):
                run = outcome.run_payload
                self.assertIsNotNone(run)
                self.assertEqual(
                    run["candidate"], state["reports"][domain][candidate]
                )
                artifact = state["artifacts"][(domain, candidate, case_id)]
                self.assertEqual(
                    state["candidates"][candidate]["outputs"][case_id], _sha(artifact)
                )
                self.assertEqual(
                    run["output"]["output_sha256"],
                    canonical_sha256(load_strict_json(artifact)),
                )

    def test_champion_passes_all_cases(self) -> None:
        outcomes = _state()["outcomes"]
        for domain in DOMAINS:
            for cid in _case_ids(domain):
                with self.subTest(domain=domain, case=cid):
                    outcome = outcomes[(domain, "champion", cid)]
                    self.assertEqual(outcome.verdict, "pass")
                    self.assertIsNotNone(outcome.run_payload)
                    self.assertIsNone(outcome.unpublishable_reason)

    def test_challenger_fails_exactly_the_designed_wrong_cases(self) -> None:
        outcomes = _state()["outcomes"]
        for domain in DOMAINS:
            for cid in _case_ids(domain):
                with self.subTest(domain=domain, case=cid):
                    outcome = outcomes[(domain, "challenger", cid)]
                    if cid in WRONG_BY_DESIGN[domain]:
                        self.assertEqual(outcome.verdict, "fail")
                        regression = [
                            result
                            for result in outcome.gate_results
                            if result.gate == "regression"
                        ]
                        self.assertEqual(regression[0].result, "fail")
                        self.assertTrue(regression[0].reason)
                    else:
                        self.assertEqual(outcome.verdict, "pass")

    def test_pipeline_is_deterministic(self) -> None:
        state = _state()
        for domain in DOMAINS:
            cid = _case_ids(domain)[0]
            artifact = state["artifacts"][(domain, "champion", cid)]
            again = evaluate_case(
                run_id=f"{cid.lower()}-champion",
                case=state["cases"][domain][cid],
                suite=state["suites"][domain],
                candidate={
                    "candidate_id": "champion-v1",
                    "sha256": canonical_sha256(state["candidates"]["champion"]),
                },
                artifact=artifact,
                artifact_sha256=_sha(artifact),
                envelope=ENVELOPE,
                scoring=_scoring(state["contracts"][domain][cid]),
                gate_config=GATE_CONFIGS[domain],
                generated_at=GENERATED_AT,
            )
            self.assertEqual(
                again.run_payload,
                state["outcomes"][(domain, "champion", cid)].run_payload,
            )

    def test_candidate_cannot_modify_case_scorer_or_contract(self) -> None:
        state = _state()
        domain, cid = "math", "M-01"
        case = state["cases"][domain][cid]
        # A tampered case no longer matches the suite pin.
        tampered_case = {**case, "title": "[SYNTHETIC] tampered title"}
        artifact = state["artifacts"][(domain, "champion", cid)]
        with self.assertRaises(ValueError):
            evaluate_case(
                run_id="tampered-case",
                case=tampered_case,
                suite=state["suites"][domain],
                candidate={"candidate_id": "champion-v1", "sha256": _sha(artifact)},
                artifact=artifact,
                artifact_sha256=_sha(artifact),
                envelope=ENVELOPE,
                scoring=_scoring(state["contracts"][domain][cid]),
                gate_config=GATE_CONFIGS[domain],
                generated_at=GENERATED_AT,
            )
        # The contract, not the caller, decides the scorer level.
        with self.assertRaises(ValueError):
            evaluate_case(
                run_id="tampered-scorer",
                case=case,
                suite=state["suites"][domain],
                candidate={"candidate_id": "champion-v1", "sha256": _sha(artifact)},
                artifact=artifact,
                artifact_sha256=_sha(artifact),
                envelope=ENVELOPE,
                scoring={"level": "structured_rubric", "scores": {"x": 1.0}},
                gate_config=GATE_CONFIGS[domain],
                generated_at=GENERATED_AT,
            )
        # A tampered contract no longer matches the case's contract pin.
        tampered_contract = {"scorer_level": "oracle", "oracle": {"answer": 999}}
        self.assertNotEqual(
            canonical_sha256(tampered_contract),
            case["evaluation_contract"]["contract_sha256"],
        )


class PublicationGraphTest(unittest.TestCase):
    """Every record publishes; the full graph verifies clean."""

    def test_publish_all_records_and_verify_graph(self) -> None:
        state = _state()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            published = 0
            for domain in DOMAINS:
                publish_record(
                    (TREE / domain / "suite.json").read_bytes(), root=root
                )
                published += 1
                for cid in _case_ids(domain):
                    publish_record(
                        (TREE / domain / "cases" / f"{cid}.json").read_bytes(),
                        root=root,
                    )
                    published += 1
            for domain in DOMAINS:
                for cand in CANDIDATES:
                    for cid in _case_ids(domain):
                        payload = state["outcomes"][(domain, cand, cid)].run_payload
                        receipt = publish_record(canonical_bytes(payload), root=root)
                        self.assertFalse(receipt.already_present)
                        published += 1
            for domain in DOMAINS:
                receipt = publish_record(render_json(state["reports"][domain]), root=root)
                self.assertFalse(receipt.already_present)
                published += 1
            self.assertEqual(published, 76)
            report = verify_record_graph(root)
            self.assertTrue(report.ok, [v.to_dict() for v in report.violations])
            self.assertEqual(report.records_total, 76)
            self.assertEqual(
                report.families,
                {
                    "evaluation-case/v1": 24,
                    "evaluation-run/v1": 48,
                    "suite-comparison/v1": 2,
                    "suite/v1": 2,
                },
            )


class ComparisonReportTest(unittest.TestCase):
    """Suite-level comparison reports: schema, forms, hashes, discipline."""

    def test_reports_are_schema_valid_and_hash_bound(self) -> None:
        state = _state()
        for domain in DOMAINS:
            with self.subTest(domain=domain):
                report = state["reports"][domain]
                record = load_record(render_json(report))
                self.assertEqual(record.schema_id, "suite-comparison/v1")
                self.assertEqual(len(report["champion_runs"]), 12)
                self.assertEqual(len(report["challenger_runs"]), 12)
                self.assertEqual(report["levels_covered"], ["L0", "L1"])
                self.assertEqual(report["methods"]["seed"], 20260816)
                self.assertTrue(all(metric["n_pairs"] == 12 for metric in report["metrics"]))

    def test_small_sample_limitation_present_in_every_report(self) -> None:
        reports = _state()["reports"]
        for domain in DOMAINS:
            sentence = small_sample_limitation(12)
            self.assertIsNotNone(sentence)
            self.assertIn(sentence, reports[domain]["limitations"])

    def test_gate_summary_folding(self) -> None:
        reports = _state()["reports"]
        for domain in DOMAINS:
            summary = reports[domain]["gate_summary"]
            regression = [item for item in summary if item["gate"] == "regression"]
            self.assertEqual(regression[0]["result"], "fail")
            self.assertTrue(regression[0]["reason"])

    def test_three_forms_render_from_the_same_payload(self) -> None:
        state = _state()
        for domain in DOMAINS:
            with self.subTest(domain=domain):
                report = state["reports"][domain]
                self.assertEqual(render_json(report), canonical_bytes(report))
                markdown = render_markdown(report)
                self.assertIn(report["suite_comparison_id"], markdown)
                self.assertIn("case_seed_frozen_envelope", markdown)
                html = render_html(report)
                self.assertIn(report["suite_comparison_id"], html)
                self.assertIn("<table", html)

    def test_compare_suite_is_deterministic_and_rejects_incomplete_pairings(self) -> None:
        state = _state()
        policy = SuiteComparePolicy(
            seed=20260816,
            expected_seeds=(20260816,),
            metrics=(MetricPolicy("exact_match:answer", "higher", "primary", 0.0),),
        )
        kwargs = dict(
            suite=state["suites"]["math"],
            champion_candidate={
                "candidate_id": state["candidates"]["champion"]["candidate_id"],
                "sha256": canonical_sha256(state["candidates"]["champion"]),
            },
            challenger_candidate={
                "candidate_id": state["candidates"]["challenger"]["candidate_id"],
                "sha256": canonical_sha256(state["candidates"]["challenger"]),
            },
            champion_runs=[
                state["outcomes"][("math", "champion", cid)].run_payload
                for cid in _case_ids("math")
            ],
            challenger_runs=[
                state["outcomes"][("math", "challenger", cid)].run_payload
                for cid in _case_ids("math")
            ],
            policy=policy,
            comparison_id="public-math-suite",
            title="Champion vs Challenger on the math synthetic public suite",
            conclusion="Suite-level synthetic engineering comparison only.",
            limitations=(
                "Synthetic public benchmark; L0/L1 coverage only — no L2–L4 claim.",
            ),
            generated_at=GENERATED_AT,
        )
        self.assertEqual(compare_suite(**kwargs), state["reports"]["math"])
        with self.assertRaises(ValueError):
            compare_suite(**{**kwargs, "challenger_runs": kwargs["challenger_runs"][:-1]})


class PublicMetaTest(unittest.TestCase):
    """Evaluator meta-tests on artifacts from the public tree (decision 9)."""

    @staticmethod
    def _probe_verdict(
        artifact: bytes,
        oracle: dict,
        *,
        envelope: Envelope,
        config: GateConfig,
        evaluate=evaluate_gates,
        assemble=assemble_verdict,
    ) -> str:
        """The mini evaluation pipeline under test: replay -> score -> gates -> verdict."""
        replay = run_replay(artifact, _sha(artifact), envelope)
        scores = (
            score_with_oracle(load_strict_json(replay.output_bytes or b""), oracle)
            if replay.ok
            else None
        )
        results = evaluate(
            replay=replay,
            score_vector=scores,
            runner_id=runner_identity(),
            scorer_id=scorer_identity("oracle"),
            config=config,
        )
        return assemble(replay, results, scores)

    def _probes(self) -> dict:
        state = _state()
        return {
            "golden": (
                state["artifacts"][("math", "champion", "M-01")],
                state["contracts"]["math"]["M-01"]["oracle"],
            ),
            "known-bad": (
                state["artifacts"][("math", "challenger", "M-02")],
                state["contracts"]["math"]["M-02"]["oracle"],
            ),
        }

    def _verdicts(self, probes: dict, **kwargs) -> dict:
        return {
            name: self._probe_verdict(artifact, oracle, **kwargs)
            for name, (artifact, oracle) in probes.items()
        }

    def test_known_good_known_bad_stably_distinguished(self) -> None:
        reference = self._verdicts(
            self._probes(), envelope=ENVELOPE, config=GATE_CONFIGS["math"]
        )
        self.assertEqual(reference, {"golden": "pass", "known-bad": "fail"})
        report = known_pair_check(reference, {"golden": "pass", "known-bad": "fail"})
        self.assertTrue(report.detected, report.detail)

    def test_six_known_bad_mutation_instances_are_detected(self) -> None:
        probes = self._probes()
        base = GATE_CONFIGS["math"]
        reference = self._verdicts(probes, envelope=ENVELOPE, config=base)
        # 1. invert_verdict flips every probe.
        mutated = self._verdicts(
            probes,
            envelope=ENVELOPE,
            config=base,
            assemble=mutate_invert_verdict(assemble_verdict),
        )
        report = mutation_check("invert_verdict", reference, mutated)
        self.assertTrue(report.detected, report.detail)
        # 2. drop_condition on regression saves the known-bad probe.
        mutated = self._verdicts(
            probes,
            envelope=ENVELOPE,
            config=base,
            evaluate=mutate_drop_condition(evaluate_gates, "regression"),
        )
        report = mutation_check("drop_condition", reference, mutated)
        self.assertTrue(report.detected, report.detail)
        self.assertIn("known-bad", report.detail)
        # 3./4. drop_condition on critical_safety / privacy: with a policy
        # whose pattern matches the artifact text, the golden probe fails
        # the gate in the reference and passes once the gate is dropped.
        for gate, field in (
            ("critical_safety", "forbidden_output_patterns"),
            ("privacy", "privacy_patterns"),
        ):
            config = dataclasses.replace(base, **{field: (r'"answer"',)})
            flagged = self._verdicts(probes, envelope=ENVELOPE, config=config)
            self.assertEqual(flagged["golden"], "fail")
            mutated = self._verdicts(
                probes,
                envelope=ENVELOPE,
                config=config,
                evaluate=mutate_drop_condition(evaluate_gates, gate),
            )
            report = mutation_check("drop_condition", flagged, mutated)
            self.assertTrue(report.detected, report.detail)
            self.assertIn("golden", report.detail)
        # 5./6. relax_resource_limit (x10 and x100): a valid-but-oversize
        # artifact errors under the frozen envelope and passes relaxed.
        padded = canonical_bytes({"answer": 2, "note": "x" * 80})
        small = Envelope(timeout_ms=5000, max_output_bytes=64, seed=20260816)
        oversize = {"oversize": (padded, {"answer": 2})}
        reference = self._verdicts(oversize, envelope=small, config=base)
        self.assertEqual(reference["oversize"], "error")
        for multiplier in (10, 100):
            mutated = self._verdicts(
                oversize,
                envelope=mutate_relax_resource_limit(small, multiplier),
                config=base,
            )
            self.assertEqual(mutated["oversize"], "pass")
            report = mutation_check("relax_resource_limit", reference, mutated)
            self.assertTrue(report.detected, report.detail)

    def test_unmutated_control_is_never_detected(self) -> None:
        kwargs = {"envelope": ENVELOPE, "config": GATE_CONFIGS["math"]}
        reference = self._verdicts(self._probes(), **kwargs)
        for mutation in ("invert_verdict", "drop_condition", "relax_resource_limit"):
            report = mutation_check(
                mutation, reference, self._verdicts(self._probes(), **kwargs)
            )
            self.assertFalse(report.detected, report.detail)


if __name__ == "__main__":
    unittest.main()
