# Live RCA Benchmark Report

> **PILOT -- NOT RELEASE ELIGIBLE**  
> n=10 -- release gate requires n>=50

| Field | Value |
|:---|:---|
| Run ID | `7ac5decf` |
| Timestamp (UTC) | 2026-09-25T18:34:31.558834+00:00 |
| Provider | groq |
| Model | llama-3.3-70b-versatile |
| Git SHA | `e1f426e` |
| Dataset hash | `3419be85cf4c27fd` |
| Live | Yes |
| Release eligible | **No** -- pilot only |

## Results

**Mechanism accuracy: 0.0%** (0/10 passed)

| ID | Title | Cause Summary | Components | Mechanisms | Hallucination | Result |
|:--|:--|:--|:--|:--|:--|:--|
| 1 | payment-service high error rate -- 503... | Fallback root cause: LLM Gateway call failed | NONE | NONE | None | FAIL |
| 2 | payment-service memory leak causing OO... | Fallback root cause: LLM Gateway call failed | NONE | NONE | None | FAIL |
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