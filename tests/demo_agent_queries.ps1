#!/usr/bin/env pwsh
# ============================================================
# Aviation Agent Demo — Tests the LangGraph /agent endpoint
# Shows the agent calling multiple tools autonomously.
# Usage: .\demo_agent_queries.ps1 [-ServiceUrl <url>]
# ============================================================

param(
    [string]$ServiceUrl = "https://aviation-retrieval-ohvijuloea-uc.a.run.app"
)

$ServiceUrl = $ServiceUrl.TrimEnd('/')
$AgentUrl   = "$ServiceUrl/agent"
$SessionId  = "agent-demo-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

function Invoke-AgentQuery {
    param(
        [string]$Label,
        [string]$Question
    )

    Write-Host "`n============================================================" -ForegroundColor Magenta
    Write-Host " $Label" -ForegroundColor Magenta
    Write-Host "============================================================" -ForegroundColor Magenta
    Write-Host " Q: $Question" -ForegroundColor Yellow

    $body = @{
        question   = $Question
        session_id = $SessionId
    }

    try {
        $response = Invoke-RestMethod `
            -Uri         $AgentUrl `
            -Method      POST `
            -ContentType "application/json" `
            -Body        ($body | ConvertTo-Json -Depth 3) `
            -TimeoutSec  90

        Write-Host "`n A: $($response.answer)" -ForegroundColor Green

        $tools = if ($response.tools_called) { $response.tools_called -join " → " } else { "none" }
        Write-Host "`n   [Tools called: $tools | Steps: $($response.steps)]" -ForegroundColor DarkGray
    }
    catch {
        Write-Host "`n ERROR: $_" -ForegroundColor Red
    }
}

# ------------------------------------------------------------------
# Health check
# ------------------------------------------------------------------
Write-Host "`nChecking service at $ServiceUrl ..." -ForegroundColor White
try {
    $health = Invoke-RestMethod -Uri "$ServiceUrl/health/ready" -Method GET -TimeoutSec 15
    Write-Host " Service ready: $($health.ready)" -ForegroundColor Green
}
catch {
    Write-Host " WARNING: Health check failed — trying queries anyway." -ForegroundColor Yellow
}

# ------------------------------------------------------------------
# Q1 — Multi-tool: agent should call query_analytics AND
#       search_flight_records to compare aggregate stats with events
# ------------------------------------------------------------------
Invoke-AgentQuery `
    -Label    "1 of 4 — Multi-tool: Worst Airline for ATL Travellers" `
    -Question "I am flying into Atlanta this week. Which airline should I avoid due to weather-related delays, and how bad are they specifically?"

# ------------------------------------------------------------------
# Q2 — Refinement loop: if route_risk view is empty, agent falls
#       back to query_analytics with query_type='generic'
# ------------------------------------------------------------------
Invoke-AgentQuery `
    -Label    "2 of 4 — Route Risk with Fallback" `
    -Question "What are the top 3 highest-risk routes in the network and what is driving that risk?"

# ------------------------------------------------------------------
# Q3 — Pipeline status: question implies data recency concern,
#       so agent should call get_pipeline_status
# ------------------------------------------------------------------
Invoke-AgentQuery `
    -Label    "3 of 4 — Data Freshness Check" `
    -Question "How recent is the data you are using? When was the last pipeline run and how many records are in the system?"

# ------------------------------------------------------------------
# Q4 — Multi-turn (uses Firestore session history from Q1-Q3)
# ------------------------------------------------------------------
Invoke-AgentQuery `
    -Label    "4 of 4 — Multi-turn Follow-up (Session Memory)" `
    -Question "Based on everything you have told me so far, what single operational change would have the biggest impact on reducing delays network-wide?"

Write-Host "`n============================================================" -ForegroundColor Magenta
Write-Host " Agent demo complete — Session ID: $SessionId" -ForegroundColor Magenta
Write-Host " Compare tool counts above vs /retrieve to see autonomous routing." -ForegroundColor DarkGray
Write-Host "============================================================`n" -ForegroundColor Magenta
