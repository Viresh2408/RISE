# Policy Tests

Unit test suite for the OPA Rego rules in `policies/`.

`policy_test.rego` covers `tool_allowlist`, `risk_tiers`, and `approval_rules`
(default-deny, unknown-tool denial, risk classification, and approval gating).

Run with [OPA](https://www.openpolicyagent.org/docs/latest/#running-opa):

```bash
opa test policies/ -v
```

These are Rego tests and are **not** collected by pytest.
