"""Deterministische neuro-symbolische Reasoning-Engine.

Die Implementierung arbeitet ausschließlich mit explizit registrierten Fakten und
vertrauenswürdigen, vom Integrator bereitgestellten Regel-Callbacks. Sie führt weder
Code aus Texten aus noch löst sie externe Aktionen aus.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from enum import Enum
from hashlib import sha256
from hmac import compare_digest
from itertools import combinations
import json
import math
import re
from threading import RLock
from time import monotonic, time
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from uuid import uuid4

MAX_INTENSITY = 1e12
STATE_SCHEMA = "hypercognitive-engine-state/1"


class EngineError(RuntimeError):
    """Basisklasse für kontrollierte Fehler der Engine."""


class AxiomParadigm(str, Enum):
    """Bewertungsparadigmen für voneinander isolierte Denkzweige."""

    STANDARD = "standard"
    OBSERVATION_FIRST = "observation_first"
    LOGIC_FIRST = "logic_first"
    CHAOS_FIRST = "chaos_first"
    TRANSCENDENT = "transcendent"


def _finite_number(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} muss eine endliche Zahl sein.")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{label} muss endlich sein.")
    return numeric


def _unit_interval(value: float, label: str) -> float:
    numeric = _finite_number(value, label)
    if not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{label} muss im Intervall [0, 1] liegen.")
    return numeric


def _canonical(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold())


def _stable_id(prefix: str, *parts: str) -> str:
    material = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{sha256(material).hexdigest()[:20]}"


@dataclass(frozen=True, slots=True)
class SemanticDimensions:
    """Normierte Koordinaten eines diskreten kognitiven Zustands."""

    epistemology: float = 0.5
    entropy: float = 0.5
    intensity: float = 1.0
    emergence: float = 0.0
    goal_alignment: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(self, "epistemology", _unit_interval(self.epistemology, "epistemology"))
        object.__setattr__(self, "entropy", _unit_interval(self.entropy, "entropy"))
        object.__setattr__(self, "emergence", _unit_interval(self.emergence, "emergence"))
        object.__setattr__(self, "goal_alignment", _unit_interval(self.goal_alignment, "goal_alignment"))
        intensity = _finite_number(self.intensity, "intensity")
        if not 1.0 <= intensity <= MAX_INTENSITY:
            raise ValueError(f"intensity muss im Intervall [1, {MAX_INTENSITY:g}] liegen.")
        object.__setattr__(self, "intensity", intensity)

    def with_intensity(self, intensity: float, *, cap: float = MAX_INTENSITY) -> "SemanticDimensions":
        cap = _finite_number(cap, "cap")
        if cap < 1.0:
            raise ValueError("cap muss mindestens 1 sein.")
        return replace(self, intensity=max(1.0, min(cap, _finite_number(intensity, "intensity"))))


@dataclass(frozen=True, slots=True)
class MindFact:
    """Unveränderlicher Fakt mit semantischen Dimensionen und Herkunftsreferenzen."""

    id: str
    content: str
    certainty: float
    dimensions: SemanticDimensions = field(default_factory=SemanticDimensions)
    generation: int = 0
    sources: tuple[str, ...] = field(default_factory=tuple)
    timestamp: float = field(default_factory=time)
    claim: Optional[str] = None
    polarity: Optional[bool] = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("fact.id darf nicht leer sein.")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("fact.content darf nicht leer sein.")
        object.__setattr__(self, "certainty", _unit_interval(self.certainty, "certainty"))
        if not isinstance(self.dimensions, SemanticDimensions):
            raise ValueError("dimensions muss SemanticDimensions sein.")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 0:
            raise ValueError("generation muss eine nichtnegative Ganzzahl sein.")
        timestamp = _finite_number(self.timestamp, "timestamp")
        if timestamp < 0:
            raise ValueError("timestamp darf nicht negativ sein.")
        object.__setattr__(self, "timestamp", timestamp)
        if self.claim is not None and (not isinstance(self.claim, str) or not self.claim.strip()):
            raise ValueError("claim muss entweder None oder ein nichtleerer Text sein.")
        if self.polarity is not None and not isinstance(self.polarity, bool):
            raise ValueError("polarity muss True, False oder None sein.")
        normalized_sources = tuple(dict.fromkeys(self.sources))
        if any(not isinstance(source, str) or not source.strip() for source in normalized_sources):
            raise ValueError("sources darf nur nichtleere String-IDs enthalten.")
        object.__setattr__(self, "sources", normalized_sources)

    @property
    def semantic_key(self) -> tuple[str, Optional[bool]]:
        """Schlüssel für semantische Deduplizierung und Konflikterkennung."""
        return (_canonical(self.claim if self.claim is not None else self.content), self.polarity)

    def with_dimensions(self, dimensions: SemanticDimensions) -> "MindFact":
        return replace(self, dimensions=dimensions)


@dataclass(frozen=True, slots=True)
class GoalMetricProfile:
    """Nichtnegative Gewichtung der Zielbewertung."""

    novelty: float = 0.25
    coherence: float = 0.25
    predictability: float = 0.25
    emergence: float = 0.25

    def __post_init__(self) -> None:
        for name in ("novelty", "coherence", "predictability", "emergence"):
            value = _finite_number(getattr(self, name), name)
            if value < 0.0:
                raise ValueError(f"{name} darf nicht negativ sein.")
            object.__setattr__(self, name, value)

    @property
    def total(self) -> float:
        return self.novelty + self.coherence + self.predictability + self.emergence


@dataclass(frozen=True, slots=True)
class TeleologicalGoal:
    """Unveränderliches Ziel, das die Bewertung eines Faktenraums ausrichtet."""

    id: str
    description: str
    metrics: GoalMetricProfile = field(default_factory=GoalMetricProfile)
    weight: float = 1.0
    satisfied: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("goal.id darf nicht leer sein.")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("goal.description darf nicht leer sein.")
        if not isinstance(self.metrics, GoalMetricProfile):
            raise ValueError("metrics muss GoalMetricProfile sein.")
        weight = _finite_number(self.weight, "goal.weight")
        if weight < 0.0:
            raise ValueError("goal.weight darf nicht negativ sein.")
        object.__setattr__(self, "weight", weight)


RuleCondition = Callable[[Sequence[MindFact]], bool]
RuleAction = Callable[[Sequence[MindFact]], Sequence[MindFact]]


@dataclass(slots=True)
class CognitiveRule:
    """Regel mit expliziter Bedingung, Aktion und stabiler Ausführungspriorität."""

    id: str
    condition: RuleCondition
    action: RuleAction
    priority: int = 0
    efficacy: float = 0.5
    generation: int = 0
    last_used: float = 0.0
    execution_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("rule.id darf nicht leer sein.")
        if not callable(self.condition) or not callable(self.action):
            raise ValueError("condition und action müssen aufrufbar sein.")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ValueError("priority muss eine Ganzzahl sein.")
        self.efficacy = _unit_interval(self.efficacy, "efficacy")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 0:
            raise ValueError("rule.generation muss nichtnegativ sein.")

    def execute(self, facts: Sequence[MindFact]) -> tuple[MindFact, ...]:
        """Wendet die Regel an und stellt den Rückgabetyp sicher."""
        if not self.condition(facts):
            return ()
        results = tuple(self.action(facts))
        if any(not isinstance(fact, MindFact) for fact in results):
            raise EngineError(f"Regel {self.id!r} hat einen Nicht-MindFact zurückgegeben.")
        self.last_used = time()
        self.execution_count += 1
        if results:
            self.efficacy = min(1.0, self.efficacy + 0.02)
        return results


@dataclass(frozen=True, slots=True)
class InferenceBudget:
    """Harte Ressourcenobergrenzen für einen einzelnen Inferenzdurchlauf."""

    max_iterations: int = 8
    max_derived_facts: int = 128
    max_rule_applications: int = 256
    max_seconds: Optional[float] = 2.0

    def __post_init__(self) -> None:
        for name in ("max_iterations", "max_derived_facts", "max_rule_applications"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} muss eine positive Ganzzahl sein.")
        if self.max_seconds is not None and _finite_number(self.max_seconds, "max_seconds") <= 0:
            raise ValueError("max_seconds muss positiv oder None sein.")


@dataclass(frozen=True, slots=True)
class DerivationRecord:
    fact_id: str
    rule_id: str
    parent_ids: tuple[str, ...]
    run_id: str
    generation: int
    created_at: float


@dataclass(frozen=True, slots=True)
class AuditEvent:
    sequence: int
    kind: str
    timestamp: float
    data: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class InferenceReport:
    run_id: str
    iterations: int
    rule_applications: int
    derived_fact_ids: tuple[str, ...]
    stopped_reason: str
    errors: tuple[str, ...]
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class ResonanceEdge:
    fact_a: str
    fact_b: str
    weight: float


@dataclass(frozen=True, slots=True)
class BranchFinding:
    branch_id: str
    fact_id: str
    content: str
    claim_key: str
    polarity: Optional[bool]
    score: float


@dataclass(frozen=True, slots=True)
class UniverseBranch:
    id: str
    paradigm: AxiomParadigm
    facts: tuple[MindFact, ...]
    findings: tuple[BranchFinding, ...]
    score: float


@dataclass(frozen=True, slots=True)
class SynthesisFinding:
    claim_key: str
    polarity: Optional[bool]
    content: str
    support_ratio: float
    mean_score: float
    branch_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Conflict:
    claim_key: str
    polarities: tuple[bool, bool]
    branch_ids: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    consensus: tuple[SynthesisFinding, ...]
    conflicts: tuple[Conflict, ...]
    branch_count: int
    min_support: float


@dataclass(frozen=True, slots=True)
class FactConflict:
    """Gegensätzliche explizite Polaritäten innerhalb desselben Faktenraums."""

    claim_key: str
    true_fact_ids: tuple[str, ...]
    false_fact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExplanationNode:
    """Begrenzter, zyklussicherer Knoten eines Faktenerklärungsbaums."""

    fact_id: str
    content: Optional[str]
    generation: Optional[int]
    rule_id: Optional[str]
    source_ids: tuple[str, ...]
    children: tuple["ExplanationNode", ...]
    missing: bool = False
    truncated: bool = False
    cycle_detected: bool = False


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """Nichtmutierender Konsistenz- und Integritätsbefund eines Engine-Zustands."""

    valid: bool
    state_digest: str
    issues: tuple[str, ...]
    fact_count: int
    goal_count: int
    derivation_count: int
    audit_event_count: int


class UniversalBrainCore:
    """Thread-sichere Kernengine mit nachvollziehbarer, begrenzter Inferenz."""

    def __init__(self, *, max_intensity: float = MAX_INTENSITY) -> None:
        max_intensity = _finite_number(max_intensity, "max_intensity")
        if max_intensity < 1.0 or max_intensity > MAX_INTENSITY:
            raise ValueError(f"max_intensity muss im Intervall [1, {MAX_INTENSITY:g}] liegen.")
        self._max_intensity = max_intensity
        self._facts: dict[str, MindFact] = {}
        self._rules: dict[str, CognitiveRule] = {}
        self._goals: dict[str, TeleologicalGoal] = {}
        self._source_index: defaultdict[str, set[str]] = defaultdict(set)
        self._semantic_index: dict[tuple[str, Optional[bool]], str] = {}
        self._derivations: dict[str, DerivationRecord] = {}
        self._audit: list[AuditEvent] = []
        # Deklaratives Regelmanifest aus Imports; es enthält niemals ausführbare Callbacks.
        self._imported_rule_manifest: dict[str, Mapping[str, Any]] = {}
        self._generation = 0
        self._revision = 0
        self._lock = RLock()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    @property
    def facts(self) -> Mapping[str, MindFact]:
        with self._lock:
            return MappingProxyType(dict(self._facts))

    @property
    def rules(self) -> Mapping[str, CognitiveRule]:
        with self._lock:
            # Kopien verhindern, dass Aufrufer Priorität oder Efficacy interner Regeln mutieren.
            return MappingProxyType({rule_id: replace(rule) for rule_id, rule in self._rules.items()})

    @property
    def rule_manifest(self) -> Mapping[str, Mapping[str, Any]]:
        """Deklarative Regelmetadaten; Callbacks werden bewusst nie offengelegt oder serialisiert."""
        with self._lock:
            manifest = {rule_id: dict(metadata) for rule_id, metadata in self._imported_rule_manifest.items()}
            for rule_id, rule in self._rules.items():
                manifest[rule_id] = {
                    "id": rule.id,
                    "priority": rule.priority,
                    "efficacy": rule.efficacy,
                    "generation": rule.generation,
                    "execution_count": rule.execution_count,
                    "last_used": rule.last_used,
                    "registered": True,
                }
            return MappingProxyType({key: MappingProxyType(dict(manifest[key])) for key in sorted(manifest)})

    @property
    def goals(self) -> tuple[TeleologicalGoal, ...]:
        with self._lock:
            return tuple(self._goals[key] for key in sorted(self._goals))

    @property
    def audit_trail(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._audit)

    @property
    def derivations(self) -> Mapping[str, DerivationRecord]:
        with self._lock:
            return MappingProxyType(dict(self._derivations))

    def _record(self, kind: str, **data: Any) -> None:
        self._audit.append(AuditEvent(len(self._audit) + 1, kind, time(), MappingProxyType(dict(data))))

    @staticmethod
    def _dimension_score(dimensions: SemanticDimensions, metrics: GoalMetricProfile) -> float:
        if metrics.total == 0.0:
            return 0.5
        weighted = (
            dimensions.emergence * metrics.novelty
            + (1.0 - dimensions.entropy) * metrics.coherence
            + dimensions.epistemology * metrics.predictability
            + dimensions.emergence * metrics.emergence
        )
        return max(0.0, min(1.0, weighted / metrics.total))

    def compute_goal_alignment(self, fact: MindFact) -> float:
        return self._goal_alignment_for_dimensions(fact.dimensions)

    def _goal_alignment_for_dimensions(self, dimensions: SemanticDimensions) -> float:
        active = [goal for goal in self._goals.values() if not goal.satisfied and goal.weight > 0.0]
        if not active:
            return max(
                0.0,
                min(
                    1.0,
                    dimensions.emergence * 0.35
                    + (1.0 - dimensions.entropy) * 0.35
                    + dimensions.epistemology * 0.30,
                ),
            )
        total_weight = sum(goal.weight for goal in active)
        return max(
            0.0,
            min(
                1.0,
                sum(self._dimension_score(dimensions, goal.metrics) * goal.weight for goal in active) / total_weight,
            ),
        )

    def _with_current_alignment(self, fact: MindFact) -> MindFact:
        dims = fact.dimensions
        aligned = self._goal_alignment_for_dimensions(dims)
        if math.isclose(aligned, dims.goal_alignment, abs_tol=1e-12):
            return fact
        return fact.with_dimensions(replace(dims, goal_alignment=aligned))

    def _index_fact(self, fact: MindFact) -> None:
        self._semantic_index[fact.semantic_key] = fact.id
        for source in fact.sources:
            self._source_index[source].add(fact.id)

    def _deindex_fact(self, fact: MindFact) -> None:
        if self._semantic_index.get(fact.semantic_key) == fact.id:
            del self._semantic_index[fact.semantic_key]
        for source in fact.sources:
            ids = self._source_index.get(source)
            if ids is not None:
                ids.discard(fact.id)
                if not ids:
                    del self._source_index[source]

    def add_goal(self, goal: TeleologicalGoal) -> None:
        with self._lock:
            if goal.id in self._goals:
                raise ValueError(f"Ziel {goal.id!r} ist bereits registriert.")
            self._goals[goal.id] = goal
            self._realign_all_facts()
            self._revision += 1
            self._record("goal_added", goal_id=goal.id)

    def set_goal_satisfied(self, goal_id: str, satisfied: bool = True) -> None:
        with self._lock:
            if goal_id not in self._goals:
                raise KeyError(f"Unbekanntes Ziel: {goal_id}")
            if not isinstance(satisfied, bool):
                raise ValueError("satisfied muss bool sein.")
            self._goals[goal_id] = replace(self._goals[goal_id], satisfied=satisfied)
            self._realign_all_facts()
            self._revision += 1
            self._record("goal_status_changed", goal_id=goal_id, satisfied=satisfied)

    def _realign_all_facts(self) -> None:
        for fact_id, fact in tuple(self._facts.items()):
            self._facts[fact_id] = self._with_current_alignment(fact)

    def add_fact(self, fact: MindFact) -> bool:
        """Registriert einen Fakt, sofern ID und semantischer Inhalt neu oder überlegen sind."""
        with self._lock:
            return self._ingest_fact(fact, origin="external")

    def add_facts(self, facts: Iterable[MindFact], *, atomic: bool = True) -> tuple[str, ...]:
        """Nimmt mehrere Fakten auf; im atomaren Modus wird kein Teilzustand übernommen."""
        incoming = tuple(facts)
        if any(not isinstance(fact, MindFact) for fact in incoming):
            raise ValueError("Nur MindFact-Instanzen können registriert werden.")
        if not incoming:
            return ()
        with self._lock:
            if not atomic:
                return tuple(fact.id for fact in incoming if self._ingest_fact(fact, origin="batch"))
            aligned = tuple(self._with_current_alignment(fact) for fact in incoming)
            ids = [fact.id for fact in aligned]
            semantic_keys = [fact.semantic_key for fact in aligned]
            if len(set(ids)) != len(ids) or len(set(semantic_keys)) != len(semantic_keys):
                self._record("batch_rejected", reason="duplicate_within_batch", count=len(aligned))
                return ()
            for fact in aligned:
                competitors = [existing for existing in (self._facts.get(fact.id), self._facts.get(self._semantic_index.get(fact.semantic_key, ""))) if existing is not None]
                if any(self._quality(existing) >= self._quality(fact) for existing in competitors):
                    self._record("batch_rejected", reason="existing_fact_not_inferior", fact_id=fact.id, count=len(aligned))
                    return ()
            accepted = tuple(fact.id for fact in aligned if self._ingest_fact(fact, origin="batch"))
            if len(accepted) != len(aligned):
                raise EngineError("Atomare Stapelaufnahme konnte nicht vollständig übernommen werden.")
            self._record("batch_added", fact_ids=list(accepted), count=len(accepted))
            return accepted

    def _quality(self, fact: MindFact) -> float:
        return fact.certainty * 0.65 + fact.dimensions.goal_alignment * 0.35

    def _ingest_fact(self, fact: MindFact, *, origin: str) -> bool:
        if not isinstance(fact, MindFact):
            raise ValueError("Nur MindFact-Instanzen können registriert werden.")
        fact = self._with_current_alignment(fact)
        existing_by_id = self._facts.get(fact.id)
        semantic_id = self._semantic_index.get(fact.semantic_key)
        existing_semantic = self._facts.get(semantic_id) if semantic_id is not None else None

        if existing_by_id is not None:
            competitors = [existing_by_id]
            if existing_semantic is not None and existing_semantic.id != existing_by_id.id:
                competitors.append(existing_semantic)
            if any(self._quality(existing) >= self._quality(fact) for existing in competitors):
                self._record("fact_rejected", fact_id=fact.id, reason="id_or_semantic_not_superior", origin=origin)
                return False
            for existing in competitors:
                self._deindex_fact(existing)
                self._facts.pop(existing.id, None)
                self._derivations.pop(existing.id, None)
                if existing.id != fact.id:
                    self._record("fact_superseded", old_fact_id=existing.id, new_fact_id=fact.id, origin=origin)
            self._facts[fact.id] = fact
            self._index_fact(fact)
            self._revision += 1
            self._record("fact_replaced", fact_id=fact.id, origin=origin)
            return True

        if existing_semantic is not None:
            if self._quality(existing_semantic) >= self._quality(fact):
                self._record("fact_rejected", fact_id=fact.id, reason="semantic_duplicate", origin=origin)
                return False
            self._deindex_fact(existing_semantic)
            del self._facts[existing_semantic.id]
            self._derivations.pop(existing_semantic.id, None)
            self._record("fact_superseded", old_fact_id=existing_semantic.id, new_fact_id=fact.id, origin=origin)

        self._facts[fact.id] = fact
        self._index_fact(fact)
        self._generation = max(self._generation, fact.generation)
        self._revision += 1
        self._record("fact_added", fact_id=fact.id, origin=origin)
        return True

    def add_rule(self, rule: CognitiveRule) -> None:
        with self._lock:
            if rule.id in self._rules:
                raise ValueError(f"Regel {rule.id!r} ist bereits registriert.")
            self._rules[rule.id] = rule
            self._imported_rule_manifest.pop(rule.id, None)
            self._revision += 1
            self._record("rule_added", rule_id=rule.id)

    def remove_rule(self, rule_id: str) -> None:
        with self._lock:
            if rule_id not in self._rules:
                raise KeyError(f"Unbekannte Regel: {rule_id}")
            del self._rules[rule_id]
            self._revision += 1
            self._record("rule_removed", rule_id=rule_id)

    def _ordered_rules(self) -> tuple[CognitiveRule, ...]:
        return tuple(sorted(self._rules.values(), key=lambda rule: (-rule.priority, -rule.efficacy, rule.id)))

    def _prepare_derivation(
        self,
        candidate: MindFact,
        *,
        rule_id: str,
        input_facts: Sequence[MindFact],
        run_id: str,
    ) -> tuple[MindFact, DerivationRecord]:
        available = {fact.id: fact for fact in input_facts}
        parent_ids = tuple(source for source in candidate.sources if source in available)
        if not parent_ids:
            parent_ids = tuple(sorted(available))
        parent_generation = max((available[parent].generation for parent in parent_ids), default=-1)
        generation = max(candidate.generation, parent_generation + 1)
        prepared = replace(candidate, generation=generation, sources=parent_ids, timestamp=time())
        prepared = self._with_current_alignment(prepared)
        return prepared, DerivationRecord(
            fact_id=prepared.id,
            rule_id=rule_id,
            parent_ids=parent_ids,
            run_id=run_id,
            generation=generation,
            created_at=prepared.timestamp,
        )

    def run_inference(self, budget: InferenceBudget = InferenceBudget()) -> InferenceReport:
        """Führt Regeln in einer stabilen Reihenfolge bis zum Fixpunkt oder Budgetlimit aus."""
        if not isinstance(budget, InferenceBudget):
            raise ValueError("budget muss InferenceBudget sein.")
        with self._lock:
            run_id = uuid4().hex
            started = monotonic()
            derived: list[str] = []
            errors: list[str] = []
            applications = 0
            iterations = 0
            stopped_reason = "fixed_point"

            for iteration in range(1, budget.max_iterations + 1):
                iterations = iteration
                changed = False
                for rule in self._ordered_rules():
                    if applications >= budget.max_rule_applications:
                        stopped_reason = "rule_application_budget"
                        break
                    if len(derived) >= budget.max_derived_facts:
                        stopped_reason = "derived_fact_budget"
                        break
                    if budget.max_seconds is not None and monotonic() - started >= budget.max_seconds:
                        stopped_reason = "time_budget"
                        break
                    snapshot = tuple(self._facts[fact_id] for fact_id in sorted(self._facts))
                    try:
                        candidates = rule.execute(snapshot)
                        applications += 1
                    except Exception as exc:  # kontrolliert protokollierte Fehler in Integratorregeln
                        message = f"{rule.id}: {type(exc).__name__}: {exc}"
                        errors.append(message)
                        self._record("rule_error", rule_id=rule.id, error=message, run_id=run_id)
                        continue
                    for candidate in candidates:
                        if len(derived) >= budget.max_derived_facts:
                            stopped_reason = "derived_fact_budget"
                            break
                        prepared, record = self._prepare_derivation(
                            candidate, rule_id=rule.id, input_facts=snapshot, run_id=run_id
                        )
                        if self._ingest_fact(prepared, origin=f"rule:{rule.id}"):
                            self._derivations[prepared.id] = record
                            derived.append(prepared.id)
                            changed = True
                            self._record(
                                "derivation_added",
                                fact_id=prepared.id,
                                rule_id=rule.id,
                                parent_ids=list(record.parent_ids),
                                run_id=run_id,
                            )
                    if stopped_reason != "fixed_point":
                        break
                if stopped_reason != "fixed_point":
                    break
                if not changed:
                    break
            else:
                stopped_reason = "iteration_budget"

            duration = monotonic() - started
            report = InferenceReport(
                run_id=run_id,
                iterations=iterations,
                rule_applications=applications,
                derived_fact_ids=tuple(derived),
                stopped_reason=stopped_reason,
                errors=tuple(errors),
                duration_seconds=duration,
            )
            self._record("inference_completed", run_id=run_id, stopped_reason=stopped_reason, derived=len(derived))
            return report

    @staticmethod
    def _content_similarity(a: str, b: str) -> float:
        tokens_a = set(re.findall(r"[\w-]+", a.casefold()))
        tokens_b = set(re.findall(r"[\w-]+", b.casefold()))
        if not tokens_a and not tokens_b:
            return 1.0
        if not tokens_a or not tokens_b:
            return 0.0
        return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)

    @classmethod
    def _resonance_weight(cls, a: MindFact, b: MindFact) -> float:
        da, db = a.dimensions, b.dimensions
        dimensional = (
            1.0 - abs(da.epistemology - db.epistemology)
            + 1.0 - abs(da.entropy - db.entropy)
            + 1.0 - abs(da.emergence - db.emergence)
            + 1.0 - abs(da.goal_alignment - db.goal_alignment)
        ) / 4.0
        intensity = min(da.intensity, db.intensity) / max(da.intensity, db.intensity)
        lexical = cls._content_similarity(a.content, b.content)
        return max(0.0, min(1.0, dimensional * 0.60 + intensity * 0.20 + lexical * 0.20))

    def build_resonance_network(self, *, threshold: float = 0.55, max_edges: int = 1_000) -> tuple[ResonanceEdge, ...]:
        threshold = _unit_interval(threshold, "threshold")
        if isinstance(max_edges, bool) or not isinstance(max_edges, int) or max_edges < 1:
            raise ValueError("max_edges muss eine positive Ganzzahl sein.")
        with self._lock:
            facts = tuple(self._facts[fact_id] for fact_id in sorted(self._facts))
            edges: list[ResonanceEdge] = []
            for a, b in combinations(facts, 2):
                weight = self._resonance_weight(a, b)
                if weight >= threshold:
                    edges.append(ResonanceEdge(a.id, b.id, weight))
            edges.sort(key=lambda edge: (-edge.weight, edge.fact_a, edge.fact_b))
            result = tuple(edges[:max_edges])
            self._record("resonance_built", edge_count=len(result), threshold=threshold)
            return result

    def propagate_resonance(
        self,
        edges: Sequence[ResonanceEdge],
        *,
        rate: float = 0.10,
        steps: int = 1,
    ) -> tuple[str, ...]:
        rate = _unit_interval(rate, "rate")
        if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
            raise ValueError("steps muss eine positive Ganzzahl sein.")
        with self._lock:
            valid_edges = tuple(
                edge for edge in edges if edge.fact_a in self._facts and edge.fact_b in self._facts and edge.fact_a != edge.fact_b
            )
            updated: set[str] = set()
            for _ in range(steps):
                deltas: defaultdict[str, float] = defaultdict(float)
                for edge in valid_edges:
                    a = self._facts[edge.fact_a]
                    b = self._facts[edge.fact_b]
                    deltas[a.id] += rate * edge.weight * b.dimensions.intensity
                    deltas[b.id] += rate * edge.weight * a.dimensions.intensity
                for fact_id, delta in deltas.items():
                    fact = self._facts[fact_id]
                    dimensions = fact.dimensions.with_intensity(fact.dimensions.intensity + delta, cap=self._max_intensity)
                    if not math.isclose(dimensions.intensity, fact.dimensions.intensity, abs_tol=1e-12):
                        self._facts[fact_id] = fact.with_dimensions(dimensions)
                        updated.add(fact_id)
            if updated:
                self._revision += 1
            self._record("resonance_propagated", updated_ids=sorted(updated), steps=steps, rate=rate)
            return tuple(sorted(updated))

    @staticmethod
    def _paradigm_dimensions(dimensions: SemanticDimensions, paradigm: AxiomParadigm) -> SemanticDimensions:
        shifts: dict[AxiomParadigm, tuple[float, float, float, float, float]] = {
            AxiomParadigm.STANDARD: (0.0, 0.0, 1.0, 0.0, 0.0),
            AxiomParadigm.OBSERVATION_FIRST: (0.08, -0.03, 1.00, -0.02, 0.02),
            AxiomParadigm.LOGIC_FIRST: (0.16, -0.14, 0.95, 0.02, 0.05),
            AxiomParadigm.CHAOS_FIRST: (-0.12, 0.22, 1.10, 0.20, -0.04),
            AxiomParadigm.TRANSCENDENT: (0.05, 0.03, 1.04, 0.24, 0.14),
        }
        de, dentropy, intensity_multiplier, dem, dgoal = shifts[paradigm]
        return SemanticDimensions(
            epistemology=max(0.0, min(1.0, dimensions.epistemology + de)),
            entropy=max(0.0, min(1.0, dimensions.entropy + dentropy)),
            intensity=max(1.0, min(MAX_INTENSITY, dimensions.intensity * intensity_multiplier)),
            emergence=max(0.0, min(1.0, dimensions.emergence + dem)),
            goal_alignment=max(0.0, min(1.0, dimensions.goal_alignment + dgoal)),
        )

    def explore_universes(
        self,
        paradigms: Iterable[AxiomParadigm] = tuple(AxiomParadigm),
        *,
        top_facts_per_branch: int = 10,
    ) -> tuple[UniverseBranch, ...]:
        if isinstance(top_facts_per_branch, bool) or not isinstance(top_facts_per_branch, int) or top_facts_per_branch < 1:
            raise ValueError("top_facts_per_branch muss eine positive Ganzzahl sein.")
        normalized = tuple(dict.fromkeys(AxiomParadigm(paradigm) for paradigm in paradigms))
        if not normalized:
            raise ValueError("Mindestens ein Paradigma ist erforderlich.")
        with self._lock:
            source_facts = tuple(self._facts[fact_id] for fact_id in sorted(self._facts))
            branches: list[UniverseBranch] = []
            for paradigm in normalized:
                projected: list[MindFact] = []
                for fact in source_facts:
                    dimensions = self._paradigm_dimensions(fact.dimensions, paradigm)
                    dimensions = replace(dimensions, goal_alignment=self._goal_alignment_for_dimensions(dimensions))
                    projected.append(fact.with_dimensions(dimensions))
                ranked = sorted(
                    projected,
                    key=lambda fact: (
                        -(fact.certainty * 0.40 + fact.dimensions.goal_alignment * 0.35 + fact.dimensions.epistemology * 0.15 + fact.dimensions.emergence * 0.10),
                        fact.id,
                    ),
                )
                selected = ranked[:top_facts_per_branch]
                branch_id = f"{paradigm.value}:{self._revision}"
                findings = tuple(
                    BranchFinding(
                        branch_id=branch_id,
                        fact_id=fact.id,
                        content=fact.content,
                        claim_key=fact.semantic_key[0],
                        polarity=fact.polarity,
                        score=fact.certainty * 0.40
                        + fact.dimensions.goal_alignment * 0.35
                        + fact.dimensions.epistemology * 0.15
                        + fact.dimensions.emergence * 0.10,
                    )
                    for fact in selected
                )
                branch_score = sum(finding.score for finding in findings) / len(findings) if findings else 0.0
                branches.append(UniverseBranch(branch_id, paradigm, tuple(projected), findings, branch_score))
            self._record("universes_explored", branch_count=len(branches), fact_count=len(source_facts))
            return tuple(branches)

    def synthesize_branches(self, branches: Sequence[UniverseBranch], *, min_support: float = 0.60) -> SynthesisResult:
        min_support = _unit_interval(min_support, "min_support")
        if not branches:
            raise ValueError("Für eine Synthese ist mindestens ein Zweig erforderlich.")
        branch_ids = {branch.id for branch in branches}
        if len(branch_ids) != len(branches):
            raise ValueError("Zweig-IDs müssen eindeutig sein.")
        grouped: defaultdict[tuple[str, Optional[bool]], list[BranchFinding]] = defaultdict(list)
        for branch in branches:
            grouped_entries: set[tuple[str, Optional[bool], str]] = set()
            for finding in branch.findings:
                if finding.branch_id != branch.id:
                    raise ValueError("Jedes BranchFinding muss die ID seines enthaltenden Zweigs tragen.")
                marker = (finding.claim_key, finding.polarity, finding.fact_id)
                if marker not in grouped_entries:
                    grouped[(finding.claim_key, finding.polarity)].append(finding)
                    grouped_entries.add(marker)

        consensus: list[SynthesisFinding] = []
        support_by_claim: defaultdict[str, dict[bool, set[str]]] = defaultdict(lambda: defaultdict(set))
        for (claim_key, polarity), findings in grouped.items():
            # Mehrere, gleichlautende Funde eines Zweigs dürfen dessen Votum nicht übergewichten.
            best_per_branch: dict[str, BranchFinding] = {}
            for finding in findings:
                previous = best_per_branch.get(finding.branch_id)
                if previous is None or (finding.score, finding.content, finding.fact_id) > (
                    previous.score,
                    previous.content,
                    previous.fact_id,
                ):
                    best_per_branch[finding.branch_id] = finding
            representative_findings = tuple(best_per_branch[branch_id] for branch_id in sorted(best_per_branch))
            participating = tuple(finding.branch_id for finding in representative_findings)
            if polarity is not None:
                support_by_claim[claim_key][polarity].update(participating)
            support = len(participating) / len(branches)
            if support >= min_support:
                best_content = min(
                    representative_findings, key=lambda finding: (-finding.score, finding.content, finding.fact_id)
                ).content
                consensus.append(
                    SynthesisFinding(
                        claim_key=claim_key,
                        polarity=polarity,
                        content=best_content,
                        support_ratio=support,
                        mean_score=sum(finding.score for finding in representative_findings) / len(representative_findings),
                        branch_ids=participating,
                        fact_ids=tuple(sorted({finding.fact_id for finding in findings})),
                    )
                )
        consensus.sort(key=lambda item: (-item.support_ratio, -item.mean_score, item.claim_key, str(item.polarity)))

        conflicts: list[Conflict] = []
        for claim_key, polarities in support_by_claim.items():
            if True in polarities and False in polarities:
                conflict_branches = tuple(sorted(polarities[True] | polarities[False]))
                conflicts.append(
                    Conflict(
                        claim_key=claim_key,
                        polarities=(False, True),
                        branch_ids=conflict_branches,
                        description="Explizit gegensätzliche Polaritäten wurden für dieselbe Behauptung gefunden.",
                    )
                )
        conflicts.sort(key=lambda conflict: conflict.claim_key)
        result = SynthesisResult(tuple(consensus), tuple(conflicts), len(branches), min_support)
        with self._lock:
            self._record("branches_synthesized", branch_count=len(branches), consensus=len(consensus), conflicts=len(conflicts))
        return result

    @staticmethod
    def _fact_payload(fact: MindFact) -> dict[str, Any]:
        return {
            "id": fact.id,
            "content": fact.content,
            "certainty": fact.certainty,
            "dimensions": {
                "epistemology": fact.dimensions.epistemology,
                "entropy": fact.dimensions.entropy,
                "intensity": fact.dimensions.intensity,
                "emergence": fact.dimensions.emergence,
                "goal_alignment": fact.dimensions.goal_alignment,
            },
            "generation": fact.generation,
            "sources": list(fact.sources),
            "timestamp": fact.timestamp,
            "claim": fact.claim,
            "polarity": fact.polarity,
        }

    @staticmethod
    def _fact_from_payload(payload: Mapping[str, Any]) -> MindFact:
        if not isinstance(payload, Mapping):
            raise EngineError("Ein serialisierter Fakt muss ein Mapping sein.")
        dimensions = payload.get("dimensions")
        if not isinstance(dimensions, Mapping):
            raise EngineError("Ein serialisierter Fakt benötigt dimensions als Mapping.")
        sources = payload.get("sources", ())
        if not isinstance(sources, list):
            raise EngineError("Ein serialisierter Fakt benötigt sources als Liste.")
        return MindFact(
            id=payload.get("id"),
            content=payload.get("content"),
            certainty=payload.get("certainty"),
            dimensions=SemanticDimensions(
                epistemology=dimensions.get("epistemology"),
                entropy=dimensions.get("entropy"),
                intensity=dimensions.get("intensity"),
                emergence=dimensions.get("emergence"),
                goal_alignment=dimensions.get("goal_alignment"),
            ),
            generation=payload.get("generation", 0),
            sources=tuple(sources),
            timestamp=payload.get("timestamp"),
            claim=payload.get("claim"),
            polarity=payload.get("polarity"),
        )

    @staticmethod
    def _goal_payload(goal: TeleologicalGoal) -> dict[str, Any]:
        return {
            "id": goal.id,
            "description": goal.description,
            "weight": goal.weight,
            "satisfied": goal.satisfied,
            "metrics": {
                "novelty": goal.metrics.novelty,
                "coherence": goal.metrics.coherence,
                "predictability": goal.metrics.predictability,
                "emergence": goal.metrics.emergence,
            },
        }

    @staticmethod
    def _goal_from_payload(payload: Mapping[str, Any]) -> TeleologicalGoal:
        if not isinstance(payload, Mapping):
            raise EngineError("Ein serialisiertes Ziel muss ein Mapping sein.")
        metrics = payload.get("metrics")
        if not isinstance(metrics, Mapping):
            raise EngineError("Ein serialisiertes Ziel benötigt metrics als Mapping.")
        return TeleologicalGoal(
            id=payload.get("id"),
            description=payload.get("description"),
            weight=payload.get("weight", 1.0),
            satisfied=payload.get("satisfied", False),
            metrics=GoalMetricProfile(
                novelty=metrics.get("novelty", 0.25),
                coherence=metrics.get("coherence", 0.25),
                predictability=metrics.get("predictability", 0.25),
                emergence=metrics.get("emergence", 0.25),
            ),
        )

    @staticmethod
    def _canonical_json(payload: Mapping[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def _digest_payload(cls, payload: Mapping[str, Any]) -> str:
        return sha256(cls._canonical_json(payload).encode("utf-8")).hexdigest()

    def _state_payload(self, *, include_audit: bool) -> dict[str, Any]:
        return {
            "runtime": {
                "max_intensity": self._max_intensity,
                "generation": self._generation,
                "revision": self._revision,
            },
            "facts": [self._fact_payload(fact) for fact in sorted(self._facts.values(), key=lambda item: item.id)],
            "goals": [self._goal_payload(goal) for goal in self.goals],
            "derivations": [
                {
                    "fact_id": record.fact_id,
                    "rule_id": record.rule_id,
                    "parent_ids": list(record.parent_ids),
                    "run_id": record.run_id,
                    "generation": record.generation,
                    "created_at": record.created_at,
                }
                for record in sorted(self._derivations.values(), key=lambda item: item.fact_id)
            ],
            "rule_manifest": [
                {key: value for key, value in self.rule_manifest[rule_id].items() if key != "registered"}
                for rule_id in sorted(self.rule_manifest)
            ],
            "audit": [
                {"sequence": event.sequence, "kind": event.kind, "timestamp": event.timestamp, "data": dict(event.data)}
                for event in self._audit
            ]
            if include_audit
            else [],
        }

    def state_digest(self, *, include_audit: bool = True) -> str:
        """Liefert den SHA-256-Fingerabdruck eines kanonischen, deklarativen Zustands."""
        with self._lock:
            return self._digest_payload(self._state_payload(include_audit=include_audit))

    def export_state(self, *, include_audit: bool = True, indent: Optional[int] = 2) -> str:
        """Exportiert einen versionierten Zustand mit prüfbarem Digest und ohne Callbacks."""
        if not isinstance(include_audit, bool):
            raise ValueError("include_audit muss bool sein.")
        with self._lock:
            state = self._state_payload(include_audit=include_audit)
            envelope = {
                "schema": STATE_SCHEMA,
                "state": state,
                "integrity": {"algorithm": "sha256", "sha256": self._digest_payload(state)},
            }
            return json.dumps(envelope, ensure_ascii=False, indent=indent, sort_keys=True, allow_nan=False)

    @classmethod
    def from_state(cls, serialized: str | Mapping[str, Any], *, verify: bool = True) -> "UniversalBrainCore":
        """Rekonstruiert deklarative Daten; Regel-Callbacks werden absichtlich nicht wiederhergestellt."""
        if isinstance(serialized, str):
            try:
                envelope = json.loads(serialized)
            except json.JSONDecodeError as exc:
                raise EngineError("Der Zustands-Import enthält ungültiges JSON.") from exc
        elif isinstance(serialized, Mapping):
            envelope = dict(serialized)
        else:
            raise ValueError("serialized muss JSON-Text oder ein Mapping sein.")
        if not isinstance(envelope, Mapping) or envelope.get("schema") != STATE_SCHEMA:
            raise EngineError(f"Nicht unterstütztes Zustands-Schema; erwartet wird {STATE_SCHEMA!r}.")
        state = envelope.get("state")
        integrity = envelope.get("integrity")
        if not isinstance(state, Mapping) or not isinstance(integrity, Mapping):
            raise EngineError("Der Zustands-Import benötigt state und integrity als Mapping.")
        digest = integrity.get("sha256")
        if integrity.get("algorithm") != "sha256" or not isinstance(digest, str):
            raise EngineError("Der Zustands-Import benötigt einen SHA-256-Integritätswert.")
        expected_digest = cls._digest_payload(state)
        if verify and not compare_digest(digest, expected_digest):
            raise EngineError("Der Zustands-Import wurde verändert oder der Integritätswert ist ungültig.")

        runtime = state.get("runtime")
        facts_payload = state.get("facts")
        goals_payload = state.get("goals")
        derivations_payload = state.get("derivations")
        manifest_payload = state.get("rule_manifest")
        audit_payload = state.get("audit", [])
        if not isinstance(runtime, Mapping):
            raise EngineError("Der Zustands-Import benötigt runtime als Mapping.")
        if not all(isinstance(value, list) for value in (facts_payload, goals_payload, derivations_payload, manifest_payload, audit_payload)):
            raise EngineError("Die Zustandslisten facts, goals, derivations, rule_manifest und audit sind erforderlich.")
        core = cls(max_intensity=runtime.get("max_intensity", MAX_INTENSITY))
        with core._lock:
            for payload in goals_payload:
                goal = cls._goal_from_payload(payload)
                if goal.id in core._goals:
                    raise EngineError(f"Doppeltes Ziel im Zustands-Import: {goal.id}")
                core._goals[goal.id] = goal
            for payload in facts_payload:
                fact = cls._fact_from_payload(payload)
                if fact.id in core._facts or fact.semantic_key in core._semantic_index:
                    raise EngineError(f"Doppelter Fakt im Zustands-Import: {fact.id}")
                core._facts[fact.id] = fact
                core._index_fact(fact)
            for payload in derivations_payload:
                if not isinstance(payload, Mapping) or not isinstance(payload.get("parent_ids"), list):
                    raise EngineError("Eine Ableitung benötigt ein Mapping mit parent_ids als Liste.")
                record = DerivationRecord(
                    fact_id=payload.get("fact_id"),
                    rule_id=payload.get("rule_id"),
                    parent_ids=tuple(payload["parent_ids"]),
                    run_id=payload.get("run_id"),
                    generation=payload.get("generation"),
                    created_at=payload.get("created_at"),
                )
                if record.fact_id not in core._facts or record.fact_id in core._derivations:
                    raise EngineError(f"Ungültige Ableitungsreferenz im Zustands-Import: {record.fact_id}")
                core._derivations[record.fact_id] = record
            for payload in manifest_payload:
                if not isinstance(payload, Mapping):
                    raise EngineError("Ein Regelmanifest-Eintrag muss ein Mapping sein.")
                rule_id = payload.get("id")
                if not isinstance(rule_id, str) or not rule_id.strip() or rule_id in core._imported_rule_manifest:
                    raise EngineError("Das Regelmanifest enthält eine ungültige oder doppelte ID.")
                if "condition" in payload or "action" in payload:
                    raise EngineError("Regel-Callbacks dürfen niemals aus einem Zustands-Import geladen werden.")
                core._imported_rule_manifest[rule_id] = MappingProxyType(dict(payload, registered=False))
            expected_sequence = 1
            for payload in audit_payload:
                if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), Mapping):
                    raise EngineError("Ein Audit-Ereignis muss ein Mapping mit data als Mapping sein.")
                event = AuditEvent(
                    sequence=payload.get("sequence"),
                    kind=payload.get("kind"),
                    timestamp=payload.get("timestamp"),
                    data=MappingProxyType(dict(payload["data"])),
                )
                if event.sequence != expected_sequence:
                    raise EngineError("Die Audit-Sequenz im Zustands-Import ist nicht lückenlos.")
                expected_sequence += 1
                core._audit.append(event)
            generation = runtime.get("generation")
            revision = runtime.get("revision")
            if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
                raise EngineError("runtime.generation muss eine nichtnegative Ganzzahl sein.")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise EngineError("runtime.revision muss eine nichtnegative Ganzzahl sein.")
            if generation < max((fact.generation for fact in core._facts.values()), default=0):
                raise EngineError("runtime.generation darf nicht unter einer Faktengeneration liegen.")
            core._generation = generation
            core._revision = revision
        return core

    def detect_internal_conflicts(self) -> tuple[FactConflict, ...]:
        """Findet explizite Wahr/Falsch-Widersprüche für denselben normalisierten Claim."""
        with self._lock:
            grouped: defaultdict[str, dict[bool, list[str]]] = defaultdict(lambda: defaultdict(list))
            for fact in self._facts.values():
                claim_key, polarity = fact.semantic_key
                if polarity is not None:
                    grouped[claim_key][polarity].append(fact.id)
            conflicts = [
                FactConflict(claim_key, tuple(sorted(polarities[True])), tuple(sorted(polarities[False])))
                for claim_key, polarities in grouped.items()
                if True in polarities and False in polarities
            ]
            return tuple(sorted(conflicts, key=lambda conflict: conflict.claim_key))

    def explain_fact(self, fact_id: str, *, max_depth: int = 8, max_nodes: int = 128) -> ExplanationNode:
        """Erzeugt eine begrenzte, zyklussichere Provenienzansicht eines Faktenknotens."""
        if not isinstance(fact_id, str) or not fact_id.strip():
            raise ValueError("fact_id darf nicht leer sein.")
        if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
            raise ValueError("max_depth muss eine nichtnegative Ganzzahl sein.")
        if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes < 1:
            raise ValueError("max_nodes muss eine positive Ganzzahl sein.")
        with self._lock:
            facts = dict(self._facts)
            derivations = dict(self._derivations)

        visited_nodes = 0

        def build(current_id: str, path: frozenset[str], depth: int) -> ExplanationNode:
            nonlocal visited_nodes
            fact = facts.get(current_id)
            if fact is None:
                return ExplanationNode(current_id, None, None, None, (), (), missing=True)
            if current_id in path:
                return ExplanationNode(
                    current_id,
                    fact.content,
                    fact.generation,
                    derivations.get(current_id).rule_id if current_id in derivations else None,
                    fact.sources,
                    (),
                    cycle_detected=True,
                )
            visited_nodes += 1
            record = derivations.get(current_id)
            source_ids = record.parent_ids if record is not None else fact.sources
            if visited_nodes >= max_nodes or depth >= max_depth:
                return ExplanationNode(
                    current_id,
                    fact.content,
                    fact.generation,
                    record.rule_id if record is not None else None,
                    source_ids,
                    (),
                    truncated=bool(source_ids),
                )
            children = tuple(build(source_id, path | {current_id}, depth + 1) for source_id in source_ids)
            return ExplanationNode(
                current_id,
                fact.content,
                fact.generation,
                record.rule_id if record is not None else None,
                source_ids,
                children,
            )

        return build(fact_id, frozenset(), 0)

    def inspect_integrity(self) -> IntegrityReport:
        """Prüft interne Indizes, Audit-Sequenzen und deklarative Invarianten ohne Mutation."""
        with self._lock:
            issues: list[str] = []
            expected_semantics: dict[tuple[str, Optional[bool]], str] = {}
            expected_sources: defaultdict[str, set[str]] = defaultdict(set)
            for fact_id, fact in self._facts.items():
                if fact.id != fact_id:
                    issues.append(f"fact_id_key_mismatch:{fact_id}")
                existing = expected_semantics.get(fact.semantic_key)
                if existing is not None and existing != fact_id:
                    issues.append(f"duplicate_semantic_key:{fact.semantic_key[0]}")
                expected_semantics[fact.semantic_key] = fact_id
                for source in fact.sources:
                    expected_sources[source].add(fact_id)
            if dict(self._semantic_index) != expected_semantics:
                issues.append("semantic_index_mismatch")
            if {key: set(value) for key, value in self._source_index.items()} != dict(expected_sources):
                issues.append("source_index_mismatch")
            for fact_id, record in self._derivations.items():
                if fact_id not in self._facts or record.fact_id != fact_id:
                    issues.append(f"derivation_mismatch:{fact_id}")
            for expected_sequence, event in enumerate(self._audit, start=1):
                if event.sequence != expected_sequence:
                    issues.append(f"audit_sequence_mismatch:{expected_sequence}")
            for rule_id, metadata in self._imported_rule_manifest.items():
                if rule_id in self._rules:
                    issues.append(f"shadowed_imported_rule_manifest:{rule_id}")
                if "condition" in metadata or "action" in metadata:
                    issues.append(f"unsafe_rule_manifest:{rule_id}")
            return IntegrityReport(
                valid=not issues,
                state_digest=self._digest_payload(self._state_payload(include_audit=True)),
                issues=tuple(sorted(issues)),
                fact_count=len(self._facts),
                goal_count=len(self._goals),
                derivation_count=len(self._derivations),
                audit_event_count=len(self._audit),
            )

    def export_audit(self, *, indent: Optional[int] = 2) -> str:
        """Erzeugt einen JSON-Export ohne serialisierte Regel-Callbacks."""
        with self._lock:
            payload = {
                "generation": self._generation,
                "revision": self._revision,
                "facts": [
                    {
                        "id": fact.id,
                        "content": fact.content,
                        "certainty": fact.certainty,
                        "dimensions": {
                            "epistemology": fact.dimensions.epistemology,
                            "entropy": fact.dimensions.entropy,
                            "intensity": fact.dimensions.intensity,
                            "emergence": fact.dimensions.emergence,
                            "goal_alignment": fact.dimensions.goal_alignment,
                        },
                        "generation": fact.generation,
                        "sources": list(fact.sources),
                        "timestamp": fact.timestamp,
                        "claim": fact.claim,
                        "polarity": fact.polarity,
                    }
                    for fact in sorted(self._facts.values(), key=lambda item: item.id)
                ],
                "goals": [
                    {
                        "id": goal.id,
                        "description": goal.description,
                        "weight": goal.weight,
                        "satisfied": goal.satisfied,
                        "metrics": {
                            "novelty": goal.metrics.novelty,
                            "coherence": goal.metrics.coherence,
                            "predictability": goal.metrics.predictability,
                            "emergence": goal.metrics.emergence,
                        },
                    }
                    for goal in self.goals
                ],
                "rules": [
                    {
                        "id": rule.id,
                        "priority": rule.priority,
                        "efficacy": rule.efficacy,
                        "generation": rule.generation,
                        "execution_count": rule.execution_count,
                        "last_used": rule.last_used,
                    }
                    for rule in self._ordered_rules()
                ],
                "derivations": [
                    {
                        "fact_id": record.fact_id,
                        "rule_id": record.rule_id,
                        "parent_ids": list(record.parent_ids),
                        "run_id": record.run_id,
                        "generation": record.generation,
                        "created_at": record.created_at,
                    }
                    for record in sorted(self._derivations.values(), key=lambda item: item.fact_id)
                ],
                "audit": [
                    {"sequence": event.sequence, "kind": event.kind, "timestamp": event.timestamp, "data": dict(event.data)}
                    for event in self._audit
                ],
            }
            return json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=True)


def make_fact(
    content: str,
    certainty: float,
    *,
    fact_id: Optional[str] = None,
    dimensions: Optional[SemanticDimensions] = None,
    sources: Sequence[str] = (),
    claim: Optional[str] = None,
    polarity: Optional[bool] = None,
) -> MindFact:
    """Erzeugt einen stabil identifizierten Fakt für einfache Integrationen."""
    if fact_id is None:
        fact_id = _stable_id("fact", content, claim or "", str(polarity), "|".join(sorted(sources)))
    return MindFact(
        id=fact_id,
        content=content,
        certainty=certainty,
        dimensions=dimensions or SemanticDimensions(),
        sources=tuple(sources),
        claim=claim,
        polarity=polarity,
    )


def make_implication_rule(
    rule_id: str,
    premise_ids: Sequence[str],
    conclusion_content: str,
    *,
    certainty: float = 0.70,
    dimensions: Optional[SemanticDimensions] = None,
    claim: Optional[str] = None,
    polarity: Optional[bool] = None,
    priority: int = 0,
) -> CognitiveRule:
    """Erzeugt eine deterministische Konjunktionsregel für explizite Prämissen."""
    required = tuple(dict.fromkeys(premise_ids))
    if not required:
        raise ValueError("Eine Implikationsregel benötigt mindestens eine Prämisse.")

    def condition(facts: Sequence[MindFact]) -> bool:
        return set(required).issubset({fact.id for fact in facts})

    def action(facts: Sequence[MindFact]) -> tuple[MindFact, ...]:
        by_id = {fact.id: fact for fact in facts}
        premises = tuple(by_id[premise] for premise in required)
        inherited = dimensions or SemanticDimensions(
            epistemology=sum(fact.dimensions.epistemology for fact in premises) / len(premises),
            entropy=sum(fact.dimensions.entropy for fact in premises) / len(premises),
            intensity=min(MAX_INTENSITY, sum(fact.dimensions.intensity for fact in premises) / len(premises)),
            emergence=min(1.0, max(fact.dimensions.emergence for fact in premises) + 0.05),
            goal_alignment=0.5,
        )
        fact = make_fact(
            conclusion_content,
            certainty,
            fact_id=_stable_id("derived", rule_id, conclusion_content, "|".join(required)),
            dimensions=inherited,
            sources=required,
            claim=claim,
            polarity=polarity,
        )
        return (fact,)

    return CognitiveRule(rule_id, condition, action, priority=priority)


def generate_combinatorial_rules(
    prefix: str,
    premise_ids: Sequence[str],
    conclusion_factory: Callable[[tuple[MindFact, ...]], MindFact],
    *,
    min_arity: int = 2,
    max_arity: int = 3,
    priority: int = 0,
) -> tuple[CognitiveRule, ...]:
    """Erzeugt Meta-Regeln über eindeutige Prämissenkombinationen ohne Code-Evaluierung."""
    unique = tuple(sorted(dict.fromkeys(premise_ids)))
    if not callable(conclusion_factory):
        raise ValueError("conclusion_factory muss aufrufbar sein.")
    if min_arity < 1 or max_arity < min_arity:
        raise ValueError("Die Aritätsgrenzen sind ungültig.")
    rules: list[CognitiveRule] = []
    for arity in range(min_arity, min(max_arity, len(unique)) + 1):
        for combo in combinations(unique, arity):
            rule_id = _stable_id(prefix, *combo)

            def condition(facts: Sequence[MindFact], required: tuple[str, ...] = combo) -> bool:
                return set(required).issubset({fact.id for fact in facts})

            def action(
                facts: Sequence[MindFact], required: tuple[str, ...] = combo, factory: Callable[[tuple[MindFact, ...]], MindFact] = conclusion_factory
            ) -> tuple[MindFact, ...]:
                by_id = {fact.id: fact for fact in facts}
                candidate = factory(tuple(by_id[fact_id] for fact_id in required))
                # Die Provenienz einer Meta-Regel ist immer genau die auslösende Kombination.
                return (replace(candidate, sources=required),)

            rules.append(CognitiveRule(rule_id, condition, action, priority=priority, generation=arity))
    return tuple(rules)


__all__ = [
    "AxiomParadigm",
    "AuditEvent",
    "BranchFinding",
    "CognitiveRule",
    "Conflict",
    "DerivationRecord",
    "EngineError",
    "ExplanationNode",
    "FactConflict",
    "GoalMetricProfile",
    "IntegrityReport",
    "InferenceBudget",
    "InferenceReport",
    "MAX_INTENSITY",
    "STATE_SCHEMA",
    "MindFact",
    "ResonanceEdge",
    "SemanticDimensions",
    "SynthesisFinding",
    "SynthesisResult",
    "TeleologicalGoal",
    "UniverseBranch",
    "UniversalBrainCore",
    "generate_combinatorial_rules",
    "make_fact",
    "make_implication_rule",
]
