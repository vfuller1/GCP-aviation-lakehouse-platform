$url = "https://aviation-retrieval-ohvijuloea-uc.a.run.app/retrieve"
$sid = "demo-$(Get-Date -Format 'HHmmss')"
Write-Host "Session: $sid" -ForegroundColor Cyan

Write-Host "`n=== Q1: Delay Root Cause ===" -ForegroundColor Cyan
Invoke-RestMethod -Uri $url -Method POST -ContentType "application/json" -Body (@{ question="What are the top causes of delays for United Airlines and how severe are they?"; airline="UA"; days_back=7; top_k=5; session_id=$sid } | ConvertTo-Json) -TimeoutSec 60 | Select-Object -ExpandProperty answer

Read-Host "`nPress Enter for Q2"

Write-Host "`n=== Q2: Worst Route (memory test 1) ===" -ForegroundColor Cyan
Invoke-RestMethod -Uri $url -Method POST -ContentType "application/json" -Body (@{ question="Which of those routes you just mentioned has the worst average delay?"; session_id=$sid } | ConvertTo-Json) -TimeoutSec 60 | Select-Object -ExpandProperty answer

Read-Host "`nPress Enter for Q3"

Write-Host "`n=== Q3: Weather on Worst Route (memory test 2) ===" -ForegroundColor Cyan
Invoke-RestMethod -Uri $url -Method POST -ContentType "application/json" -Body (@{ question="For that worst route, what percentage of delays were caused by weather?"; session_id=$sid } | ConvertTo-Json) -TimeoutSec 60 | Select-Object -ExpandProperty answer

Read-Host "`nPress Enter for Q4"

Write-Host "`n=== Q4: Single Recommendation (memory test 3) ===" -ForegroundColor Cyan
Invoke-RestMethod -Uri $url -Method POST -ContentType "application/json" -Body (@{ question="Based on everything we have discussed, what is your single recommendation to reduce delays?"; session_id=$sid } | ConvertTo-Json) -TimeoutSec 60 | Select-Object -ExpandProperty answer

Write-Host "`nDemo complete. Session: $sid" -ForegroundColor Cyan
