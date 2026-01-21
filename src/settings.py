# -*- coding: utf-8 -*-
"""
Konfiguration und Konstanten für den Schambot
"""

import os
import logging
from dotenv import load_dotenv

### Environment Setup
load_dotenv()
SIGNAL_NUMBER = os.getenv("SIGNAL_NUMBER")
SIGNAL_API_URL = "http://localhost:8080/v1"

AZUREAI_API_KEY = os.getenv("AZUREAI_API_KEY")
endpoint = "https://klinpsychbot2.openai.azure.com/"
model_name = "gpt-4.1-mini"
deployment = "gpt-4.1-mini"
api_version = "2024-12-01-preview"

### Directories
STATE_DIR = "../schambot/user_state"
TAGEBUCH_DIR = "../schambot/tagebuch"

def ensure_directories():
    """Erstellt notwendige Verzeichnisse"""
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(TAGEBUCH_DIR, exist_ok=True)

TEST_MODE = False  # True = Testmodus (kurze Zeiten), False = Produktivmodus (echte Zeiten)

### Zeiten
SESSION_LIMIT_MINUTES = 45
DAILY_LIMIT_MINUTES = 90

# FESTE ZEITEN für Nachrichten
EVENING_QUESTION_TIMES = {
    2: "18:22",
    3: "17:46",
    4: "19:25",
    5: "18:53",
    6: "19:34",
    7: "20:18",
    8: "17:31"  # Letzter Tag Woche 1
}
MORNING_GREETING_TIMES = {
    9: "08:13",
    10: "09:51",
    11: "09:12",
    12: "08:38",
    13: "09:07",
    14: "08:28",
    15: "09:05"  # Letzter Tag Woche 2
}
EVENING_INTERVENTION_TIMES = {
    9: "19:21",
    10: "17:22",
    11: "19:15",
    12: "20:06",
    13: "18:32",
    14: "20:35",
    15: "17:02"  # Letzter Tag Woche 2
}

### Krisenschlagwörter
CRISIS_KEYWORDS = [
    'suizid', 'suizidal', 'selbstmord', 'mich umbringen', 'tod', 'sterben',
    'nicht mehr leben', 'ende machen', 'aufgeben', 'hoffnungslos',
    'verzweifelt', 'kann nicht mehr', 'alles sinnlos'
]
HELP_TEXT = """
🆘 Hilfe in Krisen 

Sofortige Hilfe:
📞 Telefonseelsorge: 0800 111 0 111 oder 0800 111 0 222 (kostenlos, 24h)
💬 Online-Chat: www.telefonseelsorge.de

Weitere Hilfsangebote:
🏥 Notfall: 112
👨‍⚕️ Ärztlicher Bereitschaftsdienst: 116 117
🧠 Nummer gegen Kummer: 0800 111 0 550

Online-Hilfe:
🌐 www.deutsche-depressionshilfe.de
🌐 www.u25-deutschland.de (für unter 25-Jährige)

Du bist nicht allein! Professionelle Hilfe ist verfügbar.

❓ Du hast eine Frage zur Studie oder ein anderweitiges Problem? Dann wende dich bitte per Mail an die Studienleitung: jakob.fink-lamotte@uni-potsdam.de
"""

### Logging Setup
def setup_logging():
    """Konfiguriert das Logging-System"""
    logging.basicConfig(
        level=logging.DEBUG,  # hier auf level=logging.DEBUG umschaltefür Debugging
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('../schambot/chatbot.log'),
            logging.StreamHandler()
        ]
    )
