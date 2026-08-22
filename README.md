# HyperCognitive Reasoning & Multi-Universe Synthesis Engine

**Version 1.1.0** ergänzt die Engine um einen versionierten, SHA-256-gesicherten Zustands-Export und -Import, deklarative Regelmanifeste ohne Callbacks, atomare Faktenstapel, interne Konfliktbefunde, Faktenerklärungen und einen nichtmutierenden Integritätsbericht.

Die **HyperCognitive Reasoning Engine** ist eine lokale, deterministische und standardbibliotheksbasierte Referenzimplementierung für nachvollziehbares neuro-symbolisches Reasoning. Sie verarbeitet ausschließlich explizit registrierte Fakten und vom Integrator bereitgestellte Regeln. Sie besitzt keine Netzwerkfunktion, evaluiert keine Regeltexte als Code und führt keine Außenweltaktionen aus.

> **Wichtige Einordnung:** Die Bezeichnung „AGI“ ist ein Projektname. Die Engine beansprucht keine allgemeine künstliche Intelligenz und ersetzt weder Fachurteile noch sicherheitskritische Entscheidungsprozesse.

## Lieferumfang

| Bereich | Enthaltene Fähigkeit |
|---|---|
| Faktenraum | Immutable Fakten mit validierten epistemischen, entropischen, intensitäts-, Emergenz- und Zielkoordinaten. |
| Ziele | Gewichtete teleologische Ziele mit erneuter Ausrichtung bereits vorhandener Fakten. |
| Inferenz | Priorisierte Regeln, deterministische Reihenfolge, Fixpunkt-Erkennung und harte Zeit-, Iterations-, Regel- sowie Ableitungsbudgets. |
| Nachvollziehbarkeit | Herkunftsreferenzen, Ableitungsaufzeichnungen und zeitgestempelte Audit-Ereignisse. |
| Resonanz | Symmetrische, gewichtete Faktenbeziehungen und begrenzte Aktivierungsweitergabe. |
| Multi-Universen | Isolierte Perspektivzweige für fünf Axiomparadigmen und quantifizierte Konsens-/Konfliktsynthese. |
| Integrationsoberfläche | Öffentliche Python-API, CLI-Demo, JSON-Audit-Export, versionierter Zustands-Export/-Import und umfassende Testsuite. |
| Persistenz und Integrität | Kanonisches Zustandsformat mit SHA-256-Digest, Importprüfung, deklarativem Regelmanifest und Integritätsbericht. |
| Erklärbarkeit | Zyklussichere Provenienzansichten sowie explizite Konfliktbefunde für Wahr/Falsch-Claims. |

## Projektstruktur

| Pfad | Zweck |
|---|---|
| `src/hypercognitive_engine/core.py` | Vollständige Kernimplementierung und Hilfsfabriken. |
| `src/hypercognitive_engine/__main__.py` | Reproduzierbare CLI-Demonstration. |
| `tests/test_core.py` | Standardbibliotheksbasierte Testsuite. |
| `docs/ARCHITECTURE.md` | Zielarchitektur, Qualitätskriterien und Nichtziele. |

## Schnellstart

Die Engine benötigt Python 3.11 oder neuer und keine Laufzeitabhängigkeiten. Für einen lokalen Ausführungstest genügt der folgende Aufruf aus dem Projektverzeichnis:

```bash
PYTHONPATH=src python3 -m hypercognitive_engine \
  --export ./artifacts/audit.json \
  --state-export ./artifacts/state.json
```

Der Befehl erstellt ein kleines Evidenz- und Regelbeispiel, führt die Inferenz aus, berechnet Resonanzkanten, exploriert die fünf vordefinierten Universumszweige und exportiert eine prüfbare JSON-Auditspur sowie optional einen versionierten Zustands-Snapshot. `--state-without-audit` reduziert diesen Snapshot auf Fakten, Ziele, Ableitungen und Regelmanifest.

## Minimales Integrationsbeispiel

```python
from hypercognitive_engine import (
    InferenceBudget,
    SemanticDimensions,
    UniversalBrainCore,
    make_fact,
    make_implication_rule,
)

engine = UniversalBrainCore()
engine.add_fact(
    make_fact(
        "Die Messung ist kalibriert.",
        0.90,
        fact_id="calibrated",
        dimensions=SemanticDimensions(epistemology=0.90, entropy=0.10),
    )
)
engine.add_rule(
    make_implication_rule(
        "calibration-rule",
        ("calibrated",),
        "Die Messung darf als belastbare Eingabe verwendet werden.",
        certainty=0.75,
        priority=10,
    )
)

report = engine.run_inference(InferenceBudget(max_iterations=4))
print(report.derived_fact_ids)
print(engine.export_audit())
```

## Persistenter Zustand, Integrität und Erklärbarkeit

`export_state()` liefert eine Envelope mit der Schema-ID `hypercognitive-engine-state/1`, kanonischem deklarativem Zustand und SHA-256-Digest. `UniversalBrainCore.from_state()` überprüft diesen Digest standardmäßig und rekonstruiert Fakten, Ziele, Ableitungen, Auditdaten und Regelmetadaten. Aus Sicherheitsgründen enthält ein Regelmanifest niemals `condition`- oder `action`-Callbacks. Nach einem Import müssen Regeln daher bewusst durch vertrauenswürdigen Integrationscode erneut registriert werden.

`inspect_integrity()` prüft Fakten- und Quellenindizes, Ableitungsreferenzen, lückenlose Audit-Sequenzen sowie Manifestgrenzen ohne den Zustand zu verändern. `explain_fact()` erzeugt einen begrenzten, zyklussicheren Abstammungsbaum. `detect_internal_conflicts()` weist zeitgleich vorhandene `True`-/`False`-Polaritäten für denselben Claim aus, ohne eine Realweltwahrheit zu behaupten.

```python
snapshot = engine.export_state()
restored = UniversalBrainCore.from_state(snapshot)
assert restored.inspect_integrity().valid
assert restored.state_digest() == engine.state_digest()
```

## Multi-Universen und Synthese

`explore_universes()` projiziert den aktuellen Faktenraum in isolierte Zweige. Die Paradigmen **STANDARD**, **OBSERVATION_FIRST**, **LOGIC_FIRST**, **CHAOS_FIRST** und **TRANSCENDENT** verändern ausschließlich die Bewertungsdimensionen der brancheneigenen Kopien. Der Ausgangsfaktenraum bleibt unverändert. `synthesize_branches()` ermittelt anschließend Behauptungen mit ausreichender Zweigunterstützung und weist explizite Wahr/Falsch-Konflikte für denselben Claim separat aus.

Die Parameter `top_facts_per_branch` und `min_support` begrenzen Größe und Konsensschwelle. Die Synthese ist eine quantitative Zusammenführung der vorhandenen Fakten; sie ist keine automatische Verifikation realweltlicher Aussagen.

## Regelmodell und Sicherheitsgrenzen

Eine `CognitiveRule` erhält einen Snapshot der Fakten und gibt ausschließlich `MindFact`-Instanzen zurück. Fehler in einer Regel werden im Audit protokolliert, ohne nachfolgende Regeln zu blockieren. Regel-Callbacks stammen aus vertrauenswürdigem Integrationscode; externe Plugins, dynamisches `eval`, String-Codeausführung und versteckte Seiteneffekte sind bewusst nicht Teil der Engine.

Die `InferenceBudget`-Grenzen verhindern unbegrenzte Ausführungen. Zusätzlich sorgt semantische Deduplizierung dafür, dass ein gleichartiger Fakt nur übernommen wird, wenn er den vorhandenen Fakt in Certainty und Zielausrichtung übertrifft. `add_facts(..., atomic=True)` nimmt einen Stapel nur an, wenn sämtliche ID- und Semantikkollisionen vorab bestehen; andernfalls bleibt der gesamte Kernzustand unverändert.

## Qualitätssicherung

Die vollständige Testsuite wird ohne externe Testbibliothek ausgeführt:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Die Tests prüfen Dateninvarianten, unveränderliche Snapshots, Deduplizierung einschließlich kombinierter ID-/Semantik-Kollisionen, Zielausrichtung, Regelprioritäten, Ressourcenbudgets, Fehlerisolation, Provenienz, Resonanz, Zweig-Isolation, Konfliktsynthese, JSON-Export und kombinatorische Meta-Regeln.

## Erweiterungsgrenzen

Die stabile Kernoberfläche erlaubt weitere Ausbaustufen, etwa persistente Speicheradapter, eine deklarative Regelbeschreibung, eine Visualisierung des Resonanzgraphen oder Integrationen mit kuratierten Datenquellen. Solche Erweiterungen sollten weiterhin die bestehenden Grenzen einhalten: explizite Berechtigungen, reproduzierbare Ergebnisse, harte Ressourcenlimite, vollständige Auditierbarkeit und keine verdeckten Außenweltaktionen.
