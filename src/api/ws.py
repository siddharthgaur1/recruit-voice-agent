import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.agent.graph import build_graph
from src.agent.llm import build_llm_client
from src.agent.session import new_call_state
from src.api.auth import websocket_api_key_ok
from src.api.rate_limit import RateLimitExceeded, check_and_register, release
from src.api.session import CallSession
from src.config import settings
from src.db.repo import (
    create_call_attempt,
    create_lead,
    make_engine,
    make_session_factory,
    save_conversation_result,
)
from src.voice.stt import get_transcriber
from src.voice.tts import get_synthesizer
from src.voice.vad import frame_bytes

router = APIRouter()

FRAME_BYTES = frame_bytes()
SILENCE_CHECK_INTERVAL_S = 1.0

# WebSocket close codes (4000-4999 are reserved for application use)
CLOSE_UNAUTHORIZED = 4401
CLOSE_RATE_LIMITED = 4429


async def _send_event(websocket: WebSocket, event: dict) -> None:
    audio = event.pop("audio", None)
    await websocket.send_json(event)
    if audio:
        await websocket.send_bytes(audio)


@router.websocket("/ws/call")
async def call_ws(websocket: WebSocket) -> None:
    if not websocket_api_key_ok(websocket):
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="missing or invalid api_key")
        return

    client_ip = websocket.client.host if websocket.client else "unknown"
    try:
        check_and_register(client_ip)
    except RateLimitExceeded as e:
        await websocket.close(code=CLOSE_RATE_LIMITED, reason=str(e))
        return

    await websocket.accept()

    engine = make_engine(settings.db_path)
    db_session = make_session_factory(engine)()
    lead = create_lead(db_session, phone="+91-0000000000", name="Browser Candidate")
    attempt = create_call_attempt(db_session, lead.id)

    llm = build_llm_client()
    call = CallSession(
        state=new_call_state(lead.id, attempt.id),
        graph=build_graph(llm),
        transcriber=get_transcriber(),
        synthesizer=get_synthesizer(),
    )

    frame_buffer = bytearray()
    call_ended = False

    try:
        await _send_event(websocket, call.opening())

        while not call_ended:
            try:
                chunk = await asyncio.wait_for(
                    websocket.receive_bytes(), timeout=SILENCE_CHECK_INTERVAL_S
                )
            except asyncio.TimeoutError:
                for event in call.check_silence_timeout():
                    await _send_event(websocket, event)
                    if event.get("type") == "call_ended":
                        call_ended = True
                continue

            frame_buffer.extend(chunk)
            while len(frame_buffer) >= FRAME_BYTES:
                frame = bytes(frame_buffer[:FRAME_BYTES])
                del frame_buffer[:FRAME_BYTES]
                for event in call.handle_frame(frame):
                    if event.get("type") == "process_utterance":
                        # Filler audio (sent just before this marker) is
                        # already on the wire; run the slow STT/LLM/TTS work
                        # off the event loop so it doesn't delay it further.
                        for real_event in await asyncio.to_thread(
                            call.process_utterance, event["audio"]
                        ):
                            await _send_event(websocket, real_event)
                            if real_event.get("type") == "call_ended":
                                call_ended = True
                        continue
                    await _send_event(websocket, event)
                    if event.get("type") == "call_ended":
                        call_ended = True

        await websocket.close()
    except WebSocketDisconnect:
        pass
    finally:
        outcome = call.state.get("outcome") or "DISCONNECTED"
        save_conversation_result(
            db_session,
            lead_id=call.state["lead_id"],
            call_attempt_id=call.state["call_attempt_id"],
            slots=call.state["slots"],
            transcript=call.state["transcript"],
            outcome=outcome,
            dnc=call.dnc,
            domain_raw=call.state.get("domain_raw"),
        )
        db_session.close()
        release()
