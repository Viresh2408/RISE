# K8s Kustomize Base

Base Kubernetes resource manifests.

> **⚠️ Reference scaffolding — not implemented.** No base manifests exist here yet; the
> `../overlays/prod/` manifests are currently self-contained. See `infra/README.md` for the
> full status table. To make this a real Kustomize base, add the shared Deployment/Service/
> ConfigMap manifests and a `kustomization.yaml`, then have the overlays reference them.
