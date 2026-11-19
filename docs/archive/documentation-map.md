> Archived planning document (German). It records the documentation-refresh plan before the current folder structure was established. For current user guides, see the parent `docs` directory; for maintained technical references, see `../references/README.md`.

# Dokumentenlandkarte

Arbeitsplan für die spätere, schlanke Endnutzer-Dokumentation auf `main`.
Diese Arbeitslandkarte bleibt vorerst auf Deutsch. Neue und überarbeitete
öffentliche Dokumente werden auf Englisch geschrieben.

## Zielbild für die öffentliche Dokumentation

Auf `main` sollen Nutzer schnell verstehen, was die Integration kann, wie sie
sie einrichten und wie sie eine bestehende Installation sicher umstellen. Die
README fasst das Projekt zusammen und führt zu Schritt-für-Schritt-Seiten.

| Zieldatei | Inhalt und Leserfrage |
| --- | --- |
| `README.md` | Was ist SolarVault NG? Welche Fähigkeiten und Grenzen hat es? Wer sind die Upstream-Projekte? Wie installiere ich es kurz über HACS/Marketplace? Wo finde ich Details? |
| `docs/installation.md` | Welche Voraussetzungen brauche ich, wie installiere und konfiguriere ich eine frische NG-Installation, und wie ändere ich Optionen? |
| `docs/upgrading.md` | Was muss ich bei einem Wechsel von Jackery Official, Community oder einer älteren NG-Version beachten? Welche Sicherung und welche Rückwege sind belegt? |
| `docs/devices-and-entities.md` | Welche Gerätepfade unterstützt die Integration, mit welcher Evidenz? Welche Sensoren und Steuerungen erscheinen? |
| `docs/energy-dashboards.md` | Welche Messwerte passen zu Energieflusskarten, wo liegen ihre Messgrenzen und wie verwende ich geprüfte Kartenbeispiele? |
| `docs/troubleshooting.md` | Wie untersuche ich fehlende oder unerwartete Daten, wie lade ich Diagnostik herunter und was muss ich vor dem Teilen prüfen? |
| `CHANGELOG.md` | Welche für Nutzer relevanten Änderungen enthält jede NG-Version? |

Die vier GitHub-Vorlagen unter `.github/ISSUE_TEMPLATE/` bleiben als
Support-Einstieg erhalten. Ihre Verweise und Hinweise zu Diagnostik und
Datenschutz werden an die öffentlichen Seiten angepasst.

## Quellen in öffentliche Seiten überführen

Die folgenden Dateien sind Arbeits- und Nachweismaterial. Nutzerrelevante,
belegte Aussagen daraus werden in die Zieldokumente übernommen. Anschließend
werden die technischen Berichte aus dem veröffentlichten Dokumentbaum
entfernt; ihre Entwicklung bleibt in der Git-Historie nachvollziehbar.

| Vorhandene Quelle | Übernahme in | Wichtige Grenze |
| --- | --- | --- |
| `docs/entity-reference.md`, `docs/entity-inventory.md`, `docs/current-capability-inventory.md` | `docs/devices-and-entities.md` | Entity-Namen, Übersetzungen, Steuerungen und Hardwareevidenz mit aktuellem Code abgleichen. Synthetische Tests nicht als Hardwaretest ausgeben. |
| `docs/energy-source-policy.md`, `docs/card-energy-flow-plus.md`, `docs/card-power-flow-plus.md`, `docs/custom-card-flow.md` | `docs/energy-dashboards.md` | Messgrenzen, Vorzeichen und Quellenwahl aus der Policy ableiten; Beispiele gegen aktuelle Entity-Namen prüfen. |
| `docs/use-cases/LOAD_LATE.md` | Nur nach fachlicher Korrektur in `docs/energy-dashboards.md` übernehmen oder weglassen | Der vorhandene Wertebereich widerspricht der Geräteuntergrenze; der YAML-Entwurf ist keine ausführbare Anleitung. |
| `docs/release-compatibility-contract.md`, `docs/upgrade-migration-validation.md` | `docs/installation.md` und `docs/upgrading.md` | Technische Release-Gates und Registry-Fixture-Details entfallen. Echte Upgradewege und offene Grenzen bleiben klar getrennt. |
| `docs/diagnostics-architecture.md`, passende Teile aus `README.md` | `docs/troubleshooting.md` | Nutzerzugang, Fehlerdiagnose und Datenschutz übernehmen; interne Größen- und Implementierungsdetails weglassen. |
| `CHANGELOG.md` und historische v2-Notizen in `README.md` | `CHANGELOG.md` | NG-Änderungen verständlich zusammenfassen; vererbte v2-Geschichte nicht als aktuelle NG-Funktion darstellen. |

README- und HACS-/Marketplace-Kurzinstallation verlinken auf die ausführliche
Installationsseite. Die Props und Danksagungen für Jackery Official und den
Community-Fork bleiben erhalten. Die README wird nach den Detailseiten gekürzt
und mit ihnen abgeglichen.

## Vorläufige Einordnung der vorhandenen Dokumente

### Nutzerinhalte: zusammenführen und anschließend Quelldateien entfernen

- `docs/entity-reference.md`
- `docs/entity-inventory.md`
- `docs/current-capability-inventory.md`
- `docs/energy-source-policy.md`
- `docs/card-energy-flow-plus.md`
- `docs/card-power-flow-plus.md`
- `docs/custom-card-flow.md`
- `docs/use-cases/LOAD_LATE.md` — nur falls fachlich korrigiert und weiterhin nützlich
- `docs/release-compatibility-contract.md`
- `docs/upgrade-migration-validation.md`
- `docs/diagnostics-architecture.md`

### Entwicklungs- und Auditmaterial: nicht Teil des öffentlichen Zieldokumentsatzes

Nach Übernahme notwendiger Nutzeraussagen sollen diese Berichte und Pläne aus
dem veröffentlichten Dokumentationsbaum entfernt werden:

- **Architektur und Refactoring:** `docs/architecture.md`,
  `docs/architecture-plan.md`, `docs/coordinator-state.md`,
  `docs/entity-boundaries.md`, `docs/refactor-map.md`,
  `docs/refactoring-roadmap.md`
- **Protokoll, MQTT und Frische:** `docs/availability-freshness.md`,
  `docs/mqtt-lifecycle.md`, `docs/mqtt-protocol-inventory.md`,
  `docs/mqtt-reconnect-validation.md`, `docs/protocol-routing-commands.md`
- **Diagnostik-, Logging- und Typisierungspläne:** `docs/diagnostics-plan.md`,
  `docs/ha-aware-typing-audit.md`, `docs/logging-plan.md`
- **Projektphasen und Testbelege:** `docs/baseline.md`,
  `docs/baseline-test-results.md`, `docs/phase-0-1-report.md`,
  `docs/phase3-closeout-phase4-plan.md`, `docs/p4-standby-live-zero-audit.md`,
  `docs/project-status.md`, `docs/test-coverage-map.md`
- **Identität und Upstream-Arbeit:** `docs/multi-instance-identity.md`,
  `docs/upstream-best-of-both-worlds-audit.md`,
  `docs/upstream-feature-matrix.md`, `docs/upstream-port-candidates.md`,
  `docs/upstream-sync.md`

Diese Einordnung betrifft die öffentliche Projektdokumentation. `AGENTS.md`
bleibt eine interne Arbeitsanweisung für Entwicklungsagenten. Quellcode und
Tests bleiben die technische Grundlage für Implementierung und Wartung.

### Alte oder lokale Kopien

- `custom_components/jackery/README.md` enthält eine überholte Anleitung. Vor
  dem Entfernen kurz prüfen, ob ein Verbraucher diese Datei benötigt; falls ja,
  durch einen knappen Verweis auf die Root-README ersetzen.
- `docs/entity-katalog-de.md` ist lokal ignoriert und nicht Teil der
  versionierten Dokumentation. Sie ist weder Quelle noch Zieldatei.
- `docs/documentation-map.md` ist ein temporäres Arbeitsdokument und gehört
  nicht zum späteren Endnutzer-Dokumentensatz.

## Reihenfolge

1. Die aktuelle Quellengrundlage für Geräte, Entities, Energiequellen,
   Installation, Migration und Diagnostik abgleichen.
2. `docs/devices-and-entities.md` und `docs/energy-dashboards.md` erstellen,
   damit Entity-Namen und Messwertbeispiele einen gemeinsamen Faktenstand haben.
3. `docs/installation.md`, `docs/upgrading.md` und
   `docs/troubleshooting.md` auf Basis belegter Abläufe schreiben.
4. README, Changelog und GitHub-Supportvorlagen auf die fertigen Seiten
   ausrichten; die Upstream-Props und Danksagungen in der README erhalten.
5. Quelldokumente nach Übernahme entfernen und die Landkarte anschließend aus
   dem öffentlichen Dokumentationsbaum entfernen.
