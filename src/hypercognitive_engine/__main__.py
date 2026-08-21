"""Kommandozeilen-Demo für die HyperCognitive Reasoning Engine."""

from __future__ import annotations

import argparse
from pathlib import Path

from .core import (
    GoalMetricProfile,
    InferenceBudget,
    SemanticDimensions,
    TeleologicalGoal,
    UniversalBrainCore,
    make_fact,
    make_implication_rule,
)


def build_demo_engine() -> UniversalBrainCore:
    """Baut ein kleines, vollständig lokales Szenario für die Inspektion auf."""
    engine = UniversalBrainCore()
    engine.add_goal(
        TeleologicalGoal(
            id="reliable-synthesis",
            description="Bevorzuge kohärente, epistemisch belastbare und neuartige Schlussfolgerungen.",
            metrics=GoalMetricProfile(novelty=0.15, coherence=0.35, predictability=0.35, emergence=0.15),
            weight=1.0,
        )
    )
    evidence = make_fact(
        "Sensor A meldet stabile Temperaturwerte.",
        0.90,
        fact_id="sensor-a-stable",
        dimensions=SemanticDimensions(epistemology=0.91, entropy=0.12, intensity=2.0, emergence=0.08),
        claim="Temperaturdaten sind stabil",
        polarity=True,
    )
    calibration = make_fact(
        "Die Sensor-Kalibrierung ist gültig.",
        0.88,
        fact_id="calibration-valid",
        dimensions=SemanticDimensions(epistemology=0.88, entropy=0.16, intensity=1.8, emergence=0.04),
        claim="Kalibrierung ist gültig",
        polarity=True,
    )
    engine.add_fact(evidence)
    engine.add_fact(calibration)
    engine.add_rule(
        make_implication_rule(
            "stable-data-rule",
            ("sensor-a-stable", "calibration-valid"),
            "Die beobachteten Temperaturdaten können als verlässlich behandelt werden.",
            certainty=0.82,
            claim="Temperaturdaten sind verlässlich",
            polarity=True,
            priority=10,
        )
    )
    return engine


def main() -> int:
    parser = argparse.ArgumentParser(description="Führt eine lokale HyperCognitive-Engine-Demo aus.")
    parser.add_argument("--export", type=Path, help="Optionaler Zielpfad für den JSON-Audit-Export.")
    args = parser.parse_args()

    engine = build_demo_engine()
    report = engine.run_inference(InferenceBudget(max_iterations=4, max_derived_facts=16, max_rule_applications=16))
    edges = engine.build_resonance_network(threshold=0.40)
    engine.propagate_resonance(edges, rate=0.05)
    branches = engine.explore_universes(top_facts_per_branch=4)
    synthesis = engine.synthesize_branches(branches, min_support=0.60)

    print("HyperCognitive Reasoning Engine – lokale Demonstration")
    print(f"Inferenz: {len(report.derived_fact_ids)} Ableitung(en), Stoppgrund: {report.stopped_reason}")
    print(f"Resonanz: {len(edges)} Kante(n)")
    print(f"Universen: {len(branches)} Zweige, Konsens: {len(synthesis.consensus)}, Konflikte: {len(synthesis.conflicts)}")
    for finding in synthesis.consensus:
        polarity = "unbestimmt" if finding.polarity is None else str(finding.polarity)
        print(f"  - [{finding.support_ratio:.0%}; {polarity}] {finding.content}")

    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(engine.export_audit(), encoding="utf-8")
        print(f"Audit-Export: {args.export}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
