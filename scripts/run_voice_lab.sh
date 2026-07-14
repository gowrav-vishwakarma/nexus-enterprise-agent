#!/usr/bin/env bash
# Start Nexus media servers + Voice Lab UI for real end-to-end testing.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

SERVERS_CONFIG="${NEXUS_SERVERS_CONFIG:-examples/servers.yaml}"
VOICE_LAB_PORT="${VOICE_LAB_PORT:-8787}"
VOICE_LAB_HOST="${VOICE_LAB_HOST:-0.0.0.0}"

echo "==> Installing deps (server + voice lab)..."
uv sync --extra server --extra grpc --extra fastapi --extra realtime --extra litellm --extra openai -q
echo "==> Media servers config: $SERVERS_CONFIG"
echo "==> LLM: ${VOICE_LLM_MODEL:-${LITELLM_BASE_URL:-configure .env}}"

# Start gRPC media servers in background
uv run python -m nexus.server up -c "$SERVERS_CONFIG" &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

echo "==> Waiting for media servers..."
for i in $(seq 1 60); do
  if uv run python -m nexus.server health -c "$SERVERS_CONFIG" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "Media server process exited unexpectedly"
    exit 1
  fi
  sleep 2
done

echo "==> Starting Voice Lab on http://${VOICE_LAB_HOST}:${VOICE_LAB_PORT}"
exec uv run uvicorn examples.voice_lab:app --host "$VOICE_LAB_HOST" --port "$VOICE_LAB_PORT"
