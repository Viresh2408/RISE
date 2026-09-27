# RISE - Phase -1 through Phase 3 Verification Script
# Run this from the repo root (C:\Project\RISE) in PowerShell.
# Usage: .\verify_phases.ps1
# Output is both printed to screen and saved to verify_phases_output.log

$logFile = "verify_phases_output.log"
"RISE Verification Run - $(Get-Date)" | Tee-Object -FilePath $logFile

function Section($title) {
    ""
    ("=" * 70)
    "  $title"
    ("=" * 70)
    "" | Tee-Object -FilePath $logFile -Append
}

# ---------------------------------------------------------------
Section "PHASE -1 - Repo hygiene & structural consistency"
# ---------------------------------------------------------------

"-- policies\risk_tiers.rego exists?" | Tee-Object -FilePath $logFile -Append
(Test-Path policies\risk_tiers.rego) | Tee-Object -FilePath $logFile -Append

"-- policies\approval_rules.rego exists?" | Tee-Object -FilePath $logFile -Append
(Test-Path policies\approval_rules.rego) | Tee-Object -FilePath $logFile -Append

"-- mcp-slack server file exists?" | Tee-Object -FilePath $logFile -Append
(Test-Path packages\mcp-servers\mcp-slack\slack_server.py) | Tee-Object -FilePath $logFile -Append

"-- mcp-observability / mcp-knowledge directories exist?" | Tee-Object -FilePath $logFile -Append
(Test-Path packages\mcp-servers\mcp-observability) | Tee-Object -FilePath $logFile -Append
(Test-Path packages\mcp-servers\mcp-knowledge) | Tee-Object -FilePath $logFile -Append

"-- git status (check for tracked debug/log/db artifacts)" | Tee-Object -FilePath $logFile -Append
git status | Tee-Object -FilePath $logFile -Append

"-- tracked debug/analysis/db files (should be empty)" | Tee-Object -FilePath $logFile -Append
git ls-files | Select-String "audit_analysis|debug_|_test_run|rise_dev\.db|dec_out" | Tee-Object -FilePath $logFile -Append

"-- duplicate tenant_resolver.py / signature_verifier.py locations" | Tee-Object -FilePath $logFile -Append
Get-ChildItem -Recurse -Include "tenant_resolver.py","signature_verifier.py" -Path apps\ |
    Select-Object FullName | Tee-Object -FilePath $logFile -Append

# ---------------------------------------------------------------
Section "PHASE 0 - Security (critical gate - must be clean)"
# ---------------------------------------------------------------

"-- Auth backdoor check (should return NOTHING)" | Tee-Object -FilePath $logFile -Append
Select-String -Path "apps\api\src\deps\auth.py" -Pattern "demo-token-hardcoded","demo-" |
    Tee-Object -FilePath $logFile -Append

"-- CORS config (should NOT show allow_origins=[""*""])" | Tee-Object -FilePath $logFile -Append
Select-String -Path "apps\api\src\main.py" -Pattern "allow_origins" |
    Tee-Object -FilePath $logFile -Append

"-- Fake commit SHA in dashboard (should return NOTHING)" | Tee-Object -FilePath $logFile -Append
Get-ChildItem -Path "apps\dashboard\" -Recurse -Include *.ts,*.tsx |
    Select-String -Pattern "101a1992ff" | Tee-Object -FilePath $logFile -Append

"-- Hardcoded fabricated incidents in dashboard (spot check, review manually)" | Tee-Object -FilePath $logFile -Append
Get-ChildItem -Path "apps\dashboard\" -Recurse -Include *.ts,*.tsx |
    Select-String -Pattern "fabricat|hardcoded.*incident|MOCK_INCIDENTS|DEMO_INCIDENTS" |
    Tee-Object -FilePath $logFile -Append

"-- JWT secret fail-closed check (temporarily unsets env var, tests import)" | Tee-Object -FilePath $logFile -Append
$originalSecret = $env:SUPABASE_JWT_SECRET
$env:SUPABASE_JWT_SECRET = ""
try {
    poetry run python -c "from apps.api.src.main import app; print('APP LOADED - THIS MAY BE A PROBLEM if it loaded without a JWT secret')" 2>&1 |
        Tee-Object -FilePath $logFile -Append
} catch {
    "App failed to load as expected (good) - $($_.Exception.Message)" | Tee-Object -FilePath $logFile -Append
}
if ($originalSecret) { $env:SUPABASE_JWT_SECRET = $originalSecret } else { Remove-Item Env:\SUPABASE_JWT_SECRET -ErrorAction SilentlyContinue }

# ---------------------------------------------------------------
Section "PHASE 1 - Test fixes"
# ---------------------------------------------------------------

"-- Safety invariant regression tests (all 11+2 should run, not silently skip)" | Tee-Object -FilePath $logFile -Append
poetry run pytest tests\test_safety_invariants_regression.py -v 2>&1 | Tee-Object -FilePath $logFile -Append

"-- Full test suite summary (last 30 lines)" | Tee-Object -FilePath $logFile -Append
poetry run pytest -v 2>&1 | Select-Object -Last 30 | Tee-Object -FilePath $logFile -Append

# ---------------------------------------------------------------
Section "PHASE 2 - Gateway enforcement gap"
# ---------------------------------------------------------------

"-- OPA allow-list naming / real client usage" | Tee-Object -FilePath $logFile -Append
Select-String -Path "packages\rise-core\mcp_client\gateway.py" -Pattern "evaluate_opa_allowlist|evaluate_python_allowlist|opa_client" |
    Tee-Object -FilePath $logFile -Append

"-- Resource lock / plan-hash check location in gateway" | Tee-Object -FilePath $logFile -Append
Select-String -Path "packages\rise-core\mcp_client\gateway.py" -Pattern "lock|plan_hash|acquire" |
    Tee-Object -FilePath $logFile -Append

"-- Execution Agent MCP tests" | Tee-Object -FilePath $logFile -Append
poetry run pytest apps\agents\tests\test_execution_agent_mcp.py -v 2>&1 | Tee-Object -FilePath $logFile -Append

"-- Audit write UUID-swallow bug check" | Tee-Object -FilePath $logFile -Append
Select-String -Path "packages\rise-core\mcp_client\gateway.py" -Pattern "except.*:.*pass|badly formed hexadecimal" |
    Tee-Object -FilePath $logFile -Append

# ---------------------------------------------------------------
Section "PHASE 3 - Hardcoded/facade router fixes"
# ---------------------------------------------------------------

"-- API test suite (routers)" | Tee-Object -FilePath $logFile -Append
poetry run pytest apps\api\tests\ -v 2>&1 | Tee-Object -FilePath $logFile -Append

"-- Spot check: do these routers query the DB, or return static dicts?" | Tee-Object -FilePath $logFile -Append
$routersToCheck = @("actions.py","agent_runs.py","knowledge.py","policies.py","verification.py","root_cause_impact.py")
foreach ($r in $routersToCheck) {
    "  -- apps\api\src\routers\$r --" | Tee-Object -FilePath $logFile -Append
    Select-String -Path "apps\api\src\routers\$r" -Pattern "db\.query|session\.query|select\(|await db|\.execute\(" |
        Measure-Object | Select-Object -ExpandProperty Count |
        ForEach-Object { "    real DB call occurrences: $_" } | Tee-Object -FilePath $logFile -Append
}

"-- compute_risk_score signature consistency" | Tee-Object -FilePath $logFile -Append
Select-String -Path "apps\api\src\services\report_generator.py","apps\api\src\routers\incidents.py" -Pattern "compute_risk_score" |
    Tee-Object -FilePath $logFile -Append

"-- Regression test for risk_score <= 0 path" | Tee-Object -FilePath $logFile -Append
poetry run pytest tests\test_report_risk_score_regression.py -v 2>&1 | Tee-Object -FilePath $logFile -Append

# ---------------------------------------------------------------
Section "DONE - Full output saved to $logFile"
# ---------------------------------------------------------------
"Review the log file above. Anything under PHASE 0 that returned a match is a BLOCKER." |
    Tee-Object -FilePath $logFile -Append
