# Code-Struktur: bot.py

Übersichtliche Dokumentation der Hauptkomponenten und Funktionen des Schambot-Dispatchers.

## Inhaltsverzeichnis

- [Initialisierung](#initialisierung)
- [Nutzerverwaltung](#nutzerverwaltung)
- [Logging & Kontext](#logging--kontext)
- [Nachrichtenverarbeitung](#nachrichtenverarbeitung)
- [Krisenerkennung](#krisenerkennung)
- [Phasen-Handling](#phasen-handling)
- [Commands & Administrative Funktionen](#commands--administrative-funktionen)
- [Scheduler & Automatische Nachrichten](#scheduler--automatische-nachrichten)
- [Analyse & Auswertung](#analyse--auswertung)
- [Hauptausführung](#hauptausführung)

---

## Initialisierung

| Komponente | Zeilen | Beschreibung |
|------------|--------|--------------|
| Imports & Konfiguration | 6-30 | Module, Dependencies, Settings |
| `__init__` | 32-37 | Klassen-Initialisierung, User-States laden |

## Nutzerverwaltung

| Funktion | Zeilen | Beschreibung |
|----------|--------|--------------|
| `hash_phone_number` | 40-42 | Verschlüsselt Telefonnummern (SHA-256) |
| `save_phone_mapping` | 44-65 | Speichert user_id ↔ phone mapping |
| `get_phone_from_user_id` | 67-101 | Holt Telefonnummer aus Mapping |
| `cleanup_user_state` | 103-125 | Bereinigt überflüssige Daten |
| `save_user_state` | 127-132 | Speichert Nutzerzustand als JSON |
| `load_user_state` | 134-141 | Lädt einzelnen Nutzerzustand |
| `load_all_user_states` | 143-148 | Lädt alle User-States beim Start |
| `validate_personal_code` | 150-169 | Validiert 6-stelligen Code (AB1234) |

## Logging & Kontext

| Funktion | Zeilen | Beschreibung |
|----------|--------|--------------|
| `log_interaction` | 171-188 | Protokolliert alle Bot-User-Interaktionen |
| `get_full_conversation_context` | 190-222 | Lädt komplette Konversationshistorie |
| `check_and_handle_time_limits` | 251-353 | Session- und Daily-Limits prüfen |

## Nachrichtenverarbeitung

| Funktion | Zeilen | Beschreibung |
|----------|--------|--------------|
| `listen_for_messages` | 355-404 | Signal-Nachrichten abhören (Loop) |
| `send_signal_message` | 406-449 | Sendet Nachrichten via Signal API |
| `generate_ai_response` | 451-762 | Generiert kontextuelle AI-Antworten |
| `process_message_batch` | 2680-2712 | Verarbeitet gebatchte Nachrichten |
| `handle_signal_message` | 2714-2774 | Hauptlogik für eingehende Nachrichten |

## Krisenerkennung

| Funktion | Zeilen | Beschreibung |
|----------|--------|--------------|
| `fallback_keyword_check` | 764-772 | Keyword-basierte Krisenerkennung |
| `assess_crisis_risk` | 774-851 | AI-basierte Risikoeinschätzung |
| `handle_crisis_exploration` | 853-884 | Nachfragen bei Krisenverdacht |
| `process_exploration_response` | 886-911 | Verarbeitet Explorations-Antworten |
| `handle_confirmed_crisis` | 913-940 | Handhabt bestätigte Krisen |
| `handle_false_alarm` | 942-961 | Handhabt Fehlalarme |
| `check_for_crisis` | 963-989 | Hauptfunktion Krisenerkennung |
| `log_crisis_event` | 991-1014 | Protokolliert Krisenereignisse |

## Phasen-Handling

### Onboarding & Woche 1

| Funktion | Zeilen | Beschreibung |
|----------|--------|--------------|
| `handle_start_command` | 1016-1091 | Startet Onboarding-Prozess |
| `handle_onboarding` | 1093-1204 | Verarbeitet 7 Onboarding-Fragen |
| `assess_user_shame_level` | 1207-1232 | Ermittelt initiales Scham-Niveau |
| `generate_day2_goal_question` | 1234-1249 | Generiert Zielfrage für Tag 2 |
| `handle_goal_response` | 1251-1351 | Verarbeitet Ziel-Antworten (Tag 2) |
| `generate_optional_deepening_response` | 1353-1397 | Optional Deepening (Tag 3-7) |
| `handle_weekly_response` | 1399-1508 | Hauptlogik für Woche 1 Gespräche |

### Gesprächssteuerung

| Funktion | Zeilen | Beschreibung |
|----------|--------|--------------|
| `detect_conversation_ending` | 1510-1573 | Erkennt Gesprächsabschluss-Signale |
| `generate_week_closure` | 1575-1615 | Generiert Wochen-Abschlüsse |
| `get_recent_response_count` | 1617-1646 | Zählt Antworten in Zeitfenster |
| `get_response_count_for_week` | 1648-1670 | Zählt Antworten pro Woche |
| `log_weekly_interaction` | 1672-1675 | Protokolliert wöchentliche Interaktionen |

## Commands & Administrative Funktionen

| Funktion | Zeilen | Beschreibung |
|----------|--------|--------------|
| `handle_command` | 1677-1728 | Verarbeitet Admin-Commands |
| `get_phase_description` | 1730-1741 | Gibt Phase-Beschreibung zurück |
| `process_message` | 1743-1783 | Haupt-Message-Processing |
| `finish_study` | 2552-2603 | Beendet Studie für User |

## Scheduler & Automatische Nachrichten

### Basis-Funktionen

| Funktion | Zeilen | Beschreibung |
|----------|--------|--------------|
| `setup_scheduler` | 1785-1788 | Initialisiert Scheduler |
| `calculate_study_day_from_calendar` | 1790-1819 | Berechnet aktuellen Studientag |
| `daily_check` | 1821-1908 | Haupt-Scheduler-Logik (läuft täglich) |
| `was_sent_today` | 1910-1931 | Prüft ob Nachricht heute gesendet |
| `was_transition_sent` | 1933-1935 | Prüft ob Transition gesendet |

### Woche 2: Gezielte Interventionen

| Funktion | Zeilen | Beschreibung |
|----------|--------|--------------|
| `get_top_shame_areas` | 1937-1958 | Identifiziert Top 2 Scham-Bereiche |
| `generate_ai_exploration_question` | 1960-2075 | Generiert tagesspezifische Fragen |
| `_send_evening_question_now` | 2077-2151 | Sendet Abendfrage |
| `has_unanswered_question` | 2153-2162 | Prüft unbeantwortete Fragen |
| `assess_response_quality` | 2164-2231 | Bewertet Antwortqualität |
| `_send_morning_greeting_now` | 2233-2249 | Sendet Morgengruß |
| `_send_reminder_now` | 2251-2284 | Sendet Erinnerung |
| `_send_evening_intervention_now` | 2286-2459 | Sendet Abend-Intervention |

### Transitions & Deadlines

| Funktion | Zeilen | Beschreibung |
|----------|--------|--------------|
| `initiate_week2_transition` | 2461-2516 | Leitet Übergang zu Woche 2 ein |
| `mark_day15_last_intervention_sent` | 2518-2530 | Markiert letzte Intervention Tag 15 |
| `check_auto_finish_deadlines` | 2532-2550 | Prüft automatische Abschluss-Fristen |
| `check_t3_survey_reminder` | 2605-2632 | Prüft T3-Survey-Erinnerungen |
| `send_t3_reminder` | 2634-2678 | Sendet T3-Survey-Reminder |

## Analyse & Auswertung

| Funktion | Zeilen | Beschreibung |
|----------|--------|--------------|
| `extract_user_messages_from_tagebuch` | 2812-2842 | Extrahiert User-Nachrichten |
| `get_initial_shame_context` | 2844-2866 | Holt initialen Scham-Kontext |
| `ai_therapeutic_shame_evaluation` | 2868-2933 | AI-basierte therapeutische Bewertung |
| `extract_therapeutic_score` | 2935-2949 | Extrahiert Therapie-Score |
| `extract_confidence` | 2951-2957 | Extrahiert Confidence-Wert |
| `extract_assessment_quality` | 2959-2967 | Extrahiert Assessment-Quality |
| `extract_reasoning` | 2969-2975 | Extrahiert Begründung |
| `fallback_therapeutic_assessment` | 2977-2998 | Fallback bei KI-Fehlern |
| `perform_automatic_week1_analysis` | 3000-3053 | Automatische Woche-1-Analyse |
| `get_week1_analysis_summary` | 3055-3083 | Zusammenfassung aller Analysen |

## Hauptausführung

| Funktion | Zeilen | Beschreibung |
|----------|--------|--------------|
| `run` | 2776-2810 | Startet alle Threads (Listener, Scheduler, Deadline-Watcher) |

---

**Gesamtzeilen:** ~3085  
**Letzte Aktualisierung:** Januar 2025
