from __future__ import annotations

import json
import math
from dataclasses import replace
import unittest

from hypercognitive_engine import (
    AxiomParadigm,
    BranchFinding,
    CognitiveRule,
    EngineError,
    GoalMetricProfile,
    InferenceBudget,
    MindFact,
    SemanticDimensions,
    TeleologicalGoal,
    UniverseBranch,
    UniversalBrainCore,
    generate_combinatorial_rules,
    make_fact,
    make_implication_rule,
)


class ModelInvariantTests(unittest.TestCase):
    def test_dimensions_reject_non_finite_and_invalid_ranges(self) -> None:
        with self.assertRaises(ValueError):
            SemanticDimensions(epistemology=math.nan)
        with self.assertRaises(ValueError):
            SemanticDimensions(entropy=1.01)
        with self.assertRaises(ValueError):
            SemanticDimensions(intensity=0.99)
        with self.assertRaises(ValueError):
            MindFact("x", "Fakt", 1.2)

    def test_fact_sources_are_deduplicated_and_semantic_key_is_normalized(self) -> None:
        fact = MindFact("id", "  Ein   belastbarer Fakt  ", 0.8, sources=("a", "a", "b"))
        self.assertEqual(fact.sources, ("a", "b"))
        self.assertEqual(fact.semantic_key[0], "ein belastbarer fakt")

    def test_snapshot_mappings_cannot_mutate_engine_state(self) -> None:
        engine = UniversalBrainCore()
        engine.add_fact(make_fact("Beobachtung", 0.7, fact_id="observation"))
        snapshot = engine.facts
        with self.assertRaises(TypeError):
            snapshot["other"] = make_fact("Andere Beobachtung", 0.6)
        self.assertEqual(tuple(engine.facts), ("observation",))

    def test_rule_snapshot_is_detached_from_internal_rule_state(self) -> None:
        engine = UniversalBrainCore()
        engine.add_rule(make_implication_rule("r", ("missing",), "Nicht erreichbar", priority=3))
        exposed_rule = engine.rules["r"]
        exposed_rule.priority = 99
        self.assertEqual(engine.rules["r"].priority, 3)

    def test_audit_event_data_is_immutable(self) -> None:
        engine = UniversalBrainCore()
        engine.add_fact(make_fact("Audit-Evidenz", 0.8, fact_id="audit"))
        event = engine.audit_trail[-1]
        with self.assertRaises(TypeError):
            event.data["manipulation"] = True


class FactGoalAndInferenceTests(unittest.TestCase):
    def test_semantic_duplicate_is_replaced_only_by_higher_quality(self) -> None:
        engine = UniversalBrainCore()
        low = make_fact("Die Quelle ist verlässlich.", 0.50, fact_id="low")
        high = make_fact("  die quelle  ist verlässlich. ", 0.90, fact_id="high")
        lower_again = make_fact("Die Quelle ist verlässlich.", 0.30, fact_id="lower-again")
        self.assertTrue(engine.add_fact(low))
        self.assertTrue(engine.add_fact(high))
        self.assertFalse(engine.add_fact(lower_again))
        self.assertEqual(tuple(engine.facts), ("high",))

    def test_id_and_semantic_collision_requires_superiority_over_both_records(self) -> None:
        engine = UniversalBrainCore()
        engine.add_fact(make_fact("Inhalt A", 0.70, fact_id="shared"))
        engine.add_fact(make_fact("Inhalt B", 0.80, fact_id="other"))
        rejected = make_fact("Inhalt B", 0.75, fact_id="shared")
        accepted = make_fact("Inhalt B", 0.95, fact_id="shared")
        self.assertFalse(engine.add_fact(rejected))
        self.assertTrue(engine.add_fact(accepted))
        self.assertEqual(tuple(engine.facts), ("shared",))
        self.assertEqual(engine.facts["shared"].content, "Inhalt B")

    def test_goal_changes_realign_existing_facts(self) -> None:
        engine = UniversalBrainCore()
        fact = make_fact(
            "Kohärente Evidenz",
            0.8,
            fact_id="evidence",
            dimensions=SemanticDimensions(epistemology=0.9, entropy=0.1, emergence=0.2),
        )
        engine.add_fact(fact)
        before = engine.facts["evidence"].dimensions.goal_alignment
        engine.add_goal(
            TeleologicalGoal(
                "coherence",
                "Kohärenz priorisieren",
                GoalMetricProfile(novelty=0.0, coherence=1.0, predictability=0.0, emergence=0.0),
            )
        )
        after = engine.facts["evidence"].dimensions.goal_alignment
        self.assertGreater(after, before)
        engine.set_goal_satisfied("coherence")
        self.assertNotEqual(engine.facts["evidence"].dimensions.goal_alignment, after)

    def test_inference_tracks_provenance_and_reaches_fixed_point(self) -> None:
        engine = UniversalBrainCore()
        engine.add_fact(make_fact("Prämisse A", 0.9, fact_id="a"))
        engine.add_fact(make_fact("Prämisse B", 0.8, fact_id="b"))
        engine.add_rule(make_implication_rule("r", ("a", "b"), "Konklusion", certainty=0.75, priority=4))
        report = engine.run_inference(InferenceBudget(max_iterations=5, max_rule_applications=20))
        self.assertEqual(report.stopped_reason, "fixed_point")
        self.assertEqual(len(report.derived_fact_ids), 1)
        derived_id = report.derived_fact_ids[0]
        record = engine.derivations[derived_id]
        self.assertEqual(record.rule_id, "r")
        self.assertEqual(record.parent_ids, ("a", "b"))
        self.assertEqual(engine.facts[derived_id].generation, 1)

    def test_rule_priority_is_deterministic(self) -> None:
        engine = UniversalBrainCore()
        calls: list[str] = []

        def condition(_: tuple[MindFact, ...]) -> bool:
            return True

        def high_action(_: tuple[MindFact, ...]) -> tuple[MindFact, ...]:
            calls.append("high")
            return ()

        def low_action(_: tuple[MindFact, ...]) -> tuple[MindFact, ...]:
            calls.append("low")
            return ()

        engine.add_rule(CognitiveRule("low", condition, low_action, priority=1))
        engine.add_rule(CognitiveRule("high", condition, high_action, priority=10))
        engine.run_inference(InferenceBudget(max_iterations=1, max_rule_applications=4))
        self.assertEqual(calls, ["high", "low"])

    def test_inference_respects_derived_fact_budget(self) -> None:
        engine = UniversalBrainCore()
        engine.add_fact(make_fact("Anker", 0.9, fact_id="anchor"))

        def condition(_: tuple[MindFact, ...]) -> bool:
            return True

        def action(_: tuple[MindFact, ...]) -> tuple[MindFact, ...]:
            return (
                make_fact("Ableitung eins", 0.7, fact_id="d1", sources=("anchor",)),
                make_fact("Ableitung zwei", 0.7, fact_id="d2", sources=("anchor",)),
            )

        engine.add_rule(CognitiveRule("multiple", condition, action))
        report = engine.run_inference(InferenceBudget(max_iterations=5, max_derived_facts=1, max_rule_applications=20))
        self.assertEqual(report.stopped_reason, "derived_fact_budget")
        self.assertEqual(report.derived_fact_ids, ("d1",))
        self.assertNotIn("d2", engine.facts)

    def test_rule_errors_are_audited_without_aborting_other_rules(self) -> None:
        engine = UniversalBrainCore()
        engine.add_fact(make_fact("Anker", 0.9, fact_id="anchor"))

        def active(_: tuple[MindFact, ...]) -> bool:
            return True

        def broken(_: tuple[MindFact, ...]) -> tuple[MindFact, ...]:
            raise RuntimeError("beabsichtigter Testfehler")

        engine.add_rule(CognitiveRule("broken", active, broken, priority=10))
        engine.add_rule(make_implication_rule("working", ("anchor",), "Abgeleitet", priority=1))
        report = engine.run_inference(InferenceBudget(max_iterations=3, max_rule_applications=10))
        self.assertTrue(report.errors)
        self.assertEqual(len(report.derived_fact_ids), 1)
        self.assertTrue(any(event.kind == "rule_error" for event in engine.audit_trail))


class ResonanceAndUniverseTests(unittest.TestCase):
    def _engine_with_related_facts(self) -> UniversalBrainCore:
        engine = UniversalBrainCore()
        engine.add_fact(
            make_fact(
                "Sensor meldet stabile Temperatur.",
                0.9,
                fact_id="a",
                dimensions=SemanticDimensions(epistemology=0.9, entropy=0.1, intensity=2.0, emergence=0.2),
            )
        )
        engine.add_fact(
            make_fact(
                "Temperatur-Sensor bleibt stabil.",
                0.8,
                fact_id="b",
                dimensions=SemanticDimensions(epistemology=0.85, entropy=0.15, intensity=1.5, emergence=0.2),
            )
        )
        return engine

    def test_resonance_edges_and_propagation_are_bounded(self) -> None:
        engine = self._engine_with_related_facts()
        edges = engine.build_resonance_network(threshold=0.1)
        self.assertEqual(len(edges), 1)
        self.assertEqual({edges[0].fact_a, edges[0].fact_b}, {"a", "b"})
        before = engine.facts["a"].dimensions.intensity
        updated = engine.propagate_resonance(edges, rate=0.1, steps=2)
        self.assertEqual(updated, ("a", "b"))
        self.assertGreater(engine.facts["a"].dimensions.intensity, before)
        self.assertLessEqual(engine.facts["a"].dimensions.intensity, 1e12)

    def test_universe_exploration_isolated_from_core_facts(self) -> None:
        engine = self._engine_with_related_facts()
        baseline = engine.facts["a"].dimensions
        branches = engine.explore_universes((AxiomParadigm.STANDARD, AxiomParadigm.CHAOS_FIRST), top_facts_per_branch=1)
        self.assertEqual(len(branches), 2)
        self.assertEqual(engine.facts["a"].dimensions, baseline)
        standard = branches[0]
        chaos = branches[1]
        self.assertNotEqual(standard.facts[0].dimensions, chaos.facts[0].dimensions)
        self.assertEqual(len(standard.findings), 1)


class SynthesisAndExportTests(unittest.TestCase):
    def test_synthesis_reports_consensus_and_explicit_conflict(self) -> None:
        engine = UniversalBrainCore()
        branches = (
            UniverseBranch(
                "one",
                AxiomParadigm.STANDARD,
                (),
                (
                    BranchFinding("one", "x1", "Das Ventil ist offen.", "ventil ist offen", True, 0.8),
                    BranchFinding("one", "y1", "Der Druck ist stabil.", "druck ist stabil", True, 0.7),
                ),
                0.75,
            ),
            UniverseBranch(
                "two",
                AxiomParadigm.LOGIC_FIRST,
                (),
                (
                    BranchFinding("two", "x2", "Ventil offen bestätigt.", "ventil ist offen", True, 0.9),
                    BranchFinding("two", "y2", "Der Druck ist nicht stabil.", "druck ist stabil", False, 0.6),
                ),
                0.75,
            ),
            UniverseBranch(
                "three",
                AxiomParadigm.OBSERVATION_FIRST,
                (),
                (BranchFinding("three", "x3", "Ventil offen beobachtet.", "ventil ist offen", True, 0.85),),
                0.85,
            ),
        )
        result = engine.synthesize_branches(branches, min_support=0.60)
        self.assertEqual(len(result.consensus), 1)
        self.assertEqual(result.consensus[0].claim_key, "ventil ist offen")
        self.assertEqual(result.consensus[0].support_ratio, 1.0)
        self.assertEqual(len(result.conflicts), 1)
        self.assertEqual(result.conflicts[0].claim_key, "druck ist stabil")

    def test_synthesis_counts_at_most_one_vote_per_branch_and_claim(self) -> None:
        engine = UniversalBrainCore()
        branches = (
            UniverseBranch(
                "one",
                AxiomParadigm.STANDARD,
                (),
                (
                    BranchFinding("one", "x1", "Signal bestätigt.", "signal", True, 0.2),
                    BranchFinding("one", "x2", "Signal erneut bestätigt.", "signal", True, 0.9),
                ),
                0.5,
            ),
            UniverseBranch(
                "two",
                AxiomParadigm.LOGIC_FIRST,
                (),
                (BranchFinding("two", "x3", "Signal bestätigt.", "signal", True, 0.6),),
                0.6,
            ),
        )
        result = engine.synthesize_branches(branches, min_support=1.0)
        self.assertEqual(len(result.consensus), 1)
        self.assertAlmostEqual(result.consensus[0].mean_score, 0.75)
        self.assertEqual(result.consensus[0].branch_ids, ("one", "two"))

    def test_synthesis_rejects_misaligned_finding_branch_id(self) -> None:
        engine = UniversalBrainCore()
        branch = UniverseBranch(
            "one",
            AxiomParadigm.STANDARD,
            (),
            (BranchFinding("other", "x", "Signal", "signal", True, 0.5),),
            0.5,
        )
        with self.assertRaises(ValueError):
            engine.synthesize_branches((branch,))

    def test_json_export_contains_data_but_no_callable_callbacks(self) -> None:
        engine = UniversalBrainCore()
        engine.add_fact(make_fact("Evidenz", 0.8, fact_id="e"))
        engine.add_rule(make_implication_rule("r", ("e",), "Folgerung"))
        engine.run_inference()
        payload = json.loads(engine.export_audit())
        self.assertIn("e", {fact["id"] for fact in payload["facts"]})
        self.assertEqual(payload["rules"][0]["id"], "r")
        self.assertNotIn("action", payload["rules"][0])
        self.assertNotIn("condition", payload["rules"][0])
        self.assertTrue(payload["derivations"])


class PersistenceAndObservabilityTests(unittest.TestCase):
    def _engine_with_state(self) -> UniversalBrainCore:
        engine = UniversalBrainCore()
        engine.add_goal(TeleologicalGoal("quality", "Qualität", GoalMetricProfile(coherence=1.0)))
        engine.add_fact(make_fact("Evidenz", 0.9, fact_id="evidence"))
        engine.add_rule(make_implication_rule("derive", ("evidence",), "Folgerung", certainty=0.8))
        engine.run_inference()
        return engine

    def test_state_roundtrip_preserves_declarative_digest_but_not_callbacks(self) -> None:
        engine = self._engine_with_state()
        exported = engine.export_state()
        restored = UniversalBrainCore.from_state(exported)
        self.assertEqual(restored.state_digest(), engine.state_digest())
        self.assertEqual(set(restored.facts), set(engine.facts))
        self.assertEqual(restored.goals, engine.goals)
        self.assertEqual(set(restored.derivations), set(engine.derivations))
        self.assertFalse(restored.rules)
        self.assertIn("derive", restored.rule_manifest)
        self.assertFalse(restored.rule_manifest["derive"]["registered"])
        self.assertTrue(restored.inspect_integrity().valid)

    def test_state_import_detects_tampering(self) -> None:
        engine = self._engine_with_state()
        envelope = json.loads(engine.export_state())
        envelope["state"]["facts"][0]["content"] = "Manipulierte Evidenz"
        with self.assertRaises(EngineError):
            UniversalBrainCore.from_state(json.dumps(envelope))
        restored = UniversalBrainCore.from_state(json.dumps(envelope), verify=False)
        self.assertIn("Manipulierte Evidenz", {fact.content for fact in restored.facts.values()})

    def test_state_export_without_audit_reimports_cleanly(self) -> None:
        engine = self._engine_with_state()
        envelope = json.loads(engine.export_state(include_audit=False))
        self.assertEqual(envelope["state"]["audit"], [])
        restored = UniversalBrainCore.from_state(json.dumps(envelope))
        self.assertEqual(restored.audit_trail, ())
        self.assertTrue(restored.inspect_integrity().valid)

    def test_rule_manifest_rejects_callback_markers_even_with_matching_digest(self) -> None:
        engine = self._engine_with_state()
        envelope = json.loads(engine.export_state())
        envelope["state"]["rule_manifest"][0]["action"] = "not-a-callback"
        state = envelope["state"]
        envelope["integrity"]["sha256"] = UniversalBrainCore._digest_payload(state)
        with self.assertRaises(EngineError):
            UniversalBrainCore.from_state(json.dumps(envelope))

    def test_atomic_batch_rejects_all_on_internal_or_existing_collision(self) -> None:
        engine = UniversalBrainCore()
        first = make_fact("Erster Fakt", 0.8, fact_id="first")
        duplicate = make_fact("  erster  fakt ", 0.9, fact_id="duplicate")
        self.assertEqual(engine.add_facts((first, duplicate)), ())
        self.assertFalse(engine.facts)

        engine.add_fact(make_fact("Geschützte Evidenz", 0.9, fact_id="protected"))
        inferior = make_fact("Geschützte Evidenz", 0.4, fact_id="inferior")
        independent = make_fact("Unabhängiger Fakt", 0.8, fact_id="independent")
        self.assertEqual(engine.add_facts((inferior, independent)), ())
        self.assertEqual(set(engine.facts), {"protected"})

    def test_atomic_batch_accepts_independent_facts(self) -> None:
        engine = UniversalBrainCore()
        accepted = engine.add_facts(
            (
                make_fact("Fakt A", 0.8, fact_id="a"),
                make_fact("Fakt B", 0.7, fact_id="b"),
            )
        )
        self.assertEqual(accepted, ("a", "b"))
        self.assertTrue(engine.inspect_integrity().valid)

    def test_explanations_expose_missing_sources_and_cycles_without_recursion_failure(self) -> None:
        engine = UniversalBrainCore()
        engine.add_fact(make_fact("Fakt mit externer Quelle", 0.8, fact_id="external", sources=("missing-source",)))
        missing_explanation = engine.explain_fact("external")
        self.assertTrue(missing_explanation.children[0].missing)

        engine.add_fact(make_fact("Zyklischer Fakt", 0.8, fact_id="cycle", sources=("cycle",)))
        cycle_explanation = engine.explain_fact("cycle", max_depth=4)
        self.assertTrue(cycle_explanation.children[0].cycle_detected)
        self.assertTrue(engine.explain_fact("cycle", max_depth=0).truncated)

    def test_internal_conflicts_and_integrity_report_are_explicit(self) -> None:
        engine = UniversalBrainCore()
        engine.add_fact(make_fact("Ventil ist offen.", 0.8, fact_id="open", claim="ventil", polarity=True))
        engine.add_fact(make_fact("Ventil ist geschlossen.", 0.7, fact_id="closed", claim="ventil", polarity=False))
        conflicts = engine.detect_internal_conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].true_fact_ids, ("open",))
        self.assertEqual(conflicts[0].false_fact_ids, ("closed",))
        report = engine.inspect_integrity()
        self.assertTrue(report.valid)
        self.assertEqual(report.fact_count, 2)

    def test_integrity_report_detects_corrupted_private_index_without_mutating_state(self) -> None:
        engine = UniversalBrainCore()
        engine.add_fact(make_fact("Indexierter Fakt", 0.8, fact_id="indexed", sources=("source",)))
        engine._source_index.clear()
        report = engine.inspect_integrity()
        self.assertFalse(report.valid)
        self.assertIn("source_index_mismatch", report.issues)


class MetaRuleTests(unittest.TestCase):
    def test_combinatorial_rule_generator_uses_unique_combinations(self) -> None:
        engine = UniversalBrainCore()
        for fact_id in ("a", "b", "c"):
            engine.add_fact(make_fact(f"Fakt {fact_id}", 0.8, fact_id=fact_id))

        def conclusion(premises: tuple[MindFact, ...]) -> MindFact:
            ids = tuple(fact.id for fact in premises)
            return make_fact(
                f"Kombination {'-'.join(ids)}",
                0.7,
                fact_id=f"combo-{'-'.join(ids)}",
                sources=ids,
            )

        rules = generate_combinatorial_rules("combo", ("a", "b", "c", "a"), conclusion, min_arity=2, max_arity=2)
        self.assertEqual(len(rules), 3)
        for rule in rules:
            engine.add_rule(rule)
        report = engine.run_inference(InferenceBudget(max_iterations=2, max_rule_applications=20))
        self.assertEqual(len(report.derived_fact_ids), 3)
        self.assertEqual(len([fact_id for fact_id in engine.facts if fact_id.startswith("combo-")]), 3)


if __name__ == "__main__":
    unittest.main()
