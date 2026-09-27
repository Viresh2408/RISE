# Infrastructure & Operations

Terraform, Kubernetes, and n8n workflow manifests for RISE.

## ⚠️ Status: what is real vs. reference scaffolding

This directory mixes **working** artifacts with **reference scaffolding** — illustrative
structure that was never provisioned against a live account/cluster. Treat anything marked
_reference scaffolding_ as a documented design placeholder, **not** deployable IaC.

| Path | Status | Notes |
|------|--------|-------|
| `terraform/envs/dev/` | Working (plan-able) | Full `main.tf` / `variables.tf` / `providers.tf` / `outputs.tf` + `terraform.tfvars`. |
| `terraform/envs/prod/` | Working (plan-able) | Full module wiring; no `terraform.tfvars` committed (supply your own). |
| `terraform/modules/{vpc,eks,iam_roles}/` | Working (plan-able) | Reusable modules consumed by dev/prod. |
| `terraform/envs/staging/` | **Reference scaffolding** | README only — no `.tf`. Clone `dev/` to instantiate. |
| `k8s/overlays/prod/` | Working manifests | `deployment.yaml`, `canary-ingress.yaml`, `kustomization.yaml`. |
| `k8s/base/` | **Reference scaffolding** | README only — no base manifests. The prod overlay is currently self-contained rather than a true Kustomize base+overlay. |
| `k8s/helm/` | **Reference scaffolding** | `values-prod.yaml` only — no `Chart.yaml` / `templates/`. `helm upgrade` against this path will not work as-is. |
| `k8s/external-secrets/` | **Reference scaffolding** | README only. |
| `monitoring/` | Working config | Prometheus alerts, Grafana dashboards (JSON), Langfuse config. |
| `n8n-workflows/` | **Reference scaffolding** | READMEs only — no exported workflow JSON. |

## CI/CD interaction

- `.github/workflows/ci.yml` and `security-scan.yml` are **real gates** (pytest, pnpm
  build, Trivy, Semgrep).
- `.github/workflows/deploy-staging.yml` runs a real pytest gate, then a **placeholder**
  deploy step (see the file header) — because the staging cluster/Helm chart above is
  reference scaffolding.
- `.github/workflows/deploy-prod.yml` invokes `helm upgrade ... infra/k8s/helm`, which
  depends on a complete Helm chart that does **not** exist here yet — this workflow is
  aspirational until `k8s/helm/` gains a `Chart.yaml` + `templates/`.

To turn any reference-scaffolding item into working IaC, finish the noted missing files
and validate against a real account/cluster before relying on it.
