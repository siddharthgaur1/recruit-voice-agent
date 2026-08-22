"""Plivo telephony provider -- STUB ONLY. No credentials, no network calls.

Do not wire this up or place a real call until docs/COMPLIANCE.md's open
questions are resolved (DLT registration, DND scrubbing, calling-hours,
consent, recording).

What a real implementation needs:

  Credentials (from https://console.plivo.com/dashboard/):
    - auth_id     -- account identifier
    - auth_token  -- secret token, HTTP Basic Auth alongside auth_id
    - from_number -- a Plivo number provisioned for India outbound calling
                     (must be DLT-registered for the relevant template
                     category, same constraint as Exotel's exophone)

  Placing a call:
    POST https://api.plivo.com/v1/Account/{auth_id}/Call/
    form/json params:
      from        -- from_number above
      to          -- candidate's number, country code prefixed, no "+"
                     (bulk/multi-recipient calls use "<" as a delimiter,
                     not needed here since we dial one lead at a time)
      answer_url  -- webhook Plivo requests once the call is answered;
                     must return Plivo XML (or point at a Plivo "Answer
                     Application") describing what happens next -- for a
                     real-time bridge this is where Plivo's Audio Streaming
                     (<Stream> XML element, bidirectional WebSocket) would
                     be pointed at this app so CallSession
                     (src/api/session.py) can run the same STT -> graph ->
                     TTS loop used for the browser mic simulator, over real
                     telephony audio instead of a browser mic.
      hangup_url  -- webhook Plivo calls when the call ends, carrying final
                     status -- this is what would actually resolve the
                     CallOutcome asynchronously (unlike MockProvider, a real
                     provider call is not synchronous; DialerEngine would
                     need a callback/webhook path, not just a return value).

  Response: JSON with `request_uuid`, `message`, `api_id`. The call's
  eventual disposition arrives later via hangup_url, not in this response.

  Mapping Plivo hangup_url `HangupCauseName`/`CallStatus` onto our
  CallOutcome:
    ANSWER                                  -> HUMAN_ANSWERED
    NO_ANSWER                               -> NO_ANSWER
    BUSY                                    -> BUSY
    CANCEL / FAILED / INVALID_NUMBER_FORMAT -> FAILED or INVALID_NUMBER
    (Plivo also doesn't distinguish "switched off" from no-answer/failed at
    the API level -- would need the underlying SIP cause code.)
"""

from src.dialer.provider import CallOutcome, TelephonyProvider


class PlivoProvider(TelephonyProvider):
    def __init__(self, auth_id: str, auth_token: str, from_number: str):
        self.auth_id = auth_id
        self.auth_token = auth_token
        self.from_number = from_number

    def place_call(self, phone: str) -> CallOutcome:
        raise NotImplementedError(
            "PlivoProvider is a stub. Wiring this up means: DLT-registering "
            "from_number, passing TRAI TCCCPR calling-hours + DND/NCPR "
            "checks, switching DialerEngine to an async/webhook-driven "
            "outcome model (answer_url/hangup_url, not a synchronous "
            "return value), and plumbing Plivo's <Stream> audio into "
            "src/api/session.py's CallSession -- see docs/COMPLIANCE.md."
        )
