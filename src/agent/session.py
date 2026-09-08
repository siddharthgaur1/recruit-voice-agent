from src.agent.slots import SLOT_ORDER
from src.agent.state import CallState
from src.config import settings


def new_call_state(lead_id: str, call_attempt_id: str) -> CallState:
    return {
        "lead_id": lead_id,
        "call_attempt_id": call_attempt_id,
        "company": settings.company_name,
        "transcript": [],
        "slots": dict.fromkeys(SLOT_ORDER),
        "current_slot": SLOT_ORDER[0],
        "retry_count": 0,
        "turn_count": 0,
        "outcome": None,
        "disclosed": False,
        "domain_raw": None,
    }
