#!/usr/bin/env bash
# Go/no-go check #1 (AGENT_HUB_DESIGN.md §8): list models MaaS + test tool-calling.
# Cách chạy:  bash checks/check1_maas.sh
# PASS = thấy "tool_use" (Anthropic) hoặc "tool_calls" (OpenAI) trong response → Plan A.
set -uo pipefail

cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; source .env; set +a; fi
: "${MAAS_API_KEY:?Thiếu MAAS_API_KEY — copy .env.example thành .env rồi điền key}"
BASE="${MAAS_BASE_URL:-https://maas-llm-aiplatform-hcm.api.vngcloud.vn}"

echo "===== [1/3] List models (OpenAI-compatible: $BASE/v1/models) ====="
curl -sS --max-time 30 "$BASE/v1/models" \
  -H "Authorization: Bearer $MAAS_API_KEY" | tee /tmp/maas_models.json
echo

MODEL="${MODEL:-$(python3 -c "import json;d=json.load(open('/tmp/maas_models.json'));print(d['data'][0]['id'])" 2>/dev/null || true)}"
if [ -z "$MODEL" ]; then
  echo "!! Không parse được danh sách model — xem output trên, có thể sai key/endpoint."
  exit 1
fi
echo ">> Model dùng để test tool-call: $MODEL (đổi bằng biến MODEL trong .env)"
echo

TOOL_PROMPT='Hôm nay là ngày mấy? Hãy dùng tool.'

echo "===== [2/3] Tool-call test — protocol OpenAI ($BASE/v1/chat/completions) ====="
curl -sS --max-time 60 "$BASE/v1/chat/completions" \
  -H "Authorization: Bearer $MAAS_API_KEY" -H "Content-Type: application/json" \
  -d "{
    \"model\": \"$MODEL\",
    \"messages\": [{\"role\": \"user\", \"content\": \"$TOOL_PROMPT\"}],
    \"tools\": [{\"type\": \"function\", \"function\": {
      \"name\": \"get_current_date\",
      \"description\": \"Trả về ngày hiện tại\",
      \"parameters\": {\"type\": \"object\", \"properties\": {}}}}]
  }" | tee /tmp/maas_tool_openai.json
echo

echo "===== [3/3] Tool-call test — protocol Anthropic ($BASE/v1/messages) ====="
curl -sS --max-time 60 "$BASE/v1/messages" \
  -H "x-api-key: $MAAS_API_KEY" -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"$MODEL\",
    \"max_tokens\": 512,
    \"messages\": [{\"role\": \"user\", \"content\": \"$TOOL_PROMPT\"}],
    \"tools\": [{
      \"name\": \"get_current_date\",
      \"description\": \"Trả về ngày hiện tại\",
      \"input_schema\": {\"type\": \"object\", \"properties\": {}}}]
  }" | tee /tmp/maas_tool_anthropic.json
echo

echo "===== KẾT LUẬN ====="
grep -q '"tool_calls"' /tmp/maas_tool_openai.json    && echo "OpenAI protocol   : PASS (có tool_calls)" || echo "OpenAI protocol   : FAIL/không thấy tool_calls"
grep -q '"tool_use"'   /tmp/maas_tool_anthropic.json && echo "Anthropic protocol: PASS (có tool_use)"  || echo "Anthropic protocol: FAIL/không thấy tool_use"
echo "PASS ít nhất 1 protocol → Plan A. Cả hai FAIL → Plan B (xem §8)."
