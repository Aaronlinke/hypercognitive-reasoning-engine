# Erweiterungsschnitt v1.1: Persistenz, Integrität und Erklärbarkeit

## Ausgangspunkt

Version 1.0.0 liefert einen sicheren lokalen Fakten- und Inferenzkern, exportiert jedoch bislang vorwiegend eine Auditansicht. Die nächste Ausbaustufe ergänzt eine **vollständig prüfbare Zustandsrepräsentation**, Wiederherstellung ohne serialisierte Callbacks sowie programmgesteuerte Diagnosefunktionen. Die Erweiterung bleibt absichtlich standardbibliotheksbasiert und verändert weder das Regelvertrauensmodell noch die Außenweltgrenzen.

> **Kompatibilitätsprinzip:** Fakten, Ziele, Ableitungen und Auditdaten dürfen in einen neuen Kern importiert werden. Regeln werden ausschließlich als Metadaten exportiert und müssen nach dem Import explizit durch vertrauenswürdigen Integrationscode erneut registriert werden.

## Priorisierte Erweiterungen

| Priorität | Erweiterung | Zweck | Sicherheits- und Kompatibilitätsregel |
|---|---|---|---|
| 1 | Versionierter Zustands-Export | Persistiert Fakten, Ziele, Ableitungen und optional Auditdaten als kanonisches JSON. | Keine ausführbaren Objekte, keine Regel-Callbacks, keine implizite Codeausführung. |
| 2 | Verifizierte Wiederherstellung | Baut einen neuen Kern aus einem Zustands-Export wieder auf. | Schema und SHA-256-Integritätswert werden vor Annahme geprüft; Regeln bleiben leer. |
| 3 | Integritätsbericht | Prüft Indizes, Provenienzreferenzen, Generationsordnung, Audit-Sequenzen und Zustandsdigest. | Der Bericht verändert den Kern nicht und führt keine Regeln aus. |
| 4 | Faktenerklärung | Liefert einen begrenzten, zyklussicheren Abstammungsbaum für einen Fakt. | Unbekannte externe Quellen werden transparent als fehlend ausgewiesen. |
| 5 | Interne Konfliktsicht | Findet gegensätzliche Wahr/Falsch-Polaritäten desselben Claims im Kernzustand. | Ein Konflikt ist ein Hinweis auf Modellinkonsistenz, keine reale Weltbehauptung. |
| 6 | Atomare Stapelaufnahme | Nimmt mehrere Fakten nur vollständig oder gar nicht auf. | Vor der Mutation werden ID- und Semantikkollisionen gegen den kombinierten Entwurf geprüft. |
| 7 | Effizienz- und Snapshot-Härtung | Reduziert redundante Resonanzberechnung und schützt diagnostische Ergebnisse vor Mutation. | Öffentliche API bleibt mit Version 1.0.0 kompatibel. |

## Zustandsformat

Ein Export verwendet die Schema-ID `hypercognitive-engine-state/1` und enthält den serialisierten Zustand sowie `integrity.sha256`. Der Digest wird über die kanonische JSON-Repräsentation des Zustands **ohne** das Integritätsfeld gebildet. Der Import akzeptiert JSON-Text oder ein Mapping, überprüft Schema, Typen und Digest und rekonstruiert danach ausschließlich deklarative Daten.

| Bereich | Persistiert | Nicht persistiert |
|---|---|---|
| Fakten und Ziele | Vollständig, einschließlich semantischer Dimensionen und Quellen. | – |
| Ableitungen und Audit | Deklarative Provenienz- und Ereignisdaten. | – |
| Regeln | ID, Priorität, Effektivität, Generation und Ausführungszähler als Manifest. | `condition`- und `action`-Callbacks. |
| Laufzeit | Generation, Revision und Intensitätsgrenze. | Lock, Cache, Scheduler oder externe Handles. |

## Akzeptanzkriterien

Die Tests müssen den identischen Export nach einem Roundtrip sowie die Erkennung manipulierter Daten prüfen. Weiterhin müssen sie valide und ungültige atomare Stapelaufnahmen, Erklärbarkeitsgrenzen, Zyklenresistenz, interne Konflikte, Audit- und Indexkonsistenz sowie unveränderte v1.0.0-Regressionen abdecken. Der Pakettest wird erneut aus einer isolierten Wheel-Installation ausgeführt.
