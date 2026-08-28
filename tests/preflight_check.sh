#!/usr/bin/env bash
# Fast pre-interview health check — run this ~15 min before the demo.
# Usage (Cloud Shell):  bash tests/preflight_check.sh
# Override target with: BASE_URL=https://... bash tests/preflight_check.sh
set -uo pipefail

BASE="${BASE_URL:-https://aviation-retrieval-967202573101.us-central1.run.app}"
RESP="$(mktemp)"
trap 'rm -f "$RESP"' EXIT

pass=0
fail=0

check() {
  local name="$1" method="$2" path="$3" data="${4:-}" timeout="${5:-30}"
  local code
  if [ -n "$data" ]; then
    code=$(curl -s -o "$RESP" -w "%{http_code}" -m "$timeout" -X "$method" "$BASE$path" -H "Content-Type: application/json" -d "$data")
  else
    code=$(curl -s -o "$RESP" -w "%{http_code}" -m "$timeout" -X "$method" "$BASE$path")
  fi
  if [ "$code" = "200" ]; then
    printf "  PASS  %-14s (HTTP %s)\n" "$name" "$code"
    pass=$((pass + 1))
  else
    printf "  FAIL  %-14s (HTTP %s)\n" "$name" "$code"
    head -c 300 "$RESP"
    echo
    fail=$((fail + 1))
  fi
}

echo "Pre-interview check against: $BASE"
echo

check "health"       GET  "/health"           "" 15
check "health/ready" GET  "/health/ready"     "" 20
check "retrieve"     POST "/retrieve"    '{"question":"What delays is Delta experiencing?","airline":"DL","days_back":30,"session_id":"preflight-retrieve"}'
check "agent"        POST "/agent"      '{"question":"Which airline has the worst on-time performance?","days_back":30,"session_id":"preflight-agent"}' 60
check "multi-agent"  POST "/multi-agent" '{"question":"Delta is showing high delays on BOS-EWR - what should operations do?","session_id":"preflight-multi"}' 60
check "coordinate"   POST "/coordinate"  '{"question":"Is the data fresh?","session_id":"preflight-coord"}' 60

echo
echo "Result: $pass passed, $fail failed"
if [ "$fail" -eq 0 ]; then
  echo "All systems go."
else
  echo "Investigate the failures above before the interview."
  exit 1
fi
