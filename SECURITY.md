# Security Policy

## Vulnerability Disclosure
If you discover a security vulnerability within RISE, please do not open a public issue. Email security details directly to security@rise.local.

## Credential & Policy Integrity
- All secret values must be kept out of version control and managed via AWS Secrets Manager or local `.env` files.
- Automated actions executed by agents are governed strictly by Open Policy Agent (OPA) policy rules in `policies/`.
