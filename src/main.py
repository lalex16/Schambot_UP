#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scham-Forschungs-Chatbot für Masterarbeit Psychologie
Haupteinstiegspunkt der Anwendung
"""

import logging
from bot import SchamChatBot
from settings import setup_logging

logger = logging.getLogger(__name__)

def main():
    """Hauptfunktion zum Starten des Chatbots"""
    # Logging initialisieren
    setup_logging()
    
    # Bot erstellen und starten
    bot = SchamChatBot()
    
    try:
        # Sofortprüfung der Auto-Finish Deadlines
        bot.check_auto_finish_deadlines()
    except Exception as e:
        logger.warning(f"Sofortprüfung der Deadlines: {e}")
    
    #bot.reset_test_user_only()
    
    # Informationen ausgeben
    print(" Scham-Chatbot gestartet!")
    print(" Senden 'Start' vom Handy, um zu beginnen")
    print(" Logs: ../schambot/chatbot.log")
    print(" Stoppen mit Ctrl+C")
    print("-" * 50)
    
    # Bot laufen lassen
    bot.run()

if __name__ == "__main__":
    main()


# auf Error prüfen: grep -i error chatbot.log
# Woche 1 download:  scp alex1@141.89.241.136:~/schambot/scham_analysis/scham_ess_korrelation.csv ~/Desktop/Schambot/scham_analyse_$(date +%Y%m%d).csv
