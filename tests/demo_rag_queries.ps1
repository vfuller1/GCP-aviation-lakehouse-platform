#!/usr/bin/env pwsh
# ============================================================
# Aviation RAG Demo — 4 Live Query Tests
# Usage: .\demo_rag_queries.ps1 [-ServiceUrl <url>]
# ============================================================

param(
    [string]$ServiceUrl = "https://aviation-retrieval-ohvijuloea-uc.a.run.app"
)

$ServiceUrl = $ServiceUrl.TrimEnd('/')
$RetrieveUrl = "$ServiceUrl/retrieve"

# Shared session ID so Gemini remembers context across all 4 questions
$SessionId = "demo-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

function Invoke-RAGQuery {
    param(
        [string]$Label,
        [string]$Question,
        [hashtable]$Extra = @{}
    )

    Write-Host "`n============================================================" -ForegroundColor Cyan
    Write-Host " $Label" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " Q: $Question" -ForegroundColor Yellow

    $body = @{
        question   = $Question
        days_back  = 7
        top_k      = 5
        session_id = $SessionId
    }
    foreach ($key in $Extra.Keys) { $body[$key] = $Extra[$key] }

    try {
        $response = Invoke-RestMethod `
            -Uri         $RetrieveUrl `
            -Method      POST `
            -ContentType "application/json" `
            -Body        ($body | ConvertTo-Json -Depth 3) `
            -TimeoutSec  60

        Write-Host "`n A: $($response.answer)" -ForegroundColor Green

        $factCount = if ($response.facts) { $response.facts.Count } else { 0 }
        $docCount  = if ($response.context_docs) { $response.context_docs.Count } else { 0 }
        Write-Host "`n   [BigQuery facts: $factCount | Vector docs: $docCount]" -ForegroundColor DarkGray
    }
    catch {
        Write-Host "`n ERROR: $_" -ForegroundColor Red
    }
}

# ------------------------------------------------------------------
# Health check first
# ------------------------------------------------------------------
Write-Host "`nChecking service health at $ServiceUrl ..." -ForegroundColor White
try {
    $health = Invoke-RestMethod -Uri "$ServiceUrl/health/ready" -Method GET -TimeoutSec 15
    Write-Host " Service status: $($health.status)" -ForegroundColor Green
}
catch {
    Write-Host " WARNING: Health check failed — service may still respond to queries." -ForegroundColor Yellow
}

# ------------------------------------------------------------------
# Query 1 — Delay Root Cause (Airline-scoped)
# ------------------------------------------------------------------
Invoke-RAGQuery `
    -Label    "1 of 4 — Delay Root Cause" `
    -Question "What are the top causes of delays for United Airlines flights and how severe are they?" `
    -Extra    @{ airline = "UA" }

# ------------------------------------------------------------------
# Query 2 — Route Risk Analysis
# ------------------------------------------------------------------
Invoke-RAGQuery `
    -Label    "2 of 4 — Route Risk Analysis" `
    -Question "What is the risk level for the Atlanta to Los Angeles route? Which disruptions are most common?" `
    -Extra    @{ route = "ATL-LAX" }

# ------------------------------------------------------------------
# Query 3 — Weather Impact Analytics
# ------------------------------------------------------------------
Invoke-RAGQuery `
    -Label    "3 of 4 — Weather Impact Analytics" `
    -Question "How many flights were affected by weather in the last 7 days and what percentage of total flights does that represent?"

# ------------------------------------------------------------------
# Query 4 — Follow-up (tests Firestore session memory)
# ------------------------------------------------------------------
Invoke-RAGQuery `
    -Label    "4 of 4 — Follow-up (Session Memory)" `
    -Question "Based on what you just told me about weather impact, which airline handled it best?"

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " Demo complete — Session ID: $SessionId" -ForegroundColor Cyan
Write-Host "============================================================`n" -ForegroundColor Cyan
