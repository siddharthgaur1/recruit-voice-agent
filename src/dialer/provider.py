"""Telephony provider interface. Real providers (Phase 5) implement this
same ABC so the dialer/scheduler code needs zero changes to swap in."""

from abc import ABC, abstractmethod
from enum import Enum


class CallOutcome(Enum):
    HUMAN_ANSWERED = "HUMAN_ANSWERED"
    VOICEMAIL = "VOICEMAIL"
    BUSY = "BUSY"
    NO_ANSWER = "NO_ANSWER"
    SWITCHED_OFF = "SWITCHED_OFF"
    INVALID_NUMBER = "INVALID_NUMBER"
    DNC = "DNC"
    FAILED = "FAILED"


RETRYABLE_OUTCOMES = {CallOutcome.BUSY, CallOutcome.NO_ANSWER, CallOutcome.SWITCHED_OFF}


class TelephonyProvider(ABC):
    @abstractmethod
    def place_call(self, phone: str) -> CallOutcome:
        """Place an outbound call and return how it ended."""
