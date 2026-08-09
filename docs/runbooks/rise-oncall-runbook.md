# RISE On-Call Runbook — System Diagnostics & Emergency Procedures

## 1. Scope & Purpose
This runbook covers operational procedures when **RISE itself is misbehaving, degraded, or down** (e.g. LLM Gateway failures, queue backup, worker crashes, OPA policy unreachability).

## 2. Emergency Emergency-Disable / Policy Kill-Switch
If RISE's Execution Agent is taking unintended automated actions or misbehaving:

### Instant Emergency Lock Down (Revert to 100% Shadow Mode)
Run the emergency policy deactivation API command or script:
```bash
# Deactivate all auto-approval policies via Admin API
curl -X DELETE http://api.rise.internal/policies/pol-001 -H "Authorization: Bearer $ADMIN_JWT"

# Alternatively, set active=false on the policy row
curl -X PUT http://api.rise.internal/policies/pol-001 -H "Authorization: Bearer $ADMIN_JWT" -H "Content-Type: application/json" -d '{"requires_approval": true}'
```
This immediately forces `requires_approval = True` for ALL actions system-wide.

## 3. High Queue Depth / Stuck Agent Pipeline
1. Check queue status: `kubectl exec -it deployment/rise-api -- redis-cli llen agent_jobs`
2. If queue is backing up (>50 items), scale agent workers: `kubectl scale deployment/rise-worker --replicas=10`
3. Flush corrupted jobs if necessary: `python -m apps.agents.src.admin.flush_queue --tenant-id=<id>`

## 4. LLM Provider Failover Diagnostics
1. Check primary provider status: `kubectl logs deployment/rise-worker | grep "LLM Gateway"`
2. Force fallback provider: update ConfigMap `LLM_PROVIDER=openai` (or `ollama` for local fallback).

## 5. Secrets & Credential Rotation
Follow `docs/runbooks/secret-rotation.md` for rotating GitHub App keys, Slack tokens, or AWS IAM credentials.
