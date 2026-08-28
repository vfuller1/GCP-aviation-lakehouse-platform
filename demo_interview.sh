#!/usr/bin/env bash
# Guided interview demo — GCP Aviation Lakehouse Platform
# Run in GCP Cloud Shell:  bash demo_interview.sh
# Override the target service with:  BASE_URL=https://... bash demo_interview.sh
set -uo pipefail

BASE="${BASE_URL:-https://aviation-retrieval-967202573101.us-central1.run.app}"
SESSION="interview-$(date +%s)"

BOLD=$(tput bold 2>/dev/null || echo "")
DIM=$(tput dim 2>/dev/null || echo "")
CYAN=$(tput setaf 6 2>/dev/null || echo "")
GREEN=$(tput setaf 2 2>/dev/null || echo "")
YELLOW=$(tput setaf 3 2>/dev/null || echo "")
RESET=$(tput sgr0 2>/dev/null || echo "")

command -v jq >/dev/null 2>&1 || { echo "jq is required (Cloud Shell has it preinstalled)."; exit 1; }

pause() {
  echo
  read -rp "${DIM}[Press Enter to continue]${RESET} " _
  echo
}

section() {
  echo
  echo "${BOLD}${CYAN}══════════════════════════════════════════════════════════${RESET}"
  echo "${BOLD}${CYAN}  $1${RESET}"
  echo "${BOLD}${CYAN}══════════════════════════════════════════════════════════${RESET}"
}

narrate() {
  echo "${YELLOW}$1${RESET}"
  echo
}

call() {
  local endpoint="$1" payload="$2"
  curl -s -m 60 -X POST "$BASE$endpoint" -H "Content-Type: application/json" -d "$payload"
}

clear
echo "${BOLD}${CYAN}GCP AVIATION LAKEHOUSE PLATFORM — LIVE DEMO${RESET}"
echo "Session prefix : ${SESSION}"
echo "Target service : ${BASE}"
pause

# ---------------------------------------------------------------------------
section "0. Service Health"
narrate "Confirming the platform is live before we start."
curl -s -m 15 -w "\n${GREEN}HTTP %{http_code}${RESET}\n" "$BASE/health"
curl -s -m 20 -w "\n${GREEN}HTTP %{http_code}${RESET}\n" "$BASE/health/ready"
pause

# ---------------------------------------------------------------------------
section "1. The Router — /ask auto-selects the right AI layer"
narrate "A zero-latency regex heuristic decides: a simple factual question routes to /retrieve (fast path), a comparative/ranking question routes to /agent (reasoning loop) — no LLM call spent just to decide which LLM call to make."

echo "${BOLD}Q: \"What delays is Delta experiencing?\"${RESET}  (expect routed_to=retrieve)"
call "/ask" "{\"question\":\"What delays is Delta experiencing?\",\"airline\":\"DL\",\"days_back\":30,\"session_id\":\"${SESSION}-ask1\"}" \
  | jq -r '"\n  routed_to  : \(.routed_to)\n  tools_used : \(.tools_used)\n  answer     : \(.answer[0:280])"'
pause

echo "${BOLD}Q: \"Which airline has the worst on-time performance this week?\"${RESET}  (expect routed_to=agent)"
call "/ask" "{\"question\":\"Which airline has the worst on-time performance this week?\",\"days_back\":30,\"session_id\":\"${SESSION}-ask2\"}" \
  | jq -r '"\n  routed_to    : \(.routed_to)\n  tools_called : \(.tools_called)\n  steps        : \(.steps)\n  answer       : \(.answer[0:280])"'
pause

# ---------------------------------------------------------------------------
section "2. RAG Retrieval + Session Memory — /retrieve"
narrate "Fixed pipeline: embed -> Vector Search -> BigQuery fallback (if <3 hits) -> Gemini, one call. This turn also seeds Firestore session memory for the follow-up."

echo "${BOLD}Q1: \"What are the top causes of delays for United Airlines?\"${RESET}"
call "/retrieve" "{\"question\":\"What are the top causes of delays for United Airlines and how severe are they?\",\"airline\":\"UA\",\"days_back\":30,\"session_id\":\"${SESSION}-rag\"}" \
  | jq -r '"\n  tools_used    : \(.tools_used)\n  facts/context : \(.facts_count) / \(.context_count)\n  answer        : \(.answer)"'
pause

narrate "Follow-up on the SAME session_id — the question never repeats 'United'; the answer must come from Firestore session memory."
echo "${BOLD}Q2: \"Which of those routes you just mentioned has the worst average delay?\"${RESET}"
call "/retrieve" "{\"question\":\"Which of those routes you just mentioned has the worst average delay?\",\"session_id\":\"${SESSION}-rag\"}" \
  | jq -r '"\n  answer : \(.answer)"'
pause

# ---------------------------------------------------------------------------
section "3. Autonomous Reasoning — /agent (LangGraph single-agent)"
narrate "One decision-maker loops over 3 tools (search_flight_records, query_analytics, get_pipeline_status), choosing what to call and when to stop. Watch tools_called and steps."

echo "${BOLD}Q: \"Which airline has the most weather-related delays this week?\"${RESET}"
call "/agent" "{\"question\":\"Which airline has the most weather-related delays this week?\",\"session_id\":\"${SESSION}-agent\"}" \
  | jq -r '"\n  tools_called : \(.tools_called)\n  steps        : \(.steps)\n  tokens       : \(.token_usage.total_tokens)\n  answer       : \(.answer)"'
pause

narrate "Multi-turn follow-up — never names an airline; the agent must pull it from session history."
echo "${BOLD}Q2: \"For that same airline, which specific routes are worst affected?\"${RESET}"
call "/agent" "{\"question\":\"For that same airline, which specific routes are worst affected?\",\"session_id\":\"${SESSION}-agent\"}" \
  | jq -r '"\n  tools_called : \(.tools_called)\n  steps        : \(.steps)\n  answer       : \(.answer)"'
pause

# ---------------------------------------------------------------------------
section "4. Genuine Multi-Agent — /multi-agent (Google ADK, fixed sequence)"
narrate "Two distinct agents with a real dependency chain: Risk Analyst detects & quantifies -> hands its output to Mitigation Advisor, which has NO tools and reasons only over that output. Always both, always this order — this is the multi-step vs multi-agent distinction."

echo "${BOLD}Q: \"Delta is showing high delays on BOS-EWR - what should operations do?\"${RESET}"
call "/multi-agent" "{\"question\":\"Delta is showing high delays on BOS-EWR - what should operations do?\",\"session_id\":\"${SESSION}-multi\"}" \
  | jq -r '"\n  agents_run   : \(.agents_run)\n  total_tokens : \(.total_tokens)\n  answer       : \(.answer)"'
pause

# ---------------------------------------------------------------------------
section "5. Dynamic Coordination — /coordinate (Google ADK, LLM-routed)"
narrate "An LLM-powered coordinator decides which of 4 workers are even relevant per question, instead of always running a fixed list. Watch workers_called change across the two questions below."

echo "${BOLD}Q1: \"Is the data fresh?\"${RESET}  (expect pipeline_health only)"
call "/coordinate" "{\"question\":\"Is the data fresh?\",\"session_id\":\"${SESSION}-coord1\"}" \
  | jq -r '"\n  workers_called : \(.workers_called)\n  total_tokens   : \(.total_tokens)\n  answer         : \(.answer)"'
pause

echo "${BOLD}Q2: \"Delta is delayed on BOS-EWR - is this weather or scheduling, and what should ops do?\"${RESET}  (expect multiple workers)"
call "/coordinate" "{\"question\":\"Delta is delayed on BOS-EWR - is this weather or scheduling, and what should ops do?\",\"session_id\":\"${SESSION}-coord2\"}" \
  | jq -r '"\n  workers_called : \(.workers_called)\n  total_tokens   : \(.total_tokens)\n  answer         : \(.answer)"'
pause

# ---------------------------------------------------------------------------
section "Demo complete"
echo "Session IDs used (Firestore rag-sessions, 1hr TTL): ${SESSION}-ask1/-ask2/-rag/-agent/-multi/-coord1/-coord2"
echo
echo "${BOLD}Talking points if asked \"why build it this way\":${RESET}"
echo "  - /ask: cost/speed tradeoff — a regex router costs \$0 and 0ms vs an LLM-based router"
echo "  - /retrieve vs /agent: fixed pipeline vs an autonomous tool-selection loop (single-agent, multi-step)"
echo "  - /multi-agent vs /coordinate: fixed 2-worker handoff vs LLM-decided 1-to-4-worker dynamic routing"
echo "  - BigQuery fallback: the system never returns an empty answer, even while Vector Search is rebuilding"
