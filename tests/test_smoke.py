# -*- coding: utf-8 -*-
"""
Einfacher Smoke Test für Schambot
"""

import sys
import os

# Füge src zum Path hinzu
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_imports():
    """Teste ob alle Module importierbar sind"""
    try:
        import settings
        from storage import UserState
        from gpt_client import client
        from bot import SchamChatBot
        print("✅ Alle Imports erfolgreich")
        return True
    except ImportError as e:
        print(f"❌ Import-Fehler: {e}")
        return False

def test_user_state_creation():
    """Teste UserState Erstellung"""
    try:
        from storage import UserState
        user = UserState(user_id="test123")
        assert user.user_id == "test123"
        assert user.phase == "waiting"
        print("✅ UserState Erstellung erfolgreich")
        return True
    except Exception as e:
        print(f"❌ UserState Test fehlgeschlagen: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Running Smoke Tests...")
    print("-" * 50)
    
    tests = [
        test_imports,
        test_user_state_creation,
    ]
    
    results = [test() for test in tests]
    
    print("-" * 50)
    if all(results):
        print("✅ Alle Tests bestanden!")
        sys.exit(0)
    else:
        print("❌ Einige Tests fehlgeschlagen!")
        sys.exit(1)
