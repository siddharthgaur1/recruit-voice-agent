"""Exotel telephony provider -- STUB ONLY. No credentials, no network calls.

Do not wire this up or place a real call until docs/COMPLIANCE.md's open
questions are resolved (DLT registration, DND scrubbing, calling-hours,
consent, recording).

What a real implementation needs:

  Credentials (from the Exotel dashboard, https://my.exotel.com):
    - account_sid   -- your Exotel account identifier
    - api_key       -- HTTP Basic Auth username
    - api_token     -- HTTP Basic Auth password
    - subdomain     -- e.g. "api.exotel.com" or an India-region subdomain
    - exophone      -- the virtual/DID number Exotel assigns you, used as
                        CallerId so the candidate sees a real, DLT-registered
                        number instead of a random one

  Placing a call (Voice v1 "Connect two numbers" API):
    POST https://{api_key}:{api_token}@{subdomain}/v1/Accounts/{account_sid}/Calls/connect.json
    form params:
      From      -- the agent/flow leg Exotel dials first (or a SIP endpoint
                   fronting this app's real-time audio bridge)
      To        -- the candidate's phone number
      CallerId  -- the exophone (must be DLT-registered for the message/
                   template category being used)
      Url       -- an Exotel "Applet"/flow URL that runs once the call
                   connects; this is what would stream call audio to/from
                   this app (e.g. via Exotel's Voicebot/AgentStream
                   WebSocket applet) so CallSession (src/api/session.py)
                   can run the same STT -> graph -> TTS loop used for the
                   browser mic simulator, just over real telephony audio
                   instead of a browser mic.

  Response: JSON with a Call `Sid`, `Status`, `From`, `To`, `Direction`
    ("outbound-api"), `DateCreated`, `RecordingUrl` (if recording is
    enabled -- it must not be, per RECORDING_ENABLED, until consent design
    is signed off).

  Mapping Exotel call `Status`/`DialCallStatus` values onto our CallOutcome:
    completed (human handled the AgentStream applet) -> HUMAN_ANSWERED
    no-answer                                         -> NO_ANSWER
    busy                                               -> BUSY
    failed / invalid number                            -> INVALID_NUMBER or FAILED
    (Exotel doesn't have a native "switched off" status distinct from
    no-answer/failed -- would need to be inferred from the SIP response
    code in the callback payload.)

  Rate limit: Exotel's Voice APIs cap at 200 calls/minute per account
  (HTTP 429 beyond that) -- relevant to how aggressively the scheduler
  should fan out concurrent dials.
"""

from src.dialer.provider import CallOutcome, TelephonyProvider


class ExotelProvider(TelephonyProvider):
    def __init__(self, account_sid: str, api_key: str, api_token: str,
                 subdomain: str, exophone: str):
        self.account_sid = account_sid
        self.api_key = api_key
        self.api_token = api_token
        self.subdomain = subdomain
        self.exophone = exophone

    def place_call(self, phone: str) -> CallOutcome:
        raise NotImplementedError(
            "ExotelProvider is a stub. Wiring this up means: DLT-registering "
            "the exophone/template, passing TRAI TCCCPR calling-hours + "
            "DND/NCPR checks, and getting the AgentStream applet plumbed "
            "into src/api/session.py's CallSession -- see docs/COMPLIANCE.md."
        )
