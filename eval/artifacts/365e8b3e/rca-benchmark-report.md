# Live RCA Benchmark Report

> **PILOT -- NOT RELEASE ELIGIBLE**  
> n=10 -- release gate requires n>=50

| Field | Value |
|:---|:---|
| Run ID | `365e8b3e` |
| Timestamp (UTC) | 2026-09-25T18:42:00.780736+00:00 |
| Provider | groq |
| Model | openai/gpt-oss-120b |
| Git SHA | `e1f426e` |
| Dataset hash | `3419be85cf4c27fd` |
| Live | Yes |
| Release eligible | **No** -- pilot only |

## Results

**Mechanism accuracy: 18.2%** (2/11 passed)

| ID | Title | Cause Summary | Components | Mechanisms | Hallucination | Result |
|:--|:--|:--|:--|:--|:--|:--|
| 1 | payment-service high error rate -- 503... | The new pending‑transaction query added in v2.4.1 is sl... | connection pool | exhaustion, saturated | None | PASS |
| 1 | payment-service high error rate -- 503... |  | NONE | NONE | None | ERROR |
| 2 | payment-service memory leak causing OO... | The newly introduced billing audit middleware in deploy... | listener, EventEmitter | leak | None | PASS |
| 3 | auth-service JWT validation latency sp... | Fallback root cause: LLM Gateway call failed | NONE | NONE | None | FAIL |
| 4 | auth-service complete outage -- miscon... | Fallback root cause: LLM Gateway call failed | NONE | NONE | None | FAIL |
| 5 | notification-service queue backlog -- ... | Fallback root cause: LLM Gateway call failed | NONE | NONE | None | FAIL |
| 6 | notification-service Slack webhook rat... | Fallback root cause: LLM Gateway call failed | NONE | NONE | None | FAIL |
| 7 | api-gateway 502 cascade -- upstream co... | Fallback root cause: LLM Gateway call failed | NONE | NONE | None | FAIL |
| 8 | api-gateway TLS 1.0 deprecation breaki... | Fallback root cause: LLM Gateway call failed | NONE | NONE | None | FAIL |
| 9 | payment-service duplicate charge bug a... | Fallback root cause: LLM Gateway call failed | NONE | NONE | None | FAIL |
| 10 | auth-service token refresh race condit... | Fallback root cause: LLM Gateway call failed | NONE | NONE | None | FAIL |

## Scoring Methodology

Scoring uses a **deterministic mechanism rubric** per scenario.
**Keyword/substring overlap alone is NOT sufficient** for a PASS.
A case PASSES only when ALL of the following hold:

1. At least one `primary_component` appears in `cause_summary` or `confidence_rationale`.
2. At least one `causal_mechanism` appears in `cause_summary` or `confidence_rationale`.
3. No `hallucination_check` term dominates the first 120 chars of `cause_summary`.

## Release Gate Status

> WARNING: NOT RELEASE ELIGIBLE -- pilot run (n=10).
> Release gate requires n>=50 independently authored,
> stratified, and peer-reviewed cases per docs/evaluation-methodology.md S2.

This number MUST NOT be reported as the same metric as Orchestration Certification
(which uses mocked LLM boundaries and validates state-machine wiring,
not LLM diagnostic accuracy).