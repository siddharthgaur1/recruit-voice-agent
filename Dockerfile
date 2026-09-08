# Runs the text/dialer side of the agent: the API, the dashboard, and demo.py.
#
# It deliberately does NOT cover the local voice loop -- that needs a
# microphone and the Piper voice model, neither of which belong in an image
# (the model is 63MB and the mic can't be containerised on most hosts).
# For voice, run it on the host: see README's "Local voice loop" section.
FROM python:3.11-slim

# webrtcvad builds from source on linux (no manylinux wheel)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bind 0.0.0.0 inside the container; the app REFUSES to start on a non-local
# bind without RECRUIT_AGENT_API_KEY set (src/api/main.py), so pass one:
#   docker run -e RECRUIT_AGENT_API_KEY=... -e BIND_HOST=0.0.0.0 -p 8000:8000 recruit-voice-agent
ENV BIND_HOST=0.0.0.0 \
    BIND_PORT=8000
EXPOSE 8000

CMD ["python", "-m", "src.api.main"]
