# -*- coding: utf-8 -*-
"""
Hauptdispatcher für den Schambot - SchamChatBot Klasse
"""

import os
import json
import time
import datetime
import hashlib
import threading
import schedule
from typing import Dict, List, Optional
from dataclasses import asdict
import requests
import logging

from storage import UserState
from settings import (
    STATE_DIR, TAGEBUCH_DIR, SIGNAL_API_URL, SIGNAL_NUMBER,
    SESSION_LIMIT_MINUTES, DAILY_LIMIT_MINUTES,
    EVENING_QUESTION_TIMES, MORNING_GREETING_TIMES, EVENING_INTERVENTION_TIMES,
    CRISIS_KEYWORDS, HELP_TEXT, ensure_directories, deployment
)
from gpt_client import client

logger = logging.getLogger(__name__)

# Directories sicherstellen
ensure_directories()

class SchamChatBot:
    def __init__(self):
        self.users: Dict[str, UserState] = {}
        self.pending_messages = {}
        self.load_all_user_states()
        self.setup_scheduler()


    def hash_phone_number(self, phone: str) -> str:
        """Verschlüsselt Telefonnummer für Datenschutz"""
        return hashlib.sha256(phone.encode()).hexdigest()[:16]

    def save_phone_mapping(self, user_id: str, phone_number: str):
        """Speichert user_id -> phone mapping in secure/nummernmap.json"""
        mapping_file = "secure/nummernmap.json"

        # Erstelle secure Ordner falls er nicht existiert
        os.makedirs("secure", exist_ok=True)

        # Lade existierendes Mapping
        mapping = {}
        if os.path.exists(mapping_file):
            try:
                with open(mapping_file, 'r') as f:
                    mapping = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                mapping = {}

        mapping[user_id] = phone_number  # Füge neues Mapping hinzu

        with open(mapping_file, 'w') as f:    # Speichere zurück
            json.dump(mapping, f, indent=2)

        logger.info(f"Saved phone mapping for user {user_id}")

    def get_phone_from_user_id(self, user_id: str) -> Optional[str]:
        """Holt Telefonnummer basierend auf user_id"""
        mapping_file = "secure/nummernmap.json"

        logger.debug(f"🔍 Looking up phone for user {user_id}")

        if not os.path.exists(mapping_file):
            logger.warning(f"❌Mapping file {mapping_file} does not exist!")
            return None

        try:
            with open(mapping_file, 'r') as f:
                mapping = json.load(f)

                logger.debug(f"📋 Mapping file contains {len(mapping)} entries")
                logger.debug(f"🔑 Available keys: {list(mapping.keys())}")

                # Zuerst: Exakte Übereinstimmung versuchen
                if user_id in mapping:
                    logger.debug(f"Found exact match for user {user_id}")
                    return mapping[user_id]

                # Fallback: Partial Match (falls Hash-Längen unterschiedlich)
                for key, phone in mapping.items():
                    if key.startswith(user_id) or user_id.startswith(key):
                        logger.info(f"Found partial match: {user_id} -> {key}")
                        return phone

                logger.warning(f"No phone mapping found for user {user_id} in {len(mapping)} entries")
                logger.debug(f"Available keys: {list(mapping.keys())}")
                return None

        except Exception as e:
            logger.error(f"Error reading mapping file: {e}")
            return None

    def cleanup_user_state(self, user_id: str):
        """Bereinigt user_state von überflüssigen Daten"""
        user = self.users.get(user_id)
        if not user or not user.week1_responses:
            return

        print(f"🧹 Bereinigte {user_id}...")

        # Nur die ersten 7 Onboarding-Fragen behalten
        original_count = len(user.week1_responses)
        user.week1_responses = [resp for resp in user.week1_responses if
                                'question_number' in resp and resp['question_number'] <= 7]
        cleaned_count = len(user.week1_responses)

        # week2_responses komplett entfernen (falls vorhanden)
        if hasattr(user, 'week2_responses'):
            delattr(user, 'week2_responses')

        print(f"  📊 week1_responses: {original_count} → {cleaned_count} Einträge")
        print(f"  🗑️ week2_responses entfernt")

        self.save_user_state(user_id)
        print(f"  ✅ Gespeichert")

    def save_user_state(self, user_id: str):
        """Speichert Nutzerzustand"""
        if user_id in self.users:
            filepath = os.path.join(STATE_DIR, f"{user_id}.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(asdict(self.users[user_id]), f, ensure_ascii=False, indent=2)

    def load_user_state(self, user_id: str) -> UserState:
        """Lädt Nutzerzustand"""
        filepath = os.path.join(STATE_DIR, f"{user_id}.json")
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return UserState(**data)
        return UserState(user_id=user_id)

    def load_all_user_states(self):
        """Lädt alle Nutzerzustände beim Start"""
        for filename in os.listdir(STATE_DIR):
            if filename.endswith('.json'):
                user_id = filename[:-5]  # Remove .json
                self.users[user_id] = self.load_user_state(user_id)

    def validate_personal_code(self, code: str) -> tuple[bool, str]:
        """
        Validiert den 6-stelligen persönlichen Code
        Format: Buchstabe-Buchstabe-Zahl-Zahl-Zahl-Zahl (z.B. AB1234)
        Returns:
            tuple: (is_valid, error_message)
        """
        code = code.strip().upper()  # Whitespace entfernen und großschreiben

        # Länge prüfen
        if len(code) != 6:
            return False, "Der Code muss genau 6 Zeichen haben (Format: AB1234)"

        # Format prüfen: Erste 2 Zeichen = Buchstaben, letzte 4 = Zahlen
        if not (code[0].isalpha() and code[1].isalpha() and
                code[2].isdigit() and code[3].isdigit() and
                code[4].isdigit() and code[5].isdigit()):
            return False, "Bitte gib den Code im Format AB1234 ein (2 Buchstaben, dann 4 Zahlen)"

        return True, ""

    def log_interaction(self, user_id: str, message_type: str, content: str, is_bot: bool = True):
        """Protokolliert ALLE Interaktionen - vereinfacht"""

        log_entry = {
            'timestamp': datetime.datetime.now().isoformat(),
            'user_id': user_id,
            'type': message_type,
            'content': content,
            'sender': 'bot' if is_bot else 'user'
        }

        # In Tagebuch-Datei speichern
        tagebuch_path = os.path.join(TAGEBUCH_DIR, f"{user_id}_tagebuch.jsonl")
        try:
            with open(tagebuch_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception as e:
            logger.error(f"❌ Failed to log interaction for {user_id}: {e}")

    def get_full_conversation_context(self, user_id: str) -> str:
        """Lädt ALLE User-Nachrichten seit Studienstart für maximale Kontinuität"""
        tagebuch_path = os.path.join(TAGEBUCH_DIR, f"{user_id}_tagebuch.jsonl")

        if not os.path.exists(tagebuch_path):
            return ""

        all_messages = []

        try:
            with open(tagebuch_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())

                        # NUR User-Nachrichten (keine Bot-Antworten, zu redundant)
                        if entry.get('sender') == 'user':
                            timestamp = entry.get('timestamp', '')
                            content = entry.get('content', '')

                            # Datum extrahieren (YYYY-MM-DD)
                            date = timestamp[:10] if timestamp else "Unbekannt"

                            all_messages.append({
                                'date': date,
                                'content': content,
                                'timestamp': timestamp
                            })

                    except (json.JSONDecodeError, KeyError):
                        continue

            if not all_messages:
                return ""

            # Gruppiere nach Tagen für bessere Übersicht
            from collections import defaultdict
            by_date = defaultdict(list)

            for msg in all_messages:
                by_date[msg['date']].append(msg['content'])

            # Formatiere als strukturierten Kontext
            context_parts = []
            for date in sorted(by_date.keys()):
                messages = by_date[date]
                # Zusammenfassung pro Tag
                day_summary = f"\n[{date}] ({len(messages)} Nachrichten):\n"
                day_summary += "\n".join([f"- {msg[:150]}" for msg in messages[-5:]])  # Max 5 pro Tag
                context_parts.append(day_summary)

            context_string = "=== BISHERIGER GESPRÄCHSVERLAUF ===\n" + "\n".join(context_parts[-10:])  # Letzte 10 Tage

            logger.info(f" Full context loaded: {len(all_messages)} total messages, {len(by_date)} days")

            return context_string

        except Exception as e:
            logger.error(f"Error loading full context: {e}")
            return ""

    def check_and_handle_time_limits(self, user_id: str, phone_number: str) -> bool:
        """Prüft Zeit-Limits basierend auf AKTIVER Gesprächszeit (nicht Gesamtzeit)"""
        user = self.users.get(user_id)
        if not user:
            return False

        now = datetime.datetime.now()
        today = now.strftime('%Y-%m-%d')

        # Daily reset
        if user.last_usage_date != today:
            user.daily_usage_minutes = 0.0
            user.session_start = None
            user.last_usage_date = today
            user.session_warned = False
            user.session_ended = False  # ← HIER HINZUFÜGEN

            # NEUE FELDER für aktive Session:
            if not hasattr(user, 'active_session_minutes'):
                user.active_session_minutes = 0.0
            if not hasattr(user, 'last_message_time'):
                user.last_message_time = None
            user.active_session_minutes = 0.0
            user.last_message_time = None

        # Session-Reset bei längerer Inaktivität
        INACTIVITY_RESET_MINUTES = 120  # Nach 2h Pause = neue Session

        if user.last_message_time:
            last_msg_time = datetime.datetime.fromisoformat(user.last_message_time)
            inactive_minutes = (now - last_msg_time).total_seconds() / 60

            if inactive_minutes > INACTIVITY_RESET_MINUTES:
                # Lange Pause = Session Reset
                logger.info(f"Session reset für User {user_id} nach {inactive_minutes:.1f}min Inaktivität")
                user.session_start = now.isoformat()
                user.active_session_minutes = 0.0
                user.session_warned = False
            else:
                # Aktive Session = Zeit hinzufügen
                time_to_add = min(inactive_minutes, 3.0)  # Cap at 5 minutes
                user.active_session_minutes += time_to_add

        else:
            # Erste Nachricht = Session starten
            user.session_start = now.isoformat()
            user.active_session_minutes = 0.0

        # Aktualisiere last_message_time
        user.last_message_time = now.isoformat()

        logger.debug(
            f"User {user_id} - Aktive Session: {user.active_session_minutes:.1f}min, Tägliche Nutzung: {user.daily_usage_minutes:.1f}min")

        # SESSION-LIMIT prüfen (basierend auf AKTIVER Zeit)
        if user.active_session_minutes >= SESSION_LIMIT_MINUTES:
            limit_msg = f"""💜 Was für ein intensives Gespräch - {SESSION_LIMIT_MINUTES} Minuten voller Offenheit und Mut.

Jetzt ist der perfekte Moment für eine bewusste Pause. Selbstfürsorge bedeutet auch zu spüren, wann es Zeit ist innezuhalten und das Erlebte wirken zu lassen.

Morgen bin ich wieder hier. Bis dahin: sei liebevoll mit dir. 🌱"""

            self.send_signal_message(phone_number, limit_msg)
            self.log_interaction(user_id, "session_limit_reached", limit_msg)

            user.session_ended = True  # ← NEU: Session als beendet markieren
            user.session_end_time = now.isoformat()

            # Session beenden und zur täglichen Zeit hinzufügen
            user.daily_usage_minutes += user.active_session_minutes
            user.active_session_minutes = 0.0
            user.session_start = None
            user.last_message_time = None
            self.save_user_state(user_id)
            return True

        # TAGES-LIMIT prüfen
        projected_daily = user.daily_usage_minutes + user.active_session_minutes
        if projected_daily >= DAILY_LIMIT_MINUTES:
            limit_msg = f"""🌸 Du warst heute sehr aktiv in der Selbstreflexion - über {DAILY_LIMIT_MINUTES} Minuten!

    Zeit für eine bewusste Pause bis morgen. Das ist gesunde Selbstfürsorge! 💚"""

            self.send_signal_message(phone_number, limit_msg)
            self.log_interaction(user_id, "daily_limit_reached", limit_msg)

            # Session beenden
            user.daily_usage_minutes += user.active_session_minutes
            user.active_session_minutes = 0.0
            user.session_start = None
            user.last_message_time = None
            self.save_user_state(user_id)
            return True

        # SESSION-WARNING (bei 35 Min aktiver Zeit)
        if user.active_session_minutes >= 35 and not user.session_warned:
            warning_msg = "💛 Wir sind seit 35 Minuten aktiv im Gespräch. In etwa 10 Minuten werde ich eine klei Pause vorschlagen. 🌿"
            self.send_signal_message(phone_number, warning_msg)
            self.log_interaction(user_id, "session_warning", warning_msg)
            user.session_warned = True
            self.save_user_state(user_id)

        return False

    def listen_for_messages(self):
        """Hört auf eingehende Nachrichten"""
        logger.info("Listening for messages...")

        while True:
            try:
                # Nachrichten von Signal API abrufen
                url = f"{SIGNAL_API_URL}/receive/{SIGNAL_NUMBER}"
                logger.debug(f"Checking for messages at: {url}")  # DEBUG

                response = requests.get(url, timeout=50)
                logger.debug(f"API Response Status: {response.status_code}")  # DEBUG

                if response.status_code == 200:
                    # logger.debug(f"API Response Content: {response.text[:200]}")  # DEBUG # auskommentiert zum Datenschutz
                    try:
                        messages = response.json()
                        if isinstance(messages, list):
                            for message_data in messages:
                                self.handle_signal_message(message_data)
                        elif isinstance(messages, dict):
                            self.handle_signal_message(messages)
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON response from Signal API")

                elif response.status_code == 204:
                    # Keine neuen Nachrichten - das ist normal
                    pass
                else:
                    logger.warning(f"Signal API returned status {response.status_code}: {response.text}")

                time.sleep(6)  # 6 Sekunden warten zwischen Abfragen

            except requests.exceptions.Timeout:
                # Timeout bei Long-Polling ist normal, nicht als ERROR loggen
                logger.debug("Signal API timeout (normal bei Long-Polling, keine Nachrichten)")
                time.sleep(5)  # Kurze Pause, dann weiter

            except requests.exceptions.ConnectionError as e:
                logger.error(f"Signal API connection error: {e}")
                logger.info("Retrying in 30 seconds...")
                time.sleep(30)  # Längere Pause bei Verbindungsproblemen

            except requests.exceptions.RequestException as e:
                logger.error(f"Error connecting to Signal API: {e}")
                time.sleep(10)  # Bei Verbindungsfehlern länger warten

            except Exception as e:
                logger.error(f"Unexpected error in listen_for_messages: {e}")
                time.sleep(5)

    def send_signal_message(self, phone_number: str, message: str,
                       auto_log: bool = True, message_type: str = None):
        """Sendet Nachricht über Signal API"""
        user_hash = self.hash_phone_number(phone_number)
        user_id = user_hash  # Für Logging

        logger.info(f"📤 Attempting to send message to user {user_hash}")
        logger.debug(f"📱 Phone: {phone_number[:4]}****, Message length: {len(message)}")

        try:
            data = {
                "message": message,
                "number": SIGNAL_NUMBER,
                "recipients": [phone_number]
            }
            logger.debug(f"🌐 Sending to Signal API: {SIGNAL_API_URL}/send")
            response = requests.post(f"{SIGNAL_API_URL}/send", json=data)
            logger.info(f"📡 Signal API response: {response.status_code}")

            if response.status_code == 201:
                logger.info(f"✅Message sent to {self.hash_phone_number(phone_number)}")
                # ✅ AUTOMATISCHES LOGGING
                if auto_log:
                    # Verwende message_type wenn gegeben, sonst "auto_logged"
                    log_type = message_type if message_type else "auto_logged_message"
                    self.log_interaction(user_id, log_type, message, is_bot=True)
                    logger.debug(f"📝 Auto-logged as: {log_type}")
                return True
            else:
                logger.error(f"❌Signal API error {response.status_code}: {response.text}")
                # ✅ Auch fehlgeschlagene Versuche loggen
                if auto_log:
                    log_type = f"{message_type}_failed" if message_type else "send_failed"
                    self.log_interaction(user_id, log_type, f"FAILED: {message}", is_bot=True)
                return False

        except Exception as e:
            logger.error(f"💥 Exception sending message to {user_hash}: {e}")
            # ✅ Exceptions auch loggen
            if auto_log:
                log_type = f"{message_type}_error" if message_type else "send_error"
                self.log_interaction(user_id, log_type, f"ERROR: {str(e)}", is_bot=True)

            return False

    def generate_ai_response(self, user_context: str, message_type: str, user_id: str = None, temperature: float = 1.0) -> str:
        """Generiert KI-Antworten mit OpenAI"""

        # Zentrale Fallback-Definition
        FALLBACKS = {
            "empathic_response": "Vielen Dank für deine Antwort. Ich höre dir zu.",
            "intervention_feedback_question": "Wie geht es dir mit dieser Übung?",
            "morning_greeting": "Guten Morgen! Ich wünsche dir einen achtsamen Tag.",
            "daily_question": "Wie ging es dir heute? Gab es einen Moment, in dem du Scham erlebt hast?",
            "conversation_closure": "Danke für deine Offenheit heute.",
            "optional_deepening": "Danke, dass du das mit mir teilst."
        }
        # ✅ KONTEXT IMMER LADEN (falls user_id vorhanden)
        context_info = ""
        if user_id:
            context_info = self.get_full_conversation_context(user_id)
            if context_info:
                logger.info(f"📚 Kontext geladen: {len(context_info)} Zeichen")

        # ✅ KONTEXT-PREFIX für alle Prompts vorbereiten
        context_prefix = ""
        if context_info:
            context_prefix = f"""=== BISHERIGER GESPRÄCHSVERLAUF ===
        {context_info}
        === ENDE GESPRÄCHSKONTEXT ===

        ⚠️ WICHTIG: Nutze obigen Kontext um authentisch und passend zu antworten!

        """

        prompt = ""

        try:
            if message_type == "empathic_response":
                #Checkfor shame level context
                if "SCHAM-LEVEL:" in user_context:
                    try:
                        lines = user_context.split('\n')
                        shame_level = lines[0].split(': ')[1] if len(lines) > 0 else "mittel"
                        actual_message = lines[1].split(': ')[1] if len(lines) > 1 else user_context
                    except (IndexError, ValueError):
                        logger.warning(f"Failed to parse shame level from: {user_context[:50]}")
                        shame_level = "mittel"
                        actual_message = user_context

                    shame_adaptations = {
                        "niedrig": "Antworte ressourcen-orientiert und ermutigend. Fokus auf Stärken und Bewältigung.",
                        "mittel": "Antworte einfühlsam und unterstützend. Normale therapeutische Haltung.",
                        "hoch": "Antworte sehr sanft und validierend. Maximal unterstützend, nicht herausfordernd."
                    }

                    adaptation = shame_adaptations.get(shame_level, shame_adaptations["mittel"])
                    # Response Count ermitteln (nur für Woche 1, für Woche 2 anders)
                    if user_id:
                        user = self.users.get(user_id)
                        week = 1 if user and user.phase == "Woche 1" else 2
                        response_count = self.get_response_count_for_week(user_id, week)
                    else:
                        response_count = 0

                    if len(actual_message.strip()) <= 12:
                        prompt = f'{adaptation} Antworte sehr kurz (max 8 Wörter) auf: "{actual_message}" - stelle KEINE Fragen!'
                    else:
                        if response_count <= 2:
                            prompt = f"""{context_prefix} Du bist ein empathischer Gesprächspartner.

                           {adaptation}
                           Nutzer-NACHRICHT: "{actual_message}"
                           
                           Antworte wie ein Psychotherapeut es tun würde (nicht klischeehaft).
                           
                           WICHTIG - Variiere deinen Antwort-Stil natürlich
                           - MANCHMAL: Kurze Validation ohne viel Wiederholung
                            - MANCHMAL: Direkt zur vertiefenden Frage
                            - MANCHMAL: Kurze Spiegelung + Frage
                            - NICHT bei jeder Antwort alles wiederholen was der User sagte!
                            - NICHT immer mit "Es klingt als..." beginnen!
                            Stelle vertiefende Rückfragen aber stelle NICHT bei jedem Austausch eine Frage.
                            Stil: Menschlich, authentisch, präzise. 2-3 Sätze maximum.
                            Fokus: Echtes Interesse zeigen.
                           """
                        else:
                            prompt = f"""{context_prefix} Du bist ein empathischer Gesprächspartner.
                            {adaptation}

                        Nutzer-NACHRICHT: "{actual_message}"
                        Response Count: {response_count} (Das Gespräch läuft schon eine Weile)
                        WICHTIG - Gib dem User explizit die Wahl zu pausieren:
                        STRUKTUR (2-3 Sätze):
                        1. Kurze Validation (1 Satz, NICHT alles wiederholen!)
                        2. Optionale Einladung weiterzumachen MIT klarer Ausstiegsmöglichkeit
                        
                        Beispiel: "Falls du magst, kannst du mir gerne mehr darüber erzählen. Ansonsten sprechen wir morgen weiter."
"""
                else:
                    # Fallback wenn kein Scham-Level angegeben
                    prompt = f"""{context_prefix}Antworte einfühlsam auf: "{user_context}"
                        Sei authentisch und bodenständig. Keine kitschigen Metaphern."""

            # Spezieller Type für optionale Vertiefung
            elif message_type == "optional_deepening":
            # user_context ist hier bereits ein vollständiger prompt
                prompt = user_context

            elif message_type == "conversation_closure":
                prompt = f""" {context_prefix} Du beendest ein therapeutisches Gespräch über Scham natürlich menschlich und wertschätzend.

                    NUTZER-ANTWORT: "{user_context}"

                    Schreibe eine kurze Abschluss-Nachricht (1-2 Sätze), die:
                    - Dank für die Offenheit ausdrückt
                    - Wertschätzt was geteilt wurde  
                    - Das Gespräch beendet
                    - KEINE neuen Fragen stellt
                    """
            elif message_type == "intervention_feedback_question":
                prompt = f"""{context_prefix}Erstelle eine kurze, Feedback-Frage nach einer Selbstmitgefühls-Übung.

            Kontext: {user_context}

            Die Frage soll:
            - Kurz und offen sein (1-2 Sätze)
            - Zur Reflexion über die Übung einladen
            - Empathisch und unterstützend wirken, aber menschlich 

            Beispiele: "Wie fühlst du dich nach dieser Übung?" oder "Was nimmst du aus diesem Moment mit?"
            """

            elif message_type == "morning_greeting":
                # Scham-Facts Array für Rotation
                scham_facts = [
                    "Scham aktiviert dieselben Gehirnregionen wie körperlicher Schmerz",
                    "Bei Schuld denkst du 'Ich habe Fehler gemacht', bei Scham 'Ich BIN ein Fehler'",
                    "Je mehr wir Scham verstecken, desto stärker wird sie - Sprechen nimmt ihr die Macht",
                    "Scham half uns früher, in Gruppen zu überleben. Heute kann sie uns aber in selbstkritischen Mustern festhalten",
                    "Selbstkritik führt zu mehr Angst und schlechterer Leistung - Selbstmitgefühl motiviert zu Wachstum",
                    "Verletzlichkeit, nicht Perfektion, ist die Grundlage für echte Verbindung"
                ]

                # Einfache Rotation basierend auf aktuellem Tag
                import datetime
                day_of_year = datetime.datetime.now().timetuple().tm_yday
                selected_fact = scham_facts[day_of_year % len(scham_facts)]

                prompt = f""" {context_prefix}Erstelle eine kurze, ermutigende Morgengrüßung (2-3 Sätze).
                    Verwende genau diesen Scham-Fakt: "{selected_fact}"

                    Kombiniere:
                    1. Kurze Begrüßung  
                    2. Den gegebenen Scham-Fakt (variiere die Formulierung!)
                    3. Sanfte Tagesermutigung

                    Stil: Natürlich, menschlich, ermutigend. Keine Fragen stellen. Beziehe dich subtil auf gestrige Themen aus dem Kontext falls relevant!
                    """

            elif message_type == "daily_question":
                prompt = f"""{context_prefix}Erstelle eine einfühlsame Frage über Schamgefühle, die explizit zur Antwort auffordert.

                Kontext: {user_context}

                - Beziehe dich auf den spezifischen Fokusbereich falls erwähnt
                - Verwende offene W-Fragen (Wie, Was, Wann) für detaillierte Antworten
                - Fordere explizit zum Antworten auf: Magst du mir erzählen..., Kannst du beschreiben...
                - Frage sanft nach konkreten Situationen oder Beispielen
                - Warm aber neugierig, 1-2 Sätze maximum
                - Vermeide Wiederholungen zu den letzten Tagen! 

                Beispiel: Magst du mir erzählen, wie sich ... für dich anfühlt? Kannst du eine konkrete Situation beschreiben?
                
                - Gebe dem user auch die option über etwas anderes zu reden, wenn er möchte.
                """
            else:
                # Unbekannter message_type - Fallback
                logger.warning(f"Unknown message_type: {message_type}")
                prompt = f"{context_prefix}Antworte empathisch und unterstützend auf: {user_context}. Sei authentisch, menschlich, nicht kitschig."

            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system",
                     "content": "Du bist ein empathischer Therapeut mit 10 Jahren Praxis in Schamforschung. Antworte auf Deutsch, benutze die informelle Du-Form. Halte dich kurz und menschlich. WICHTIG: Sei authentisch, nicht kitschig."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=250,
                temperature=temperature
            )
            # Check for None BEFORE calling strip()
            raw_content = response.choices[0].message.content
            if raw_content is None or not raw_content.strip():
                logger.warning(f"OpenAI returned None/empty response for {message_type}")
                return FALLBACKS.get(message_type, "Danke, dass du das mit mir teilst.")

            generated_response = raw_content.strip()
            # Log temperature wenn nicht Standard
            if temperature != 0.7:
                logger.debug(f"Generated {message_type} with temperature {temperature}")

            return generated_response

        except Exception as e:
            error_msg = str(e)

            # Content Filter spezifisch erkennen und detailliert loggen
            if "content_filter" in error_msg or "ResponsibleAIPolicyViolation" in error_msg:

                # ============= DETAILLIERTES FILTER LOGGING =============
                logger.error(f"🚫 Content Filter triggered for {message_type}")
                logger.error(f"👤 USER_ID: {user_id if user_id else 'UNKNOWN'}")

                # 2. Message Type und Zeitstempel
                logger.error(f"📝 Message Type: {message_type}")
                logger.error(f"⏰ Timestamp: {datetime.datetime.now().isoformat()}")

                # 3. Extrahiere und zeige Filter-Gründe
                import re
                filter_results = {}

                # Parse content_filter_result aus der Error-Message
                filter_match = re.search(r"'content_filter_result': \{([^}]+)\}", error_msg)
                if filter_match:
                    logger.error(f"🔍 FILTER REASONS:")

                    # Extrahiere einzelne Filter-Kategorien
                    categories = ['hate', 'self_harm', 'sexual', 'violence', 'jailbreak']
                    for category in categories:
                        cat_match = re.search(
                            rf"'{category}': \{{'filtered': (True|False), 'severity': '(\w+)'(?:, 'detected': (True|False))?\}}",
                            error_msg
                        )
                        if cat_match:
                            filtered = cat_match.group(1) == 'True'
                            severity = cat_match.group(2)

                            if filtered:
                                logger.error(f"   ❌ {category.upper()}: FILTERED (severity: {severity})")
                            else:
                                logger.error(f"   ✅ {category}: passed (severity: {severity})")
                else:
                    logger.error(f"🔍 Could not parse filter details from error")

                # 4. Zeige Prompt (erste 400 Zeichen)
                logger.error(f"\n📄 PROMPT CONTENT (first 400 chars):")
                logger.error("-" * 80)
                try:
                    if 'prompt' in locals():
                        prompt_preview = prompt[:400].replace('\n', '\n    ')
                        logger.error(f"    {prompt_preview}")
                        if len(prompt) > 400:
                            logger.error(f"    ... [truncated, total length: {len(prompt)} chars]")
                    else:
                        logger.error("    Prompt variable not available")
                except Exception as prompt_err:
                    logger.error(f"    Error showing prompt: {prompt_err}")
                logger.error("-" * 80)

                # 5. User Context (wenn verfügbar)
                logger.error(f"\n📋 USER CONTEXT (first 200 chars):")
                logger.error("-" * 80)
                try:
                    if 'user_context' in locals():
                        context_preview = str(user_context)[:200].replace('\n', '\n    ')
                        logger.error(f"    {context_preview}")
                    else:
                        logger.error("    User context not available")
                except Exception as ctx_err:
                    logger.error(f"    Error showing context: {ctx_err}")
                logger.error("-" * 80)

                # 6. Letzte User-Nachrichten aus Tagebuch
                if user_id:
                    logger.error(f"\n📚 RECENT USER MESSAGES:")
                    logger.error("-" * 80)
                    try:
                        tagebuch_file = os.path.join(TAGEBUCH_DIR, f"{user_id}_tagebuch.jsonl")
                        if os.path.exists(tagebuch_file):
                            with open(tagebuch_file, 'r', encoding='utf-8') as f:
                                lines = f.readlines()
                                # Zeige letzte 5 Nachrichten
                                recent_messages = lines[-5:] if len(lines) >= 5 else lines

                                for line in recent_messages:
                                    try:
                                        msg = json.loads(line)
                                        timestamp = msg.get('timestamp', 'N/A')
                                        sender = msg.get('sender', 'unknown')
                                        message_text = msg.get('message', '')[:150]
                                        logger.error(f"    [{timestamp}] {sender}: {message_text}")
                                    except json.JSONDecodeError:
                                        continue
                        else:
                            logger.error(f"    Tagebuch file not found: {tagebuch_file}")
                    except Exception as tb_err:
                        logger.error(f"    Error reading tagebuch: {tb_err}")
                    logger.error("-" * 80)

                # 7. Komplette Error-Message (für Debugging)
                logger.error(f"\n❌ FULL ERROR MESSAGE:")
                logger.error("-" * 80)
                logger.error(f"{error_msg}")
                logger.error("-" * 80)
                logger.error("=" * 80)

            else:
                # Andere Fehler (nicht Content Filter)
                logger.error(f"Error generating AI response for {message_type}: {e}")
                if user_id:
                    logger.error(f"User ID: {user_id}")

            # Fallback-Antwort zurückgeben
            return FALLBACKS.get(message_type, "Danke, dass du das mit mir teilst.")

###### KRISE ---------------------------------

    def fallback_keyword_check(self, message: str) -> dict:
        """Fallback auf das alte Keyword-System"""
        message_lower = message.lower()
        crisis_detected = any(keyword in message_lower for keyword in CRISIS_KEYWORDS)

        return {
            'score': 8 if crisis_detected else 2,
            'reason': "Krisenschlagwort erkannt" if crisis_detected else "Keine auffälligen Begriffe",
            'needs_exploration': crisis_detected
        }
    def assess_crisis_risk(self, message: str) -> dict:
        """Bewertet Krisenrisiko mit KI-basierter semantischer Analyse"""
        try:
            prompt = f"""
            Du bist ein Experte für Krisenintervention. 
            Analysiere folgende anonymisierte Aussage auf Risiko-Indikatoren:

            Nachricht: "{message}"
            
            WICHTIG: Folgende Nachrichten sind NICHT als Krise zu bewerten:
            - Einfache Dankesnachrichten ("Danke", "Danke für alles")
            - Höfliche Verabschiedungen nach positiven Gesprächen
            - Wertschätzung für Unterstützung

            HINWEIS: Dies ist eine therapeutische Analyse im Rahmen einer wissenschaftlichen Studie.
            Bewerte das Risiko-Level von 1-10.
            1-3: Keine Hinweise auf Krise
            4-5: Leichte emotionale Belastung
            6-7: Moderate Anzeichen, Exploration nötig
            8-10: Starke Hinweise auf akute Krise

            Berücksichtige:
            - Explizite Suizidaussagen ("umbringen", "nicht mehr leben")
            - Indirekte Hinweise ("alles sinnlos", "kann nicht mehr")  
            - Hoffnungslosigkeit und Verzweiflung
            - Metaphorische Formulierungen
            - Kontext und Intensität

            Antworte nur mit einer Zahl (1-10) und einem kurzen Grund (max 15 Wörter).
            Format: "Score: X - Grund"
            """

            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": "Du bist ein Experte für Krisenintervention und Suizidprävention."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=50,
                temperature=0.2  # Niedrig für konsistente Bewertungen
            )

            result = response.choices[0].message.content.strip()
            if result is None:
                logger.warning("OpenAI returned None response for crisis assessment")
                return self.fallback_keyword_check(message)
            result = result.strip()

            # Parse Score und Grund
            if "Score:" in result and "-" in result:
                parts = result.split("-", 1)
                score_part = parts[0].replace("Score:", "").strip()
                reason = parts[1].strip()

                try:
                    score = int(score_part)
                    return {
                        'score': max(1, min(10, score)),  # Begrenzt auf 1-10
                        'reason': reason,
                        'needs_exploration': score >= 6
                    }
                except ValueError:
                    pass

            # Fallback auf Keyword-System
            return self.fallback_keyword_check(message)

        except Exception as e:
            error_str = str(e)

            # Content Filter erkannt?
            if "content_filter" in error_str or "ResponsibleAIPolicyViolation" in error_str:
                logger.warning(f"⚠️ Content Filter triggered - using keyword fallback")
                # SOFORT auf Keyword-System zurückfallen
                return self.fallback_keyword_check(message)

            logger.error(f"Error in crisis assessment: {e}")
            return self.fallback_keyword_check(message)

    def handle_crisis_exploration(self, phone_number: str, user_id: str, initial_assessment: dict):
        """Führt validierend-empathische Exploration durch"""

        exploration_messages = [
            "Es klingt, als würdest du gerade durch eine schwere Zeit gehen. Magst du mir mehr darüber erzählen?",
            "Das hört sich wirklich belastend an. Wie geht es dir denn gerade?",
            "Ich merke, dass es dir nicht gut geht. Kannst du mir sagen, was dich so beschäftigt?"
        ]

        import random
        exploration_msg = random.choice(exploration_messages)

        # Markiere User als "in exploration"
        if user_id in self.users:
            self.users[user_id].crisis_exploration = {
                'active': True,
                'initial_score': initial_assessment['score'],
                'initial_reason': initial_assessment['reason'],
                'started_at': datetime.datetime.now().isoformat()
            }
            self.save_user_state(user_id)

        self.send_signal_message(phone_number, exploration_msg)

        self.log_crisis_event(user_id, "crisis_exploration_started", {
            'initial_score': initial_assessment['score'],
            'initial_reason': initial_assessment['reason'],
            'exploration_message': exploration_msg,
            'trigger_message': "User message that triggered exploration would be logged separately"
        })

        logger.info(f"Started crisis exploration for user {user_id} (initial score: {initial_assessment['score']})")

    def process_exploration_response(self, phone_number: str, user_id: str, response: str):
        """Verarbeitet Antwort auf Crisis Exploration"""

        # Finale Bewertung der Exploration-Antwort
        final_assessment = self.assess_crisis_risk(response)

        user = self.users.get(user_id)
        initial_assessment = user.crisis_exploration if user else {}

        # Kombiniere Initial- und Final-Score für Gesamtbewertung
        combined_score = (initial_assessment.get('initial_score', 6) + final_assessment['score']) / 2

        logger.info(
            f"Crisis exploration result for {user_id}: initial={initial_assessment.get('initial_score')}, final={final_assessment['score']}, combined={combined_score}")

        if combined_score >= 7:
            # Akute Krise bestätigt
            self.handle_confirmed_crisis(phone_number, user_id, combined_score)
        else:
            # Krise nicht bestätigt - empathisch weiterführen
            self.handle_false_alarm(phone_number, user_id, combined_score)

        # Exploration beenden
        if user_id in self.users:
            self.users[user_id].crisis_exploration = {'active': False}
            self.save_user_state(user_id)

    def handle_confirmed_crisis(self, phone_number: str, user_id: str, final_score: float):
        """Behandelt bestätigte Krisensituation"""
        if user_id in self.users:
            self.users[user_id].crisis_detected = True
            self.users[user_id].crisis_final_score = final_score
            self.users[user_id].phase = "stopped"
            self.save_user_state(user_id)

        crisis_message = f"""Ich merke, dass du gerade wirklich viel durchmachst und es dir sehr schwer fällt. Das tut mir leid.

    In so schweren Zeiten ist es wichtig, dass du dir professionelle Hilfe holst. Du musst das nicht alleine durchstehen.

    {HELP_TEXT}

    Ich denke, es ist besser, wenn wir die Studie erstmal pausieren, damit du dich um dich kümmern kannst.

    Falls du später doch weitermachen möchtest, melde dich bei der Studienleitung unter jakob.fink-lamotte@uni-potsdam.de"""

        self.send_signal_message(phone_number, crisis_message)

        self.log_crisis_event(user_id, "confirmed_crisis", {
            'final_score': final_score,
            'intervention_sent': True,
            'study_stopped': True,
            'help_resources_provided': True
        })

        logger.warning(f"Confirmed crisis intervention for user {user_id} (final score: {final_score})")

    def handle_false_alarm(self, phone_number: str, user_id: str, final_score: float):
        """Behandelt Fehlalarm - empathisch weiterführen"""

        empathic_responses = [
            "Danke, dass du mir das erzählt hast. Es ist völlig in Ordnung, schwierige Zeiten zu durchleben. Gibt es Personen, denen du dich dir mit diesem Thema anvertrauen kannst?",
            "Ich höre, dass es dir nicht leicht fällt. Das sind wichtige Gefühle, die du da beschreibst. Gibt es Personen, denen du dich dir mit diesem Thema anvertrauen kannst?",
            "Danke für deine Offenheit. Es ist normal, dass das Leben manchmal überwältigend ist. Gibt es Personen, denen du dich dir mit diesem Thema anvertrauen kannst? "
        ]

        import random
        response = random.choice(empathic_responses)

        self.send_signal_message(phone_number, response)
        self.log_crisis_event(user_id, "crisis_false_alarm", {
            'final_score': final_score,
            'continued_study': True,
            'empathic_response_sent': True
        })

        logger.info(f"False alarm handled empathically for user {user_id} (final score: {final_score})")

    def check_for_crisis(self, message: str, phone_number: str, user_id: str):
        """Erweiterte Crisis Detection - Hauptfunktion"""

        user = self.users.get(user_id)
        # Sichere Prüfung auf crisis_exploration
        if user:
            crisis_exploration = getattr(user, 'crisis_exploration', {}) or {}
            if crisis_exploration.get('active', False):
                # User ist in Exploration - verarbeite Antwort
                self.process_exploration_response(phone_number, user_id, message)
                self.log_interaction(user_id, "crisis_exploration_response", message, is_bot=False)
                return True  # Nachricht wurde verarbeitet

        # Normale Crisis Assessment
        assessment = self.assess_crisis_risk(message)

        logger.info(f"Crisis assessment for user {user_id}: {assessment}")

        if assessment['needs_exploration']:
            # Score ≥6: Starte Exploration
            self.handle_crisis_exploration(phone_number, user_id, assessment)

            self.log_interaction(user_id, "potential_crisis_message", message, is_bot=False)

            return True  # Nachricht wurde verarbeitet

        return False  # Keine Krise, normale Verarbeitung

    def log_crisis_event(self, user_id: str, event_type: str, details: dict):
        """Protokolliert Krisenereignisse in separater Datei"""
        crisis_log_path = os.path.join(TAGEBUCH_DIR, "crisis_events.jsonl")

        # Telefonnummer für Kontext holen
        phone_number = self.get_phone_from_user_id(user_id)

        crisis_entry = {
            'timestamp': datetime.datetime.now().isoformat(),
            'user_id': user_id,
            'phone_last_4': phone_number[-4:] if phone_number else 'unknown',
            'event_type': event_type,
            'details': details,
            'user_phase': self.users[user_id].phase if user_id in self.users else 'unknown',
            'user_day': self.users[user_id].day if user_id in self.users else 0
        }

        # In Crisis-Log-Datei schreiben
        with open(crisis_log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(crisis_entry, ensure_ascii=False) + '\n')

        # Auch in Console loggen für Aufmerksamkeit
        logger.warning(f"🚨 CRISIS EVENT: {event_type} for user {user_id}")
#### -------------------------------------

    def handle_start_command(self, phone_number: str):
        """Behandelt Start-Befehl"""
        logger.info(f"phone number: {phone_number}")
        user_id = self.hash_phone_number(phone_number)
        self.save_phone_mapping(user_id, phone_number)

        if user_id not in self.users:
            self.users[user_id] = UserState(user_id=user_id)

        user = self.users[user_id]
        if user.phase != "waiting":
            self.send_signal_message(phone_number, "Du hast bereits gestartet oder die Studie beendet.")
            return

        # Nachricht 1
        welcome_message_1 = """
👋 Hallo und herzlich Willkommen bei der Studie zu Selbstmitgefühl bei Scham. 
In den nächsten zwei Wochen werde ich dich begleiten.

Bevor wir starten sind hier noch ein paar wichtige Infos: """

        # Nachricht 2
        welcome_message_2 = """
Damit du täglich Nachrichten von mir erhalten kannst, wird deine Telefonnummer verschlüsselt gespeichert. So bleiben deine Daten bestmöglich geschützt.🔐

✍️ Bitte antworte ausschließlich mit Textnachrichten, da ich Sprachnachrichten aktuell noch nicht verarbeiten kann. 

Dieser Chatbot ist Teil einer wissenschaftlichen Studie und kein Kriseninterventionsangebot.
Wenn es dir sehr schlecht geht oder du an Suizid denkst, wende dich bitte an:

📞 Telefonseelsorge: 08001110111 
🌐 Online-Chat: online.telefonseelsorge.de
🚑 Notruf: 112 

Du bist nicht allein – Hilfe ist jederzeit erreichbar.
"""
        #  Nachricht 3
        welcome_message_3 = """
Hier sind außerdem ein paar hilfreiche Befehle:

'Status' = Zeigt dir deinen Fortschritt.
'Hilfe' = Hilft dir bei Fragen oder wenn du dich in einer Krise befindest.
'Stop' = Bricht die Studie ab.
"""
        welcome_message_4 = """ Alles klar? Dann kanns jetzt losgehen! 
        
🔑 Bitte gebe zuerst deinen persönlichen 6-stelligen Code ein:

Zur Erinnerung: 
- Erster Buchstabe des Vornamens der Mutter
- Letzter Buchstabe des Geburtsortes
- Tag des Geburtstags als zweistellige Zahl (z.B. "08")
- Zweite Ziffer der Postleitzahl des Geburtsortes 
- Anzahl der Buchstaben des Geburtsmonats als einstellige Zahl (z.B. "5" für April) 
"""

        user.phase = "onboarding"
        user.start_date = datetime.datetime.now().isoformat()
        user.day = 1

        self.users[user_id] = user
        self.save_user_state(user_id)

        self.send_signal_message(phone_number, welcome_message_1, message_type="start_command_1")

        time.sleep(4)

        self.send_signal_message(phone_number, welcome_message_2, message_type="start_command_2")

        time.sleep(8)

        self.send_signal_message(phone_number, welcome_message_3, message_type="start_command_3")

        time.sleep(8)

        self.send_signal_message(phone_number, welcome_message_4, message_type="start_command_4")

    def handle_onboarding(self, phone_number: str, message: str):
        """Behandelt Onboarding-Phase"""

        user_id = self.hash_phone_number(phone_number)
        user = self.users[user_id]

        # SICHERHEITSPRÜFUNG: week1_responses initialisieren falls None
        if user.week1_responses is None:
            user.week1_responses = []

        if user.onboarding_step == 0:
            # Personal Code validieren
            is_valid, error_message = self.validate_personal_code(message)

            if not is_valid:
                # Fehlerhafte Eingabe - nochmal nachfragen
                retry_message = f"""
                        {error_message}
Bitte gib deinen 6-stelligen Code erneut ein:
                        """
                self.send_signal_message(phone_number, retry_message)
                self.log_interaction(user_id, "code_validation_error", error_message)
                return  # Wichtig: Funktion beenden, Schritt nicht erhöhen

            # Gültiger Code - speichern und weiter
            user.personal_code = message.strip().upper()  # Normalisiert speichern
            user.onboarding_step = 1

            intro_message = """
Vielen Dank! 

Um dich in den nächsten zwei Wochen bestmöglich begleiten zu können, möchte ich dich zunächst ein wenig kennenlernen. Dafür habe ich 7 kurze Fragen vorbereitet, die sich um verschiedene Aspekte von Schamgefühlen drehen.

Es gibt dabei keine "richtigen" oder "falschen" Antworten - es geht nur darum, wie du persönlich diese Dinge erlebst. Deine Antworten helfen mir zu verstehen, welche Bereiche für dich besonders relevant sind.

Bitte antworte jeweils mit einer Zahl zwischen 1 (trifft gar nicht zu) und 10 (trifft sehr stark zu). 

Lass dir gerne die Zeit, die du brauchst. Es ist völlig in Ordnung, kurz in dich hineinzuspüren, bevor du antwortest.🧡
"""
            self.send_signal_message(phone_number, intro_message)
            self.log_interaction(user_id, "onboarding_q1", intro_message)

            # ✅ SEPARATE FRAGE 1 nach kurzer Pause
            def send_first_question():
                time.sleep(13)  # 8 Sekunden zum Verarbeiten der Einleitung

                first_question = "❓Frage 1: Wie stark hast du das Gefühl, dass du dich grundsätzlich oft für dich selbst oder deine Persönlichkeit schämst, unabhängig von konkreten Situationen?"

                success = self.send_signal_message(phone_number, first_question)
                if success:
                    self.log_interaction(user_id, "onboarding_q1", first_question)
                    logger.info(f"✅ First question sent to {user_id} after intro pause")
                else:
                    logger.error(f"Failed to send first question to {user_id}")

            # Thread für erste Frage starten
            question_thread = threading.Thread(target=send_first_question, daemon=True)
            question_thread.start()

        elif user.onboarding_step <= 7:
            # VALIDIERUNG
            try:
                rating = int(message.strip())
                if not (1 <= rating <= 10):
                    raise ValueError("Außerhalb des Bereichs")
            except ValueError:
                # Fehlerhafte Eingabe - nochmal nachfragen
                error_msg = "Hoppala! Bitte gib eine Zahl zwischen 1 und 10 ein."
                self.send_signal_message(phone_number, error_msg)
                self.log_interaction(user_id, "rating_validation_error", error_msg)
                return  # Wichtig: Funktion beenden, Schritt nicht erhöhen

            # Onboarding-Fragen
            questions = [
                "❓Frage 2: Wie sehr fühlst du dich manchmal unsicher oder unwohl wegen deines Aussehens oder bestimmter Körpermerkmale?",
                "❓Frage 3: Wie stark belastet dich rückblickend Scham über Dinge, die du getan oder entschieden hast?",
                "❓Frage 4: Wie stark hast du das Gefühl, dass dir bestimmte Eigenschaften oder Seiten von dir peinlich oder unangenehm sind?",
                "❓Frage 5: Wie oft ziehst du dich von anderen zurück, weil du dich für deine Gedanken, Gefühle oder Handlungen schämst?",
                "❓Frage 6: Wie stark kritisierst du dich selbst innerlich, wenn du dich schlecht fühlst?",
                "❓Frage 7: Wie sehr hast du das Gefühl, dass du mit Schamgefühlen schlecht umgehen kannst oder darunter leidest?"
            ]

            # Antwort speichern
            response_data = {
                'question_number': user.onboarding_step,
                'response': message,
                'timestamp': datetime.datetime.now().isoformat()
            }
            user.week1_responses.append(response_data)

            if user.onboarding_step < 7:
                # Nächste Frage
                next_question = questions[user.onboarding_step - 1]
                user.onboarding_step += 1
                self.send_signal_message(phone_number, next_question)
                self.log_interaction(user_id, f"onboarding_q{user.onboarding_step}", next_question)
            else:
                # Onboarding abgeschlossen
                completion_message = """
Vielen Dank für deine Offenheit 💜. In den nächsten 7 Tagen werde ich dir täglich eine vertiefende Frage stellen, um dich und dein Schamempfinden noch besser kennenzulernen.

Die Fragen erhälst du jeweils zwischen 17 und 21 Uhr. Bitte nimm dir einen Moment Zeit, diese in Ruhe zu beantworten. Ab morgen gehts los! 🤗

Du kannst jederzeit "Status" eingeben, um deinen Fortschritt zu sehen.
"""
                user.phase = "Woche 1"
                user.onboarding_step = 8
                user.pending_evening_questions = []
                self.send_signal_message(phone_number, completion_message)
                self.log_interaction(user_id, "onboarding_complete", completion_message)

        self.users[user_id] = user
        self.save_user_state(user_id)

    def assess_user_shame_level(self, user: UserState) -> str:
        """Bewertet Gesamt-Scham-Level basierend auf Eingangsbefragung"""

        if not user.week1_responses or len(user.week1_responses) < 7:
            return "mittel"  # Fallback

        # Alle Ratings sammeln
        ratings = []
        for resp in user.week1_responses[:7]:
            try:
                rating = int(resp.get('response', '5'))
                ratings.append(rating)
            except:
                ratings.append(5)  # Fallback

        # Durchschnitt berechnen
        avg_rating = sum(ratings) / len(ratings)
        max_rating = max(ratings)

        # Klassifikation
        if avg_rating <= 3.5 or max_rating <= 5:
            return "niedrig"  # Wenig Scham-Belastung
        elif avg_rating <= 6.5 or max_rating <= 7:
            return "mittel"  # Moderate Scham-Belastung
        else:
            return "hoch"  # Hohe Scham-Belastung

    def generate_day2_goal_question(self) -> str:
        """Generiert die spezielle Zielsetzungsfrage für Tag 2"""

        goal_question = """Hey! 🌱
Nach dem gestrigen Kennenlernen möchte ich heute etwas Besonderes mit dir machen: Lass uns gemeinsam ein persönliches Ziel für diese zwei Wochen definieren.
Stell dir vor, es sind zwei Wochen vergangen und du blickst zufrieden auf diese Zeit zurück. In Bezug auf Selbstmitgefühl und den Umgang mit Schamgefühlen:
Was möchtest du erreicht haben?

Das kann zum Beispiel sein:
"Ich möchte liebevoller zu mir selbst sprechen" oder
"Ich möchte mich trauen, anderen von meinen Schwierigkeiten zu erzählen"

Nimm dir einen Moment Zeit und formuliere in 1-2 Sätzen: Wie möchtest du am Ende dieser zwei Wochen mit Scham und Selbstmitgefühl umgehen?
Dieses Ziel wird unser Kompass für die kommende Zeit. ✨"""

        return goal_question

    def handle_goal_response(self, phone_number: str, message: str, user_id: str):
        """Behandelt die Antwort auf die Zielsetzungsfrage"""

        user = self.users[user_id]

        # Ziel speichern
        user.personal_goal = message.strip()
        user.goal_set_date = datetime.datetime.now().isoformat()

        # SCHRITT 1: Bestätigung generieren
        confirmation_prompt = f"""Der Nutzer hat als persönliches Ziel definiert: '{message}'. 

        Schreibe eine kurze, wertschätzende Bestätigung (1-2 Sätze), die:
        - Das Ziel würdigt 
        - Mut macht
        - Zur Vertiefung überleitet

        Beispiel: "Ein wundervolles Ziel! Lass uns gleich schauen, wie du dem näher kommen kannst."
        Stil: Ermutigend, nicht überschwänglich."""

        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": "Du bist ein einfühlsamer therapeutischer Chatbot."},
                    {"role": "user", "content": confirmation_prompt}
                ],
                max_tokens=100,
                temperature=0.7
            )
            confirmation = response.choices[0].message.content.strip()
        except:
            confirmation = "Ein wichtiges Ziel! Lass uns schauen, wie du dem näher kommen kannst."

        # SCHRITT 2: Vertiefende Frage basierend auf Ziel + Scham-Level
        shame_level = self.assess_user_shame_level(user)

        follow_up_prompt = f"""Erstelle EINE einfache vertiefende Frage basierend auf diesem Ziel: "{message}"

        Nutzer-Scham-Level: {shame_level} (niedrig/mittel/hoch)
        Stil: {"Sanft und ermutigend" if shame_level == "niedrig" else "Einfühlsam und unterstützend" if shame_level == "mittel" else "Sehr vorsichtig und validierend"}

        Die Frage soll:
        - Konkret zum Ziel passen
        - Zum Nachdenken anregen
        - {"Ressourcen-orientiert" if shame_level == "niedrig" else "Mitfühlend" if shame_level == "mittel" else "Sehr behutsam"} sein

        Beispiele:
        - "Wann fällt dir das besonders schwer?"
        - "In welchen Momenten bemerkst du, dass..."
        - "Wann ist deine innere Stimme besonders kritisch?"
        
        WICHTIG: 
        - Nur EINE W-Frage (Wann/Wo/In welchen Situationen)
        - KEINE Doppelfragen mit "und"
            1-2 Sätze maximum."""

        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": "Du bist ein empathischer Therapeut der an Stärken anknüpft."},
                    {"role": "user", "content": follow_up_prompt}
                ],
                max_tokens=120,
                temperature=0.7
            )
            follow_up_question = response.choices[0].message.content.strip()
        except:
            follow_up_question = "Was denkst du, könnte dir dabei helfen, diesem Ziel näher zu kommen?"

        # SCHRITT 3: Beide Nachrichten senden
        combined_message = f"{confirmation}\n\n{follow_up_question}"

        self.send_signal_message(phone_number, combined_message)

        # Logging
        self.log_interaction(user_id, "goal_response", message, is_bot=False)
        self.log_interaction(user_id, "goal_confirmation_plus_question", combined_message, is_bot=True)

        # Pending question als beantwortet markieren + neue hinzufügen
        if user.pending_evening_questions:
            for q in user.pending_evening_questions:
                if q['day'] == 2 and q.get('question_type') == 'goal_setting':
                    q['answered'] = True
                    q['answered_at'] = datetime.datetime.now().isoformat()

                    # neue vertiefende Frage hinzufügen
                    follow_up_entry = {
                        'day': 2,
                        'question': follow_up_question,
                        'question_type': 'goal_exploration',
                        'sent_at': datetime.datetime.now().isoformat(),
                        'answered': False,
                        'response_count': 0
                    }
                    user.pending_evening_questions.append(follow_up_entry)
                    break

        self.save_user_state(user_id)
        logger.info(f"Goal set + follow-up question sent for {user_id}: '{message[:30]}...'")

    def generate_optional_deepening_response(self, user_message: str, user_id: str) -> str:
        """Generiert empathische Antwort mit optionaler Vertiefung"""

        shame_level = self.assess_user_shame_level(self.users[user_id])
        message_length = len(user_message.strip())

        # Stil-Anpassung basierend auf Shame-Level definieren
        if shame_level == "niedrig":
            style_instruction = "Ermutigend und ressourcen-orientiert"
        elif shame_level == "mittel":
            style_instruction = "Einfühlsam und unterstützend"
        else:  # shame_level == "hoch"
            style_instruction = "Sehr sanft und validierend"

        # Bei sehr kurzen Antworten: Nur validieren, keine Vertiefung
        if message_length <= 15:
            prompt = f"""Der User hat kurz geantwortet: "{user_message}"

                    Scham-Level: {shame_level}

                    Schreibe eine sehr kurze, wertschätzende Antwort (1 Satz), die:
                    - Die Antwort würdigt ohne nachzuhaken
                    - Das Gespräch natürlich beendet
                    - KEINE weitere Frage stellt
                    - Zum nächsten Tag überleitet

                    Stil: {style_instruction}, abschließend"""
        else:
            prompt = f"""Der User hat auf eine therapeutische Scham-Frage geantwortet: "{user_message}"

    Scham-Level: {shame_level}

    Erstelle eine 2-teilige Antwort:
    1. Empathische Validation der Antwort (1-2 Sätze)
    2. OPTIONALE Vertiefungseinladung mit klarem Ausstieg

    Beispiele für den optionalen Teil:
    - "Falls du möchtest, kannst du mir gerne mehr dazu erzählen. Ansonsten sprechen wir morgen weiter."
    - "Magst du mir noch erzählen, was dir dabei am schwersten fällt? Oder lassen wir es für heute dabei."
    - "Wenn du Lust hast, erzähl gerne mehr. Falls nicht, ist das auch völlig okay - wir können morgen weitermachen."

    Stil: {style_instruction}
    WICHTIG: Dem User explizit die Wahl lassen! Nicht drängen! """

        return self.generate_ai_response(prompt, "optional_deepening", user_id)

    def handle_weekly_response(self, phone_number: str, message: str, user_id: str):
        """Unified response handler für Week 1 und Week 2"""
        if user_id is None:
            user_id = self.hash_phone_number(phone_number)

        user = self.users[user_id]
        week = 1 if user.phase == "Woche 1" else 2

        self.log_interaction(user_id, f"week{week}_user_message", message, is_bot=False)

        # ERSTE PRIORITÄT: Abschluss NUR nach letzter Intervention an Tag 15 (Woche 2)
        if user.phase == "Woche 2" and user.day == 15 and not user.completion_sent:
            # Wurde die letzte Intervention (18:02) an Tag 15 bereits verschickt?
            if user.last_intervention_sent_at:
                try:
                    sent_ts = datetime.datetime.fromisoformat(user.last_intervention_sent_at)
                except Exception:
                    sent_ts = None
                # Falls diese eingehende Nachricht NACH der letzten Intervention kommt
                if sent_ts is None or datetime.datetime.now() >= sent_ts:
                    if not user.last_intervention_replied:
                        user.last_intervention_replied = True
                        self.save_user_state(user_id)
                    self.finish_study(user_id)
                    return
            # Wenn die letzte Intervention noch nicht raus ist: KEIN Abschluss hier.

        # ── Zielsetzung (Tag 2, Woche 1) ───────────────────────────────────
        if week == 1 and user.day == 2:
            has_goal_question = False
            has_goal_exploration = False

            if user.pending_evening_questions:
                for q in user.pending_evening_questions:
                    if q.get('day') == 2:
                        if q.get('question_type') == 'goal_setting' and not q.get('answered', False):
                            has_goal_question = True
                        elif q.get('question_type') == 'goal_exploration' and not q.get('answered', False):
                            has_goal_exploration = True

            if has_goal_question:
                # Antwort auf die Zielsetzungsfrage weiterreichen
                self.handle_goal_response(phone_number, message, user_id)
                return

            if has_goal_exploration:
                # Antwort auf die Ziel-Vertiefungsfrage → empathisch abschließen
                closure_prompt = f"""Der User hat auf eine Vertiefungsfrage zu seinem Ziel geantwortet: "{message}"

    Erstelle eine empathische, abschließende Antwort (1-2 Sätze), die:
    - Validierend und verständnisvoll ist
    - Auf die konkrete Antwort eingeht
    - Das Gespräch natürlich beendet
    - Hoffnung macht, dass wir daran arbeiten werden
    - KEINE neuen Fragen stellt

    Beispiele:
    "Das kann ich gut verstehen. Wir schauen in den kommenden Tagen genauer hin, wie du liebevoller mit dir umgehen kannst."
    "Das klingt herausfordernd. Gemeinsam finden wir Wege, wie du dir in solchen Momenten helfen kannst."

    Stil: Warm, verständnisvoll, hoffnungsvoll"""
                try:
                    empathic_closure = self.generate_ai_response(closure_prompt, "conversation_closure", user_id)
                except Exception:
                    empathic_closure = (
                        "Das kann ich gut verstehen. Wir schauen in den kommenden Tagen genauer hin, "
                        "wie du liebevoller mit dir umgehen kannst."
                    )

                # Als beantwortet markieren
                if user.pending_evening_questions:
                    for q in user.pending_evening_questions:
                        if q.get('day') == 2 and q.get('question_type') == 'goal_exploration':
                            q['answered'] = True
                            q['answered_at'] = datetime.datetime.now().isoformat()
                            break

                self.send_signal_message(phone_number, empathic_closure)
                self.log_interaction(user_id, "goal_exploration_closure", empathic_closure, is_bot=True)
                self.save_user_state(user_id)
                return

        # ── ALLGEMEINE ANTWORTLOGIK (gilt für Woche 1 & 2, alle Tage) ───────────────
        response_count = self.get_response_count_for_week(user_id, week)
        end_detection = self.detect_conversation_ending(message, response_count)
        # SICHERER ZUGRIFF MIT .get()
        reason = end_detection.get("reason", "continue")

        if reason == "offer_optional_deepening":
            # KI-generierte Antwort mit optionaler Vertiefung
            # ERSTE Antwort = empathische Antwort + optionale Vertiefungseinladung
            response = self.generate_optional_deepening_response(message, user_id)
            response_type = f"week{week}_optional_deepening"

        elif end_detection["should_end"]:
            # Normale Beendigung
            response = self.generate_week_closure(week, end_detection["closure_type"], message)
            response_type = f"week{week}_conversation_closure"

        else:
            # Empathische Antwort – ggf. Scham-Level-adaptiert
            shame_level = self.assess_user_shame_level(user)
            adapted_context = f"SCHAM-LEVEL: {shame_level}\nNUTZER-NACHRICHT: {message}"
            response = self.generate_ai_response(adapted_context, "empathic_response", user_id)
            response_type = f"week{week}_ai_response"

        self.send_signal_message(phone_number, response)
        self.log_weekly_interaction(user_id, week, message, response, response_type)
        logger.info(f"Week{week} ending detection for {user_id}: {end_detection}")
        self.save_user_state(user_id)

    def detect_conversation_ending(self, message: str, response_count: int = 0) -> dict:
        """Vereinfachte Erkennung mit optionaler Vertiefung"""
        message_lower = message.lower().strip()
        message_length = len(message.strip())

        # Explizite End-Signale (immer respektieren)
        explicit_end_words = [
            'genervt', 'stop', 'aufhören', 'schluss', 'reicht',
            'später', 'müde',
        ]

        # Auch auf Satzebene prüfen
        explicit_end_phrases = [
            'reicht für heute', 'das wars', 'ich bin müde', 'nicht heute',
            'vielleicht später', 'erstmal genug', 'will aufhören'
        ]

        if (any(word in message_lower for word in explicit_end_words) or
                any(phrase in message_lower for phrase in explicit_end_phrases)):
            return {"should_end": True, "reason": "explicit_negative", "closure_type": "understanding"}

            # Sehr kurze, oberflächliche Antworten (oft ein Zeichen von Desinteresse)
        very_short_responses = ['ok', 'klar']
        if message_lower in very_short_responses:
            return {"should_end": True, "reason": "very_short_response", "closure_type": "natural"}

        # Einwortige Antworten nach dem ersten Austausch
        if response_count >= 1 and message_length <= 10 and len(message.split()) <= 2:
            return {"should_end": True, "reason": "minimal_engagement", "closure_type": "natural"}

        # Höfliche Dankbarkeit (früher erkannt)
        polite_end_patterns = [
            'danke', 'dankeschön', 'alles klar', 'passt', 'reicht erstmal',
            'gut so', 'das reicht', 'schön', 'ok danke'
        ]
        if any(pattern in message_lower for pattern in polite_end_patterns):
            return {"should_end": True, "reason": "polite_thanks", "closure_type": "appreciative"}

        # Wiederholungen erkennen (wenn User sich wiederholt ohne neue Info)
        repetitive_patterns = [
            'wie gesagt', 'hab ich schon gesagt', 'nochmal', 'bereits erzählt',
            'schon erwähnt', 'immer das gleiche'
        ]
        if any(pattern in message_lower for pattern in repetitive_patterns):
            return {"should_end": True, "reason": "repetitive", "closure_type": "understanding"}

        # Änderung: Optionale Vertiefung nur bei längeren, engagierten ersten Antworten
        if response_count == 1 and message_length > 20:
            prompt = f"""Der User hat ausführlich geantwortet: "{message}"

                Reagiere mit echtem Interesse:
                1. Spiegele das Wichtigste zurück
                2. Validiere die Emotion
                3. Stelle eine natürliche Vertiefungsfrage (KEIN "Falls du möchtest")

                Beispiel: "Das mit [Situation] klingt wirklich schwer. 
                Wie gehst du damit normalerweise um?" 
                """

        # Nach der zweiten Antwort: sehr vorsichtig mit weiteren Fragen
        if response_count >= 10:
            return {"should_end": True, "closure_type": "natural"}

        return {"should_end": False, "reason": "continue",}

    def generate_week_closure(self, week: int, closure_type: str, user_message: str = "") -> str:
        """Generiert natürliche Abschlussnachrichten mit KI"""

        time_context = "morgen" if week == 1 else "später"
        # Einfacher Kontext je nach Woche
        week_context = "erste Woche (Kennenlernen)" if week == 1 else "zweite Woche (Selbstmitgefühl)"

        # Einfacher Prompt basierend auf closure_type
        prompts = {
            "understanding": f"Beende empathisch ein therapeutisches Gespräch der {week_context}. Der User hat signalisiert, dass er aufhören möchte. .",
            "appreciative": f"Beende dankbar ein therapeutisches Gespräch der {week_context}. Der User war dankbar.",
            "brief": f"Beende kurz und freundlich ein therapeutisches Gespräch der {week_context}.",
            "natural": f"Beende natürlich ein therapeutisches Gespräch der {time_context}. Sage, dass es morgen weitergeht. ",
            "explicit_negative": f"Beende verständnisvoll ein therapeutisches Gespräch der {week_context}. Der User will definitiv aufhören."
        }

        prompt = prompts.get(closure_type, prompts["natural"])
        prompt += f"\n\nUser sagte: '{user_message}'\n\nAntworte in 1-2 Sätzen, warm aber nicht überschwänglich."

        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system",
                     "content": "Du beendest therapeutische Gespräche natürlich und empathisch auf Deutsch und in der informellen Du-Form. Sei authentisch, nicht kitschig."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,
                temperature=0.8
            )
            return response.choices[0].message.content.strip()
        except:
            # Fallback bei Fehlern
            fallbacks = {
                "understanding": "Ich verstehe. Danke für das Gespräch heute.",
                "appreciative": "Das freut mich. Bis morgen!",
                "brief": "Alles klar, dann bis morgen.",
                "natural": "Danke für deine Offenheit heute.",
                "explicit_negative": "Alles klar. Bis morgen."
            }
            return fallbacks.get(closure_type, "Bis morgen!")

    def get_recent_response_count(self, user_id: str, minutes: int = 30) -> int:
        """Zählt Bot-Antworten in den letzten X Minuten"""
        tagebuch_path = os.path.join(TAGEBUCH_DIR, f"{user_id}_tagebuch.jsonl")

        if not os.path.exists(tagebuch_path):
            return 0

        cutoff_time = datetime.datetime.now() - datetime.timedelta(minutes=minutes)
        response_count = 0

        try:
            with open(tagebuch_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        entry_time = datetime.datetime.fromisoformat(entry['timestamp'])

                        # Zähle nur Bot-Antworten in der Week 2 Phase
                        if (entry_time >= cutoff_time and
                                entry['sender'] == 'bot' and
                                'week2_ai_response' in entry.get('type', '')):
                            response_count += 1

                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        except Exception as e:
            logger.error(f"Error counting recent responses: {e}")
            return 0

        return response_count

    def get_response_count_for_week(self, user_id: str, week: int) -> int:
        """Einheitliche Response Count Logik für beide Wochen"""
        user = self.users[user_id]

        if week == 1:
            # Week 1: Prüfe pending_evening_questions für aktuellen Tag
            response_count = 0
            if user.pending_evening_questions:
                for q in user.pending_evening_questions:
                    if q['day'] == user.day and not q.get('answered', False):
                        q['response_count'] = q.get('response_count', 0) + 1
                        response_count = q['response_count']

                        # Bei erster Antwort als "answered" markieren
                        if q['response_count'] == 1:
                            q['answered'] = True
                            q['answered_at'] = datetime.datetime.now().isoformat()
                        break
            return response_count

        else:  # week == 2
            # Week 2: Verwende recent response count (30min Fenster)
            return self.get_recent_response_count(user_id, minutes=30)

    def log_weekly_interaction(self, user_id: str, week: int, user_message: str,
                               bot_response: str, response_type: str):
        """Einheitliches Logging für beide Wochen"""
        self.log_interaction(user_id, response_type, bot_response, is_bot=True)

    def handle_command(self, phone_number: str, message: str) -> bool:
        """Behandelt Spezial-Befehle"""
        user_id = self.hash_phone_number(phone_number)
        message_lower = message.lower().strip()

        if message_lower == "start":
            self.handle_start_command(phone_number)
            return True

        elif message_lower == "stop":
            if user_id in self.users:
                self.users[user_id].phase = "stopped"
                self.save_user_state(user_id)

            stop_message = "Die Studienteilnahme wurde beendet. Vielen Dank für deine bisherige Teilnahme!"
            self.send_signal_message(phone_number, stop_message)
            self.log_interaction(user_id, "stop_command", stop_message)
            return True

        elif message_lower == "hilfe":
            self.send_signal_message(phone_number, HELP_TEXT)
            self.log_interaction(user_id, "help_command", HELP_TEXT)
            return True

        elif message_lower == "status":
            if user_id in self.users:
                user = self.users[user_id]

                # Scheduled messages info
                scheduled_info = ""
                if user.next_scheduled_message:
                    scheduled_info = f"\nNächste geplante Aktion: {user.next_scheduled_message}"
                if user.scheduled_messages:
                    recent_scheduled = user.scheduled_messages[-3:]  # Letzte 3
                    scheduled_info += f"\nGeplante Aktionen: {', '.join(recent_scheduled)}"

                status_message = f"""
📊 Dein Studienfortschritt:

Phase: {user.phase} - {self.get_phase_description(user.phase)}
Tag: {user.day}
Startdatum: {user.start_date[:10] if user.start_date else 'Nicht gestartet'}

"""
            else:
                status_message = "Du hast noch nicht gestartet. Sende 'start' um zu beginnen."

            self.send_signal_message(phone_number, status_message)
            self.log_interaction(user_id, "status_command", status_message)
            return True

        return False

    def get_phase_description(self, phase: str) -> str:
        """Gibt Phasenbeschreibung zurück"""
        descriptions = {
            "waiting": "Warten auf Start",
            "onboarding": "Eingangsbefragung läuft",
            "Woche 1": "Kennenlernen",
            "transition": "Übergang zu Woche 2",
            "Woche 2": "Selbstmitgefühlsübungen",
            "finished": "Studie abgeschlossen",
            "stopped": "Studie gestoppt"
        }
        return descriptions.get(phase, "Unbekannte Phase")

    def process_message(self, phone_number: str, message: str):
        """Hauptverarbeitung eingehender Nachrichten"""
        user_id = self.hash_phone_number(phone_number)

        # Zeit-Limits prüfen (außer bei Basis-Befehlen)
        if not message.lower().strip() in ["start", "stop", "hilfe", "status"]:
            # Session-Ende prüfen VOR Zeit-Limits
            user = self.users.get(user_id)
            if user and getattr(user, 'session_ended', False):
                # Session wurde heute bereits beendet - keine Antwort
                return  # keine weitere Verarbeitung

            if self.check_and_handle_time_limits(user_id, phone_number):
                return  # Limit erreicht, Gespräch gestoppt

        # Crisis Detection (ersetzt die alte)
        crisis_handled = self.check_for_crisis(message, phone_number, user_id)
        if crisis_handled:
            return  # Crisis Detection hat die Nachricht bereits verarbeitet

        # Befehle prüfen
        if self.handle_command(phone_number, message):
            return

        # Nutzer laden oder erstellen
        if user_id not in self.users:
            help_message = "Bitte sende zuerst 'Start' um die Studie zu beginnen."
            self.send_signal_message(phone_number, help_message)
            return

        user = self.users[user_id]

        # Je nach Phase behandeln
        if user.phase == "onboarding":
            self.handle_onboarding(phone_number, message)
        elif user.phase in ["Woche 1", "Woche 2"]:
            self.handle_weekly_response(phone_number, message, user_id)
        elif user.phase in ["finished", "stopped"]:
            end_message = "Danke für deine Nachricht! Du hast die Studie bereits erfolgreich abgeschlossen. Es war eine besondere Zeit, dich zu begleiten und ich wünsche dir alles Gute. 💛 "
            self.send_signal_message(phone_number, end_message)


    def setup_scheduler(self):
        """Nur daily_check - keine anderen Jobs"""
        schedule.every(1).minutes.do(self.daily_check)  # Jede Minute prüfen
        logger.info("⏰Checking every minute")

    def calculate_study_day_from_calendar(self, start_date_str: str, current_time: datetime.datetime = None) -> int:
        """
        Berechnet Studientag basierend auf Kalendertagen (nicht 24h-Perioden)

        Tag 1: Start-Kalendertag (Onboarding)
        Tag 2: Zweiter Kalendertag (erste Abendsfrage)
        Tag 3-8: Woche 1 fortgesetzt
        Tag 9-15: Woche 2
        Tag 16+: Studie beendet

        Args:
            start_date_str: ISO format start date
            current_time: Optional current time (default: now)

        Returns:
            int: Study day number
        """
        if current_time is None:
            current_time = datetime.datetime.now()

        start_date = datetime.datetime.fromisoformat(start_date_str)

        # Kalendertage verwenden, nicht 24h-Perioden
        start_calendar_day = start_date.date()
        current_calendar_day = current_time.date()

        calendar_days_passed = (current_calendar_day - start_calendar_day).days
        study_day = calendar_days_passed + 1

        return study_day

    def daily_check(self):
        """Tägliche Aufgaben prüfen - FIXED SCHEDULE VERSION"""
        current_time = datetime.datetime.now()
        current_date_str = current_time.strftime('%Y-%m-%d')
        current_time_str = current_time.strftime('%H:%M')

        logger.info(f"🕰️ Daily check at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        # DEBUG: User-Anzahl loggen
        logger.info(f"👥 Checking {len(self.users)} users")

        # T3-Check EINMAL für alle User (vor der Hauptschleife)
        if current_time_str == "14:00":
            logger.info(f"⏰ 14:00 reached - checking T3 reminders for all users")
            for uid, u in self.users.items():
                self.check_t3_survey_reminder(uid, u, current_time)

        for user_id, user in self.users.items():
            logger.debug(f"🔍 Checking user {user_id}: phase={user.phase}, day={user.day}")

            if user.phase in ["stopped", "finished"] or not user.start_date:
                logger.debug(f"⏭️ Skipping user {user_id} (phase: {user.phase})")
                continue

            # Tage seit Start berechnen
            start_date = datetime.datetime.fromisoformat(user.start_date)
            study_day = self.calculate_study_day_from_calendar(user.start_date, current_time)

            # User day aktualisieren falls nötig
            if user.day != study_day:
                logger.info(f"User {user_id}: Day updated from {user.day} to {study_day}")
                user.day = study_day
                self.save_user_state(user_id)

            # WOCHE 1: Abendsfragen (Tag 2-8)
            if user.phase == "Woche 1" and 2 <= study_day <= 8:
                scheduled_time = EVENING_QUESTION_TIMES.get(study_day)
                if scheduled_time and current_time_str == scheduled_time:
                    if not self.was_sent_today(user_id, f"daily_question_day_{study_day}", current_date_str):
                        logger.info(f"🚀 SENDING evening question for {user_id}, day {study_day}")
                        phone_number = self.get_phone_from_user_id(user_id)
                        if phone_number:
                            self._send_evening_question_now(user_id, study_day, phone_number)

            # Woche 1 daily reminder
            if user.phase == "Woche 1" and 3 <= study_day <= 8:
                if current_time_str == "14:00":
                    yesterday = study_day - 1
                    has_unanswered = self.has_unanswered_question(user_id, yesterday)
                    already_sent = self.was_sent_today(user_id, f"reminder_day_{yesterday}", current_date_str)

                    logger.info(f"🔍 REMINDER DEBUG {user_id}: day={study_day}, yesterday={yesterday}")
                    logger.info(f"   📝 has_unanswered_question({yesterday}): {has_unanswered}")
                    logger.info(f"   ✉️ was_sent_today(reminder_day_{yesterday}): {already_sent}")

                    if has_unanswered and not already_sent:
                        logger.info(f"   🚀 SENDING reminder for day {yesterday}")
                        self._send_reminder_now(user_id, yesterday)
                    elif already_sent:
                        logger.info(f"   ⏭️ Reminder already sent today")
                    else:
                        logger.info(f"❌ No unanswered question for day {yesterday}")

            # ÜBERGANG ZU WOCHE 2 (Tag 8+)
            if user.phase == "Woche 1" and study_day >= 8:
                if not self.was_transition_sent(user_id):
                    if current_time_str >= "20:00":
                        logger.info(f"📤 Initiating week2 transition for {user_id}")
                        self.initiate_week2_transition(user_id)

            # WOCHE 2: Morgengrüße (Tag 9-15)
            if user.phase == "Woche 2" and 9 <= study_day <= 15:
                morning_time = MORNING_GREETING_TIMES.get(study_day)
                if morning_time and current_time_str == morning_time:
                    if not self.was_sent_today(user_id, f"morning_greeting_day_{study_day}", current_date_str):
                        logger.info(f"🚀 SENDING morning greeting for {user_id}, day {study_day}")
                        self._send_morning_greeting_now(user_id, study_day)

            # WOCHE 2: Abendinterventionen (Tag 9-15)
            if user.phase == "Woche 2" and 9 <= study_day <= 15:
                intervention_time = EVENING_INTERVENTION_TIMES.get(study_day)
                if intervention_time and current_time_str == intervention_time:
                    if not self.was_sent_today(user_id, f"intervention_day_{study_day}", current_date_str):
                        logger.info(f"🚀 SENDING intervention for {user_id}, day {study_day}")
                        self._send_evening_intervention_now(user_id, study_day)

            # STUDIE BEENDEN (Tag 15+)
            elif study_day >= 16 and user.phase != "finished":
                self.finish_study(user_id)

    def was_sent_today(self, user_id: str, message_type: str, date_str: str) -> bool:
        """Prüft ob eine bestimmte Nachricht heute schon gesendet wurde"""
        log_file = os.path.join(TAGEBUCH_DIR, f"{user_id}_tagebuch.jsonl")

        if not os.path.exists(log_file):
            return False

        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if (entry.get('type') == message_type and
                                entry.get('timestamp', '').startswith(date_str) and
                                entry.get('sender') == 'bot'):
                            return True
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass

        return False

    def was_transition_sent(self, user_id: str) -> bool:
        """Prüft ob Week2 Transition schon gesendet wurde"""
        return self.was_sent_today(user_id, "week2_transition", datetime.datetime.now().strftime('%Y-%m-%d'))

    def get_top_shame_areas(self, week1_responses: List[Dict]) -> tuple[int, int]:
        """Ermittelt die TOP-2 Bereiche mit den höchsten Scham-Ratings"""
        if not week1_responses or len(week1_responses) < 7:
            return (0, 1)  # Fallback

        # Ratings extrahieren (erste 7 Antworten sind die Eingangsfragen)
        ratings = []
        for resp in week1_responses[:7]:
            try:
                rating = int(resp.get('response', '1'))
                ratings.append(rating)
            except:
                ratings.append(1)  # Fallback bei Parsing-Fehler

        # Top-2 Indices bestimmen (bei Gleichstand gewinnt niedrigerer Index)
        indexed_ratings = [(i, rating) for i, rating in enumerate(ratings)]
        indexed_ratings.sort(key=lambda x: (-x[1], x[0]))  # Nach Rating desc, dann Index asc

        top1_idx = indexed_ratings[0][0]
        top2_idx = indexed_ratings[1][0]

        return (top1_idx, top2_idx)

    def generate_ai_exploration_question(self, user_id: str, day: int) -> str:
        """KI-Exploration mit Scham-Level-Anpassung"""

        user = self.users[user_id]
        shame_level = self.assess_user_shame_level(user)
        top1_idx, top2_idx = self.get_top_shame_areas(user.week1_responses)

        # Bereiche und Ratings
        area_names = [
            "Scham über die eigene Persönlichkeit und das Selbstbild",
            "Scham wegen des Aussehens oder körperlicher Merkmale",
            "Scham über vergangene Entscheidungen und Handlungen",
            "Scham wegen bestimmter persönlicher Eigenschaften",
            "Sozialer Rückzug aufgrund von Schamgefühlen",
            "Innere Selbstkritik und harte Selbstbewertung",
            "Schwierigkeiten im Umgang mit Schamgefühlen"
        ]
        focus_idx = top1_idx if day % 2 == 0 else top2_idx  # Wechselt jeden Tag
        focus_name = area_names[focus_idx]
        focus_rating = user.week1_responses[focus_idx]['response']

        # ANGEPASSTE PROMPTS je nach Scham-Level
        if shame_level == "niedrig":
            base_approach = """RESSOURCEN-ORIENTIERTER ANSATZ:
        - Fokus auf Stärken und positive Bewältigung
        - Weniger intensive Scham-Fokussierung
        - Mehr Richtung Selbstentwicklung und Wachstum
        - Frage eher: "Wie gehst du damit um?" statt "Wie sehr leidest du?"
        """
            tone = "neugierig und ermutigend"

        elif shame_level == "mittel":
            base_approach = """AUSGEWOGENER ANSATZ:
        - Balance zwischen Herausforderung und Unterstützung
        - Normale therapeutische Exploration
        - Sanft nach konkreten Situationen fragen
        """
            tone = "einfühlsam und unterstützend"

        else:  # hoch
            base_approach = """SEHR BEHUTSAMER ANSATZ:
        - Maximal validierend und vorsichtig
        - Nie drängend oder überfordernd
        - Fokus auf Sicherheit und Selbstmitgefühl
        - Kleinste Schritte würdigen
        """
            tone = "sehr sanft und validierend"

        # Ziel einbeziehen falls vorhanden
        goal_context = ""
        if hasattr(user, 'personal_goal') and user.personal_goal:
            goal_context = f"PERSÖNLICHES ZIEL: '{user.personal_goal}' - beziehe das Ziel mit ein falls passend."

        previous_questions = []
        if user.pending_evening_questions:
            recent = [q['question'] for q in user.pending_evening_questions[-2:]]
            previous_questions = recent

        prompt = f"""Du führst ein therapeutisches Gespräch über schwierige Gefühle

    NUTZER-PROFIL:
    - Stärkster Bereich: {focus_name} (Rating: {focus_rating}/10)
    - Tag: {day} der Exploration
    - Ziel: {goal_context}
    - Stil: {"Sanft" if shame_level == "hoch" else "Neugierig"}

    {base_approach}
    
    VERMEIDE DIESE FRAGEN:
    {chr(10).join(['- ' + q for q in previous_questions]) if previous_questions else 'Keine'}

    AUFGABE:
    Erstelle eine Frage (1-2 Sätze), die:
    - Zum Belastungs-Level passt
    - Den stärksten Bereich sanft exploriert  (W-Fragen: Was/Wann/Wo/Wie)
    - NICHT pathologisiert bei niedriger Belastung

    Beginne mit "Hi" oder ähnlich natürlich, sei menschlich.
    **Vermeide repetitive Phrasen von vorherigen Tagen!**"""

        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system",
                     "content": "Du bist ein menschlicher Therapeut der individuell angepasst arbeitet. Du sprichst auf Deutsch und in der informellen Du-Form."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150,
                temperature=1.2
            )

            generated = response.choices[0].message.content
            if generated is None:
                logger.warning(f"OpenAI returned None for exploration question day {day}")
                raise ValueError("None response from API")

            # ZUSÄTZLICHE PRÜFUNG AUF LEEREN STRING
            generated = generated.strip()
            if not generated:
                logger.warning(f"OpenAI returned empty string for day {day}")
                raise ValueError("Empty response from API")

            return generated

        except Exception as e:
            logger.error(f"Error generating shame-adapted question: {e}")

            # Fallback je nach Shame Level
            fallbacks = {
                "niedrig": f"Hi! Bei bei dem Thema '{focus_name}' hattest du {focus_rating} angegeben. Was hilft dir dabei, damit gut umzugehen?",
                "mittel": f"Hey! Erinnere dich an eine Situation in der du besonders viel Scham erlebt hast. Wie hat sich das in deinem Körper angefühlt?",
                "hoch": f" Hi! Das Thema '{focus_name}' scheint dich manchmal sehr zu belasten. Was hat dir rückblickend geholfen, wenn es dir deswegen schlecht ging?"
            }

            return fallbacks.get(shame_level, fallbacks["mittel"])

    def _send_evening_question_now(self, user_id: str, day: int, phone_number: str):
        """Sendet KI-gesteuerte Scham-Explorationsfrage - VEREINFACHT"""
        self.log_interaction(user_id, "scheduler_trigger", f"evening_question_day_{day}")
        try:
            user = self.users.get(user_id)
            if not user or not user.week1_responses:
                logger.error(f"User {user_id} not found or no responses!")
                return

            # SPEZIELLE BEHANDLUNG FÜR TAG 2: Zielsetzungsfrage
            if day == 2:
                goal_question = self.generate_day2_goal_question()
                success = self.send_signal_message(phone_number, goal_question)

                if success:
                    self.log_interaction(user_id, f"goal_setting_day_{day}", goal_question)

                    # Spezielle pending question für Zielsetzung
                    if user.pending_evening_questions is None:
                        user.pending_evening_questions = []

                    question_entry = {
                        'day': day,
                        'question': goal_question,
                        'question_type': 'goal_setting',  # WICHTIG: Markierung als Zielsetzung
                        'sent_at': datetime.datetime.now().isoformat(),
                        'answered': False,
                        'response_count': 0
                    }
                    user.pending_evening_questions.append(question_entry)
                    self.save_user_state(user_id)

                    logger.info(f"✅ Goal setting question (day {day}) sent to {user_id}")
                else:
                    logger.error(f"Failed to send goal setting question to {user_id}")
                return

        # NORMALE EXPLORATION für andere Tage (Tag 3-8)
            ai_success = True
            try:
                exploration_message = self.generate_ai_exploration_question(user_id, day)
            except Exception as e:
                logger.warning(f"AI generation failed for day {day}, using fallback: {e}")
                exploration_message = f"Hi! Wie ging es dir heute? Magst du mir erzählen, was dich beschäftigt hat?"
                ai_success = False  # Merke dass Fallback verwendet wurde

            success = self.send_signal_message(phone_number, exploration_message)

            if success:
                self.log_interaction(user_id, f"daily_question_day_{day}", exploration_message)

                # Pending question hinzufügen
                if user.pending_evening_questions is None:
                    user.pending_evening_questions = []

                question_entry = {
                    'day': day,
                    'question': exploration_message,
                    'question_type': 'exploration',  # Normale Exploration
                    'ai_generated': ai_success,
                    'sent_at': datetime.datetime.now().isoformat(),
                    'answered': False,
                    'response_count': 0  #Zählt Antworten
                }
                user.pending_evening_questions.append(question_entry)
                self.save_user_state(user_id)

                logger.info(f"✅ AI-generated exploration question day {day} sent to {user_id}")
            else:
                logger.error(f"Failed to send exploration question day {day} to {user_id}")

        except Exception as e:
            logger.error(f"Error in _send_evening_question_now: {e}")
            import traceback
            traceback.print_exc()

    def has_unanswered_question(self, user_id: str, day: int) -> bool:
        """Prüft ob für einen Tag eine unbeantwortete Frage existiert"""
        user = self.users.get(user_id)
        if not user or not user.pending_evening_questions:
            return False

        for q in user.pending_evening_questions:
            if q['day'] == day and not q.get('answered', False):
                return True
        return False

    def assess_response_quality(self, user_id: str, user_response: str) -> dict:
        """Bewertet ob die therapeutische Frage sinnvoll beantwortet wurde"""

        # Ursprüngliche Frage finden
        original_question = ""
        user = self.users[user_id]
        if user.pending_evening_questions:
            for q in user.pending_evening_questions:
                if q['day'] == user.day:
                    original_question = q['question']
                    break

        if not original_question:
            return {'quality': 5, 'should_close': False}

        try:
            prompt = f"""Bewerte diese Antwort auf eine therapeutische Schamfrage:

    FRAGE: {original_question}
ANTWORT: {user_response}

Bewerte 1-10 basierend auf ENGAGEMENT und BEREITSCHAFT:

HOCH (8-10): 
- Längere, durchdachte Antworten
- Nachfragen stellen
- Offen für weitere Exploration
- "Weiß nicht, aber..." mit Interesse

MITTEL (5-7):
- Ehrliches "Weiß ich nicht" 
- Kurz aber nicht abweisend
- Zeigt minimale Bereitschaft

NIEDRIG (1-4):
- Sehr kurz: "Ja", "Nein", "Ok"  
- Abweisend oder genervt
- Themenwechsel
- Signalisiert "will aufhören"

Erkenne: Will der User WEITERMACHEN oder AUFHÖREN?

Antworte: "Score: X"
    """

            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": "Du bewertest therapeutische Antworten objektiv."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=20,
                temperature=0.3
            )

            result = response.choices[0].message.content.strip()
            score = int(result.replace("Score:", "").strip())

            return {
                'quality': max(1, min(10, score)),
                'should_close': score >= 7  # Bei guter Qualität beenden
            }

        except Exception as e:
            logger.error(f"Error in response assessment: {e}")
            return {'quality': 5, 'should_close': False}  # Fallback

### Woche 2 Funktionen###

    def _send_morning_greeting_now(self, user_id: str, day: int):
        """Sendet Morgengruß sofort"""
        greeting = self.generate_ai_response("", "morning_greeting", user_id, temperature=1.0)
        # FALLBACK falls None
        if not greeting or greeting.strip() == "":
            greeting = "Guten Morgen! Ich wünsche dir einen achtsamen Tag. 🌱"

        phone_number = self.get_phone_from_user_id(user_id)
        if phone_number:
            success = self.send_signal_message(phone_number, f"🌅 {greeting}")
            if success:
                self.log_interaction(user_id, f"morning_greeting_day_{day}", greeting)
                logger.info(f"✅ Morning greeting sent to {user_id}")
            else:
                logger.error(f"Failed to send morning greeting to {user_id}")
        else:
            logger.error(f"No phone number found for {user_id}")

    def _send_reminder_now(self, user_id: str, day: int):
        """Sendet Reminder sofort (aus Timer aufgerufen)"""
        try:
            user = self.users.get(user_id)
            if user and user.pending_evening_questions:
                # Prüfe ob die Frage von diesem Tag noch unbeantwortet ist
                pending_today = None
                for q in user.pending_evening_questions:
                    if q['day'] == day and not q['answered']:
                        pending_today = q
                        break

                if pending_today:
                    reminder_text = f"""🔔 Kleine Erinnerung

Du hast gestern eine Reflexionsfrage erhalten, die noch auf deine Antwort wartet:
{pending_today['question']}

Falls du magst, kannst du gerne nachträglich antworten. Wenn nicht, ist das auch völlig in Ordnung! 💛"""

                    phone_number = self.get_phone_from_user_id(user_id)
                    if phone_number:
                        self.send_signal_message(phone_number, reminder_text)
                        self.log_interaction(user_id, f"reminder_day_{day}", reminder_text)
                        logger.info(f"✅ Reminder sent for day {day} to {user_id}")
                else:
                    logger.info(f"ℹ️ No pending question for day {day}, skipping reminder for {user_id}")
            else:
                logger.info(f"ℹ️ No user or pending questions, skipping reminder for {user_id}")

        except Exception as e:
            logger.error(f"💥 Error in _send_reminder_now: {e}")
            import traceback
            traceback.print_exc()

    def _send_evening_intervention_now(self, user_id: str, day: int):
        """Sendet personalisierte Abendintervention basierend auf Top-Schambereichen"""
        user = self.users.get(user_id)
        if not user:
            return

        # Top-2 Scham-Bereiche ermitteln
        top1_idx, top2_idx = self.get_top_shame_areas(user.week1_responses)
        focus_area = top1_idx if day % 2 == 0 else top2_idx

        # VEREINFACHTE ARRAYS
        areas = ["Selbstbild und Körperidentität", "Körperwahrnehmung", "Vergange Entscheidungen",
                 "Persönlichkeitseigenschaften", "Soziale Interaktion", "Selbstkritik", "Emotionsregulation"]

        area_contexts = [
            "du mit deinem Selbstbild ringst",
            "du deine Körperwahrnehmung als belastend erlebst",
            "du mit vergangenen Entscheidungen haderst",
            "du dich für bestimmte Seiten an dir schämst",
            "du dich in sozialen Situationen zurückziehst",
            "deine innere Bewertung sehr streng ist",
            "du mit schwierigen Emotionen kämpfst"
        ]

        methods = ["3-Komponenten-Übung", "Liebevoller Freund", "Körper-Beruhigung",
                   "Self-Compassion Letter", "Loving-Kindness for Self", "Compassionate Body Scan", "Common Humanity Reflection"]

        # WERTE BESTIMMEN
        area_name = areas[focus_area] if focus_area < len(areas) else areas[0]
        area_context = area_contexts[focus_area] if focus_area < len(area_contexts) else area_contexts[0]
        method_name = methods[day % len(methods)]
        personal_goal = getattr(user, 'personal_goal', '')
        user_rating = user.week1_responses[focus_area].get('response', '5') if focus_area < len(
            user.week1_responses) else '5'

        # SCHRITT 1: INTRO - NACHRICHT GENERIEREN
        intro_prompt = f"""Erstelle eine sanfte Abend-Begrüßung für jemanden, {area_context}.

        Stil: Menschlich, nicht kitschig, nicht zu pathologisierend
        Länge: 1-2 Sätze
        Zweck: zur Übung überleiten
"""

        # DIREKTER AUFRUF (nutzt den spezifischen Prompt!)
        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system",
                     "content": "Du bist ein einfühlsamer Therapeut. Antworte auf Deutsch, benutze die Du-Form. Sei menschlich."},
                    {"role": "user", "content": intro_prompt}
                ],
                max_tokens=100,
                temperature=1.0
            )
            intro_message = (
                response.choices[0].message.content.strip()
                if response.choices[0].message and response.choices[0].message.content
                else "Hey, lass uns mit deiner abendlichen Übung beginnen :)"
            )
        except Exception as e:
            logger.error(f"Intro generation error: {e}")
            intro_message = "Hey, willkommen zu deiner täglichen Mini-Übung. Erinnere dich an eine schwierige Situation mit dir selbst. Wir üben heute liebevollen Umgang damit."

        # SCHRITT 2: ÜBUNGS-NACHRICHT GENERIEREN
        goal_context = f"Persönliches Ziel: '{personal_goal}'" if personal_goal else "Allgemein: Mehr Selbstmitgefühl entwickeln"

        exercise_prompt = f"""Du bist Experte für Kristin Neffs Selbstmitgefühls-Übungen. Erstelle eine {method_name} Selbstmitgefühls-Übung passend zum Scham-Level des Users.

        Problem: {area_context} 
        User-Rating: {user_rating}/10
        Tag: {day} (variiere die Übungstypen über die Woche)
        Ziel: {goal_context}
        Übungs-Typ: {method_name}
        Länge: 3-5 Sätze konkrete Anweisungen
        Stil: Liebevoll, warm, praktisch, umsetzbar
        

        ANWEISUNG:
        Starte IMMER mit: "Erinnere dich an eine Situation, in der du {area_context}..."
        Wähle eine Übung, die zum Kontext passt. Gib konkrete, liebevolle Anweisungen in 3-5 Sätzen. 
        Variiere den Übungstyp - vermeide Wiederholungen der letzten Tage. 
        Stelle keine Fragen."""

        # DIREKTER AUFRUF (nutzt den spezifischen Prompt!)
        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system",
                     "content": "Du bist ein einfühlsamer therapeutischer Chatbot. Antworte auf Deutsch, benutze die Du-Form."},
                    {"role": "user", "content": exercise_prompt}
                ],
                max_tokens=150,
                temperature=1.0
            )
            intervention_message = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Exercise generation error: {e}")
            intervention_message = "Stell dir vor, ein liebevoller Freund sitzt neben dir und hört dir geduldig zu, wie du über deine Probleme sprichst. Er nimmt deine Schmerzen ernst und erinnert dich sanft daran, dass Fehler zum Menschsein gehören und dich nicht definieren. Er spricht dir Mut zu und lädt dich ein, dich selbst mit der gleichen Freundlichkeit zu begleiten, die du einem guten Freund schenken würdest. Atme tief ein und aus, während du diese liebevollen Worte innerlich annimmst und dir erlaubst, dich selbst ohne Urteil zu umarmen."

        # NACHRICHTEN SENDEN (ohne Split-Logik)
        phone_number = self.get_phone_from_user_id(user_id)
        if phone_number:
            # ERSTE NACHRICHT: Intro senden
            success1 = self.send_signal_message(phone_number, intro_message)
            # ✅ IMMER LOGGEN - unabhängig vom Erfolg
            log_status = "sent" if success1 else "failed"
            self.log_interaction(user_id, f"intervention_intro_day_{day}_{log_status}", intro_message)

            if success1:
                # Ziel-Referenz zählen falls vorhanden
                if personal_goal:
                    user.goal_reminder_count = getattr(user, 'goal_reminder_count', 0) + 1
                    self.save_user_state(user_id)

                # ZWEITE NACHRICHT: Intervention nach kurzer Pause senden
                def send_intervention():
                    try:
                        time.sleep(10)  # 10 Sekunden Pause für mentale Vorbereitung
                        success2 = self.send_signal_message(phone_number, intervention_message)

                        # ✅ IMMER LOGGEN
                        log_status = "sent" if success2 else "failed"
                        self.log_interaction(user_id, f"intervention_day_{day}_{log_status}", intervention_message)

                        if success2:
                            logger.info(f"✅ Split intervention sent to {user_id} (day {day}, focus: {area_name})")
                        else:
                            logger.error(f"Failed to send intervention part 2 to {user_id}")

                    except Exception as e:
                        logger.error(f"💥 Exception in send_intervention thread: {e}")
                        # ✅ Auch bei Exception loggen
                        self.log_interaction(user_id, f"intervention_day_{day}_error", f"Error: {str(e)}")

                def send_feedback():
                    try:
                        time.sleep(100)  # 2 Minuten warten nach dem Intro

                        # KI-generierte Feedback-Frage basierend auf verwendeter Methode
                        feedback_context = f"Die Intervention verwendete {method_name} für {area_name}."
                        feedback_message = self.generate_ai_response(feedback_context, "intervention_feedback_question")

                        success3 = self.send_signal_message(phone_number, feedback_message)
                        # ✅ IMMER LOGGEN
                        log_status = "sent" if success3 else "failed"
                        self.log_interaction(user_id, f"intervention_feedback_day_{day}_{log_status}", feedback_message)

                        if success3:
                            logger.info(f"✅ Feedback question sent to {user_id} after 2 minutes")

                            # ── NEU: Wenn es die letzte Intervention (Tag 15, Woche 2) ist → markieren
                            if user.phase == "Woche 2" and day == 15:
                                self.mark_day15_last_intervention_sent(user_id)
                        else:
                            logger.error(f"Failed to send feedback question to {user_id}")

                    except Exception as e:
                        logger.error(f"💥 Exception in send_feedback thread: {e}")
                        # ✅ Auch bei Exception loggen
                        self.log_interaction(user_id, f"intervention_feedback_day_{day}_error", f"Error: {str(e)}")

                # Beide Threads starten
                intervention_thread = threading.Thread(target=send_intervention, daemon=True)
                intervention_thread.start()

                feedback_thread = threading.Thread(target=send_feedback, daemon=True)
                feedback_thread.start()

            else:
                logger.error(f"Failed to send intervention intro to {user_id}")
        else:
            logger.error(f"No phone number found for {user_id}")

    def initiate_week2_transition(self, user_id: str):
        """Initiiert Übergang zu Woche 2"""
        user = self.users[user_id]
        user.phase = "transition"

        # 🔍 AUTOMATISCHE WOCHE 1 ANALYSE VOR DEM ÜBERGANG
        logger.info(f"🔄 Starting Week2 transition for {user_id}")

        # Prüfe ob Analyse bereits durchgeführt wurde
        if not getattr(user, 'week1_analysis_completed', False):
            logger.info(f"📊 Performing automatic Week1 analysis...")
            analysis_success = self.perform_automatic_week1_analysis(user_id)

            if analysis_success:
                logger.info(f"✅ Week1 analysis completed successfully")
            else:
                logger.warning(f"⚠️ Week1 analysis failed, continuing with transition")
        else:
            logger.info(f"📋 Week1 analysis already completed, skipping")

        # T2-Link senden
        transition_message = """
Eine Woche ist vorüber - Zeit für einen kleinen Rückblick! 😊
Du hast in den letzten Tagen so viel mit mir geteilt und mir tiefe Einblicke in deine Gedanken und Gefühle gewährt. Das zeigt großen Mut und ich bin dankbar für dein Vertrauen. 💙
Diese Offenheit ist der erste Schritt zu mehr Selbstmitgefühl - und genau darauf liegt unser Fokus in der kommenden Woche.

Bevor wir starten, würde ich dich bitten, kurz zu reflektieren, wie die erste Woche für dich war:
https://umfragenup.uni-potsdam.de/Schambot/?q=mid-assessment 

Ab morgen begleite ich dich dann mit sanften Übungen dabei, einen liebevolleren Umgang mit dir selbst zu entwickeln. 
Du hast es verdient, dir selbst mit der gleichen Güte zu begegnen, die du anderen schenkst. 🌱"""

        phone_number = self.get_phone_from_user_id(user_id)
        logger.info(f"📱 Phone number for {user_id}: {'found' if phone_number else 'NOT FOUND'}")

        if phone_number:
            success = self.send_signal_message(phone_number, transition_message)
            logger.info(f"📤 Transition message sent: {'✅' if success else '❌'}")

            if success:
                self.log_interaction(user_id, "week2_transition", transition_message)

                user.week2_transition_sent = datetime.datetime.now().isoformat()
                user.mid_assessment_link_sent = True

                user.phase = "Woche 2"  # Nur bei Erfolg
            else:
                logger.error(f"Failed to send transition message to {user_id}")
                return False

        else:
            logger.error(f"No phone number found for {user_id}")
            return False

        self.save_user_state(user_id)
        return True

    def mark_day15_last_intervention_sent(self, user_id: str):
        """Mark Day 15 last intervention as sent at 18:02 and set 21:00 auto-finish deadline."""
        user = self.users[user_id]
        now = datetime.datetime.now()
        user.last_intervention_sent_at = now.replace(hour=18, minute=2, second=0, microsecond=0).isoformat()
        user.last_intervention_day = 15
        user.last_intervention_replied = False
        deadline_dt = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if deadline_dt < now:  # falls später aufgerufen
            deadline_dt = now
        user.auto_finish_deadline = deadline_dt.isoformat()
        user.completion_sent = False
        self.save_user_state(user_id)

    def check_auto_finish_deadlines(self):
        """Auto-send completion at 21:00 on Day 15 if no reply after the last intervention."""
        now = datetime.datetime.now()
        for user_id, user in self.users.items():
            try:
                if (user.phase == "Woche 2"
                        and user.day == 15
                        and not user.completion_sent
                        and user.last_intervention_sent_at
                        and not user.last_intervention_replied
                        and user.auto_finish_deadline):
                    try:
                        deadline = datetime.datetime.fromisoformat(user.auto_finish_deadline)
                    except Exception:
                        deadline = now
                    if now >= deadline:
                        self.finish_study(user_id)
            except Exception:
                continue

    def finish_study(self, user_id: str):
        """Beendet die Studie"""
        user = self.users[user_id]
        if getattr(user, "completion_sent", False):
            return  # schon erledigt

        user.phase = "finished"
        user.completion_sent = True
        user.t3_survey_sent = datetime.datetime.now().isoformat()

        congratulations_message = """
Herzlichen Glückwunsch! Du hast die 2-wöchige Studie erfolgreich abgeschlossen.

Vielleicht magst du dir einen Moment Zeit nehmen, um zurückzuschauen:  
Wie hat es sich angefühlt, dir in den letzten Tagen mit mehr Freundlichkeit und Verständnis zu begegnen?  
Erinnere dich daran, dass diese Haltung jederzeit für dich verfügbar ist – gerade in schwierigen Momenten. 💙
"""
        survey_message = """
Zum Abschluss ist es für unsere Forschung sehr wichtig, dass du noch den letzten Fragebogen ausfüllst:  
https://umfragenup.uni-potsdam.de/Schambot/?q=post-assessment

Als Dankeschön erhälst du am Ende des Fragebogens eine Audiodatei zur Stärkung deines Selbstmitgefühls zum Download 😊

Deine Antworten helfen uns zu verstehen, wie wir solche Unterstützungsangebote weiterentwickeln können. 

Vielen Dank für deine Offenheit und dein Vertrauen. Alles Gute für deinen weiteren Weg! 🌱
"""

        phone_number = self.get_phone_from_user_id(user_id)
        if phone_number:
            # ERSTE NACHRICHT sofort senden
            success1 = self.send_signal_message(phone_number, congratulations_message)
            if success1:
                self.log_interaction(user_id, "study_completion_part1", congratulations_message)

                # ZWEITE NACHRICHT nach kurzer Pause senden
                def send_survey_request():
                    time.sleep(6)  # 6 Sekunden Pause für Reflexion
                    success2 = self.send_signal_message(phone_number, survey_message)
                    if success2:
                        self.log_interaction(user_id, "study_completion_part2", survey_message)
                        logger.info(f"✅ Split completion message sent to {user_id}")
                    else:
                        logger.error(f"Failed to send survey request to {user_id}")

                # Thread für zweite Nachricht starten
                survey_thread = threading.Thread(target=send_survey_request, daemon=True)
                survey_thread.start()
            else:
                logger.error(f"Failed to send congratulations message to {user_id}")

        self.save_user_state(user_id)

    def check_t3_survey_reminder(self, user_id: str, user: UserState, current_time: datetime.datetime):
        """Prüft ob T3 Survey Reminder gesendet werden soll"""

        # Nur für beendete Studien die T3 Link erhalten haben
        if user.phase != "finished" or not user.t3_survey_sent:
            return

        # Maximum 2 Reminders
        if user.t3_reminder_count >= 2:
            return

        try:
            survey_sent_time = datetime.datetime.fromisoformat(user.t3_survey_sent)
        except (ValueError, TypeError):
            logger.warning(f"Invalid t3_survey_sent timestamp for user {user_id}")
            return

        days_since_survey = (current_time - survey_sent_time).days

        # Ersten Reminder nach 3 Tagen
        if days_since_survey >= 3 and user.t3_reminder_count == 0:
            self.send_t3_reminder(user_id, "first")
            logger.info(f"📅 First T3 reminder due for {user_id} ({days_since_survey} days)")

        # Zweiten Reminder nach 7 Tagen
        elif days_since_survey >= 7 and user.t3_reminder_count == 1:
            self.send_t3_reminder(user_id, "final")
            logger.info(f"📅 Final T3 reminder due for {user_id} ({days_since_survey} days)")

    def send_t3_reminder(self, user_id: str, reminder_type: str):
        """Sendet T3 Survey Reminder"""
        user = self.users[user_id]
        phone_number = self.get_phone_from_user_id(user_id)

        if not phone_number:
            logger.error(f"No phone number found for T3 reminder: {user_id}")
            return False

        if reminder_type == "first":
            reminder_message = """📋 Kurze Erinnerung
            
Hallo! Vor ein paar Tagen hast du die 2-wöchige Studie zu Selbstmitgefühl bei Scham abgeschlossen. Ich hoffe, du konntest einige der Selbstmitgefühls-Impulse in deinen Alltag mitnehmen 😌

Falls du noch nicht dazu gekommen bist: Es wäre großartig, wenn du den abschließenden Fragebogen ausfüllen könntest. Deine Antworten sind sehr wertvoll für unsere Forschung.

https://umfragenup.uni-potsdam.de/Schambot/?q=post-assessment

Falls du ihn bereits ausgefüllt hast, kannst du diese Nachricht einfach ignorieren. 😊
Vielen Dank!"""

        else:  # final reminder
            reminder_message = """📝 Umfrage ausgefüllt?

Ich wollte noch mal kurz bei dir einchecken, ob du schon den letzten Fragebogen ausgefüllt hast. Am Ende wartet auch noch eine kleine Belohung auf dich 😊

https://umfragenup.uni-potsdam.de/Schambot/?q=post-assessment
    
Deine Teilnahme hilft uns sehr dabei, solche Unterstützungsangebote weiterzuentwickeln. Falls du bereits geantwortet hast, kannst du diese Nachricht ignorieren.
Vielen Dank und liebe Grüße vom Forschungsteam 🌱"""

        success = self.send_signal_message(phone_number, reminder_message)

        if success:
            user.t3_reminder_count += 1
            user.t3_last_reminder = datetime.datetime.now().isoformat()
            self.save_user_state(user_id)

            self.log_interaction(user_id, f"t3_reminder_{reminder_type}", reminder_message)
            logger.info(f"✅ T3 {reminder_type} reminder sent to {user_id}")
            return True
        else:
            logger.error(f"Failed to send T3 reminder to {user_id}")
            return False


    def process_message_batch(self, user_hash: str):
        """Verarbeitet eine Batch von Nachrichten zusammen"""
        try:
            if user_hash not in self.pending_messages:
                return

            batch = self.pending_messages[user_hash]
            # SICHERE EXTRAKTION MIT .get()
            phone_number = batch.get('phone')
            messages = batch.get('messages', [])

            if not phone_number or not messages:
                logger.warning(f"Invalid batch data for {user_hash}")
                return

            # Cleanup
            del self.pending_messages[user_hash]

            if not messages:
                return

            # Nachrichten kombinieren
            if len(messages) == 1:
                # Einzelne Nachricht normal verarbeiten
                self.process_message(phone_number, messages[0]['text'])
            else:
                # Mehrere Nachrichten kombinieren
                combined_text = "\n".join([msg['text'] for msg in messages])
                logger.info(f"📦 Processing batch of {len(messages)} messages as one")
                self.process_message(phone_number, combined_text)

        except Exception as e:
            logger.error(f"Error in batch processing: {e}")

    def handle_signal_message(self, message_data: dict):
        """Verarbeitet eine einzelne Signal-Nachricht"""
        try:
            # logger.debug(f"Raw message data: {message_data}") auskommentiert zum Datenschutz

            # Signal API Format: envelope.source und envelope.dataMessage.message
            envelope = message_data.get('envelope', {})
            data_message = envelope.get('dataMessage', {})

            # Sender aus envelope
            sender = envelope.get('source') or envelope.get('sourceNumber')
            #logger.info(f"sender at the start: {sender}") # source = von signal --> unproblematisch ?!

            # Text aus dataMessage
            text = (data_message.get('message') or '').strip()

            user_hash = self.hash_phone_number(sender)
            logger.debug(f"Parsed - sender: {user_hash}, text: {text}")


            if sender and text:
                user_hash = self.hash_phone_number(sender)
                logger.info(f"✅ Received message from user {user_hash}: {text[:50]}")

                # Sofortverarbeitung für wichtige Befehle
                if text.lower().strip() in ["start", "stop", "hilfe", "status"]:
                    self.process_message(sender, text)
                    return

                # Message Batching: Nachricht sammeln
                if user_hash not in self.pending_messages:
                    self.pending_messages[user_hash] = {
                        'phone': sender,
                        'messages': [],
                        'timer': None
                    }

                # Nachricht zur Batch hinzufügen
                self.pending_messages[user_hash]['messages'].append({
                    'text': text,
                    'timestamp': datetime.datetime.now().isoformat()
                })

                # Bestehenden Timer abbrechen falls vorhanden
                if self.pending_messages[user_hash]['timer']:
                    self.pending_messages[user_hash]['timer'].cancel()

                # Neuen Timer starten (10 Sekunden)
                def process_batch():
                    self.process_message_batch(user_hash)

                self.pending_messages[user_hash]['timer'] = threading.Timer(10.0, process_batch)
                self.pending_messages[user_hash]['timer'].start()

                logger.info(
                    f"⏱️ Message batched, will process in 10s ({len(self.pending_messages[user_hash]['messages'])} messages)")

        except Exception as e:
            logger.error(f"💥 Error handling message: {e}")
            import traceback
            traceback.print_exc()

    def run(self):
        """Startet den Bot"""
        logger.info("Starting Scham Research Bot...")

        # Scheduler in separatem Thread starten
        def run_scheduler():
            while True:
                pending_count = len([job for job in schedule.jobs if job.should_run])
                if pending_count > 0:
                    logger.info(f"⚡ Running {pending_count} pending jobs")

                schedule.run_pending()
                time.sleep(1)

        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()

        # Deadline-Watcher in separatem Thread starten
        def run_deadline_watcher():
            while True:
                try:
                    self.check_auto_finish_deadlines()
                except Exception as e:
                    logger.exception(f"Fehler im Deadline-Watcher: {e}")
                time.sleep(60)  # minütlich

        threading.Thread(target=run_deadline_watcher, daemon=True).start()

        # Hauptschleife für Nachrichten
        try:
            self.listen_for_messages()
        except KeyboardInterrupt:
            logger.info("Bot gestoppt.")

##### ==== WOCHE 1 ANALYSE ==== #####

    def extract_user_messages_from_tagebuch(self, user_id: str) -> list:
        """Extrahiert alle User-Nachrichten aus der Tagebuch-Datei"""
        tagebuch_path = os.path.join(TAGEBUCH_DIR, f"{user_id}_tagebuch.jsonl")

        if not os.path.exists(tagebuch_path):
            return []

        user_messages = []
        try:
            with open(tagebuch_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())

                        if (entry.get('sender') == 'user' and
                                entry.get('content', '').lower().strip() not in ["start", "stop", "hilfe", "status"] and
                                len(entry.get('content', '').strip()) > 3):
                            user_messages.append({
                                'content': entry['content'],
                                'timestamp': entry['timestamp'],
                                'type': entry.get('type', 'unknown')
                            })

                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            logger.error(f"Error reading tagebuch for user {user_id}: {e}")
            return []

        return user_messages

    def get_initial_shame_context(self, user: UserState) -> dict:
        """Extrahiert relevanten Kontext aus Eingangsbefragung"""
        if not user.week1_responses or len(user.week1_responses) < 7:
            return {'top_areas': [], 'ratings': []}

        top1_idx, top2_idx = self.get_top_shame_areas(user.week1_responses)

        area_names = [
            "Scham über eigene Persönlichkeit",
            "Scham wegen Aussehen/Körper",
            "Scham über vergangene Handlungen",
            "Scham wegen persönlicher Eigenschaften",
            "Sozialer Rückzug durch Scham",
            "Selbstkritik und harte Selbstbewertung",
            "Schwierigkeiten im Scham-Umgang"
        ]

        return {
            'top_areas': [area_names[top1_idx], area_names[top2_idx]],
            'top_ratings': [user.week1_responses[top1_idx]['response'],
                            user.week1_responses[top2_idx]['response']],
            'all_ratings': [resp.get('response', '0') for resp in user.week1_responses[:7]]
        }

    def ai_therapeutic_shame_evaluation(self, user_id: str, user_messages: list, initial_context: dict) -> dict:
        """KI führt therapeutische Gesamteinschätzung durch"""

        all_conversations = "\n---\n".join([
            f"[{msg['timestamp'][:10]}] {msg['content']}"
            for msg in user_messages
        ])

        prompt = f"""
        Du bist ein erfahrener klinischer Psychologe mit Expertise in Schamforschung.

        Eine Person hat an einer Scham-Studie teilgenommen. Du sollst ihre Scham-Belastung einschätzen, 
        wie du es nach therapeutischen Gesprächen tun würdest.

        EINGANGSBEFRAGUNG (1-10 Skala):
        - Stärkste Bereiche: {initial_context.get('top_areas', [])} 
        - Ratings: {initial_context.get('top_ratings', [])}
        - Alle Bereiche: {initial_context.get('all_ratings', [])}

        GESPRÄCHSVERLAUF ({len(user_messages)} Nachrichten):
        {all_conversations}

        THERAPEUTISCHE AUFGABE:
        Schätze das Gesamt-Scham-Niveau dieser Person ein, wie du es als Therapeut 
        nach diesen Gesprächen tun würdest.

        Gib deine Einschätzung auf der ESS-Skala von 25-100 an:
        - 25-40: Geringe Scham-Belastung
        - 41-60: Moderate Scham-Belastung  
        - 61-80: Erhöhte Scham-Belastung
        - 81-100: Hohe bis sehr hohe Scham-Belastung

        Antworte im folgenden Format:
        THERAPEUTISCHE_EINSCHÄTZUNG: [Zahl zwischen 25-100]
        CONFIDENCE: [Zahl zwischen 1-10]
        ASSESSMENT_QUALITY: [excellent/good/moderate/poor]
        BEGRÜNDUNG: [2-3 Sätze]
        """

        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {
                        "role": "system",
                        "content": "Du bist ein erfahrener klinischer Psychologe mit 15 Jahren Erfahrung in Schamforschung und -therapie."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=400,
                temperature=0.2
            )

            response_text = response.choices[0].message.content.strip()

            return {
                'therapeutic_shame_score': self.extract_therapeutic_score(response_text),
                'confidence': self.extract_confidence(response_text),
                'assessment_quality': self.extract_assessment_quality(response_text),
                'reasoning': self.extract_reasoning(response_text),
                'raw_response': response_text
            }

        except Exception as e:
            logger.error(f"Error in AI evaluation for {user_id}: {e}")
            return self.fallback_therapeutic_assessment(initial_context, len(user_messages))

    def extract_therapeutic_score(self, response_text: str) -> float:
        """Extrahiert therapeutische Einschätzung"""
        import re
        match = re.search(r'THERAPEUTISCHE_EINSCHÄTZUNG:\s*(\d+(?:\.\d+)?)', response_text, re.IGNORECASE)
        if match:
            score = float(match.group(1))
            return max(25, min(100, score))

        numbers = re.findall(r'\b(\d{2,3})\b', response_text)
        for num in numbers:
            score = int(num)
            if 25 <= score <= 100:
                return float(score)

        return 50.0

    def extract_confidence(self, response_text: str) -> int:
        """Extrahiert Confidence-Score"""
        import re
        match = re.search(r'CONFIDENCE:\s*(\d+)', response_text, re.IGNORECASE)
        if match:
            return max(1, min(10, int(match.group(1))))
        return 5

    def extract_assessment_quality(self, response_text: str) -> str:
        """Extrahiert Assessment-Quality"""
        import re
        match = re.search(r'ASSESSMENT_QUALITY:\s*(\w+)', response_text, re.IGNORECASE)
        if match:
            quality = match.group(1).lower()
            if quality in ['excellent', 'good', 'moderate', 'poor']:
                return quality
        return 'moderate'

    def extract_reasoning(self, response_text: str) -> str:
        """Extrahiert Begründung"""
        import re
        match = re.search(r'BEGRÜNDUNG:\s*(.+?)(?=\n[A-Z_]+:|$)', response_text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return "Begründung nicht verfügbar"

    def fallback_therapeutic_assessment(self, initial_context: dict, message_count: int) -> dict:
        """Fallback bei KI-Fehlern"""
        all_ratings = initial_context.get('all_ratings', [])
        if all_ratings:
            numeric_ratings = [float(r) for r in all_ratings if r.isdigit()]
            if numeric_ratings:
                avg_rating = sum(numeric_ratings) / len(numeric_ratings)
                ess_score = 25 + (avg_rating - 1) * (75 / 9)

                return {
                    'therapeutic_shame_score': round(ess_score, 1),
                    'confidence': 3,
                    'assessment_quality': 'poor',
                    'reasoning': f'Fallback basierend auf Eingangsbefragung (Ø{avg_rating:.1f})'
                }

        return {
            'therapeutic_shame_score': 50.0,
            'confidence': 1,
            'assessment_quality': 'insufficient_data',
            'reasoning': 'Keine ausreichenden Daten verfügbar'
        }

    def perform_automatic_week1_analysis(self, user_id: str):
        """Führt automatische Woche 1 Analyse durch wenn User zu Woche 2 wechselt"""
        try:
            user = self.users.get(user_id)
            if not user or len(user.week1_responses) < 7:
                logger.warning(f"Cannot perform Week1 analysis for {user_id}: insufficient data")
                return False

            logger.info(f"🔍 Performing automatic Week1 analysis for {user_id}")

            # User-Nachrichten extrahieren
            user_messages = self.extract_user_messages_from_tagebuch(user_id)
            if len(user_messages) < 2:
                logger.warning(f"Not enough messages for analysis: {len(user_messages)}")
                return False

            # Kontext aus Eingangsbefragung
            initial_context = self.get_initial_shame_context(user)

            # KI-Analyse durchführen
            assessment = self.ai_therapeutic_shame_evaluation(user_id, user_messages, initial_context)

            # Ergebnis speichern
            analysis_result = {
                'user_id': user_id,
                'personal_code': user.personal_code,
                'analysis_timestamp': datetime.datetime.now().isoformat(),
                'therapeutic_shame_score': assessment['therapeutic_shame_score'],
                'ai_confidence': assessment['confidence'],
                'assessment_quality': assessment['assessment_quality'],
                'message_count': len(user_messages),
                'initial_sum_score': sum(int(r) for r in initial_context.get('all_ratings', []) if r.isdigit()),
                'initial_ratings': initial_context.get('all_ratings', []),
                'reasoning': assessment['reasoning'],
                'phase_at_analysis': user.phase
            }

            # In separate Analyse-Datei speichern
            analysis_file = os.path.join(TAGEBUCH_DIR, "week1_analyses.jsonl")
            with open(analysis_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(analysis_result, ensure_ascii=False) + '\n')

            # Auch in User-State speichern
            user.week1_analysis_completed = True
            user.week1_analysis_score = assessment['therapeutic_shame_score']
            user.week1_analysis_timestamp = datetime.datetime.now().isoformat()
            self.save_user_state(user_id)

            logger.info(f"✅ Week1 analysis completed for {user_id}: Score {assessment['therapeutic_shame_score']:.1f}")
            return True

        except Exception as e:
            logger.error(f"Error in automatic Week1 analysis for {user_id}: {e}")
            return False

    def get_week1_analysis_summary(self):
        """Zeigt Zusammenfassung aller Week1 Analysen"""
        analysis_file = os.path.join(TAGEBUCH_DIR, "week1_analyses.jsonl")

        if not os.path.exists(analysis_file):
            return "Noch keine automatischen Analysen durchgeführt."

        analyses = []
        with open(analysis_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    analyses.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue

        if not analyses:
            return "Keine gültigen Analyseergebnisse gefunden."

        scores = [a['therapeutic_shame_score'] for a in analyses]
        qualities = [a['assessment_quality'] for a in analyses]

        summary = f"📊 WEEK1 ANALYSIS SUMMARY: {len(analyses)} Analysen\n"
        summary += f"Therapeutic Scores: μ={sum(scores) / len(scores):.1f}, Range: {min(scores):.1f}-{max(scores):.1f}\n"

        from collections import Counter
        quality_dist = Counter(qualities)
        summary += f"Quality Distribution: {dict(quality_dist)}\n"

        return summary

#######################################