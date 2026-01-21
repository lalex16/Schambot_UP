# -*- coding: utf-8 -*-
"""
Datenspeicher und Persistenz für User States
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

### Datenspeicher
@dataclass
class UserState:
    user_id: str
    personal_code: str = ""
    phase: str = "waiting"  # waiting, onboarding, Woche 1, transition, week2, finished, stopped
    day: int = 0
    start_date: Optional[str] = None
    onboarding_step: int = 0
    week1_responses: List[Dict] = field(default_factory=list)
    crisis_detected: bool = False
    last_message_time: Optional[str] = None
    next_scheduled_message: Optional[str] = None
    scheduled_messages: List[str] = field(default_factory=list)
    pending_evening_questions: List[Dict] = field(default_factory=list)
    session_start: Optional[str] = None
    daily_usage_minutes: float = 0.0
    last_usage_date: Optional[str] = None
    session_warned: bool = False
    active_session_minutes: float = 0.0  # Nur aktive Gesprächszeit
    week1_conversation_closed: Dict[str, bool] = field(default_factory=dict)
    daily_reply_count: Dict[str, int] = field(default_factory=dict)
    daily_closure_sent: Dict[str, bool] = field(default_factory=dict)
    personal_goal: str = ""
    goal_set_date: Optional[str] = None
    goal_reminder_count: int = 0
    last_intervention_sent_at: Optional[str] = None
    last_intervention_day: Optional[int] = None
    last_intervention_replied: bool = False
    auto_finish_deadline: Optional[str] = None
    completion_sent: bool = False
    crisis_exploration: Dict = field(default_factory=lambda: {'active': False})
    crisis_final_score: Optional[float] = None
    session_ended: bool = False
    week1_analysis_completed: bool = False
    week1_analysis_score: Optional[float] = None
    week1_analysis_timestamp: Optional[str] = None
    week2_transition_sent: Optional[str] = None
    mid_assessment_link_sent: bool = False
    t3_survey_sent: Optional[str] = None  # Wann T3 Link gesendet wurde
    t3_reminder_count: int = 0  # Anzahl gesendeter Reminders
    t3_last_reminder: Optional[str] = None # Wann letzter Reminder gesendet wurde

    def __post_init__(self):
        if self.week1_responses is None:
            self.week1_responses = []
        if self.scheduled_messages is None:
            self.scheduled_messages = []
        if self.pending_evening_questions is None:
            self.pending_evening_questions = []
        if not hasattr(self, 't3_survey_sent'):
            self.t3_survey_sent = None
        if not hasattr(self, 't3_reminder_count'):
            self.t3_reminder_count = 0
