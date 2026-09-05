# Deployment

The **live lab** on NKP is GitOps, not a hand `kubectl apply`. See
[`gitops-nkp-pipeline.md`](gitops-nkp-pipeline.md) and
[`../deploy/gitops/README.md`](../deploy/gitops/README.md). Do not apply
`cv-lab/deploy/k8s/` into `db-project-002`.

Three local / legacy ways to run the app, from easiest to most involved. For
the full step-by-step hand-apply Kubernetes guide (including a registry-free
ConfigMap path), see [`../cv-lab/DEPLOYMENT.md`](../cv-lab/DEPLOYMENT.md).

## 1. Docker Compose (local / demo)

Brings up the backend plus a MinIO object store.

```bash
cd cv-lab/deploy
docker compose up --build
# open http://localhost:8000
```

Stop with `Ctrl+C`, then `docker compose down`. To run CPU-only is the default;
the compose file sets `DEVICE=cpu`.

## 2. Single container

Build the image and run it with local-disk storage (no external services):

```bash
docker build -f cv-lab/backend/Dockerfile -t cvlab-retail:0.1.0 cv-lab
docker run --rm -p 8000:8000 \
  -e STORAGE_BACKEND=local \
  cvlab-retail:0.1.0
# open http://localhost:8000
```

Add `-e NAI_BASE_URL=... -e NAI_API_KEY=... -e NAI_MODEL=...` to enable the LLM.
For GPU, use an NVIDIA runtime (`--gpus all`) and an image with CUDA PyTorch (see
the GPU manifest), and set `DEVICE=cuda:0`.

## 3. Kubernetes (legacy hand-apply)

These manifests are **not** the live `db-project-002` path. They stay as a
reference for registry-free or GPU experiments. Live delivery is
[`gitops-nkp-pipeline.md`](gitops-nkp-pipeline.md).

Manifests live in `cv-lab/deploy/k8s/`:

| File | Purpose |
|---|---|
| `namespace.yaml` | Namespace |
| `deployment-cpu.yaml` | All-in-one **CPU** deploy (registry-free; deps on a PVC) |
| `deployment-gpu.yaml` | All-in-one **GPU** deploy (CUDA PyTorch image) |
| `backend-deployment.yaml` + `backend-service.yaml` | Image-based deploy + Service |
| `ingress.yaml` | Ingress (edit host + ingress class) |
| `deps-pvc.yaml` | Dependency/model cache volume |
| `obc.yaml` | Object Bucket Claim (S3 storage option) |
| `nai-secret.example.yaml` | LLM credentials Secret (copy → `nai-secret.yaml`) |
| `objects-secret.example.yaml` | S3 credentials Secret (copy → `objects-secret.yaml`) |

**Before applying, edit these placeholders:**

- Container image → your registry (e.g. `ghcr.io/<your-org>/cvlab-retail:0.1.0`).
- `storageClassName` → a ReadWriteOnce class on your cluster (`kubectl get sc`).
- `ingressClassName` and the ingress `host` → your cluster's values.
- GPU `nodeSelector` → your GPU model, or remove it.

**Quick CPU path (registry-free):**

```bash
kubectl apply -f cv-lab/deploy/k8s/deployment-cpu.yaml
# deliver the source as a ConfigMap tarball (see header of that file)
tar -czf cvlab-src.tgz -C cv-lab backend frontend
kubectl -n cv-lab-cpu-only create configmap cvlab-src --from-file=cvlab-src.tgz=cvlab-src.tgz
kubectl -n cv-lab-cpu-only rollout status deploy/cv-lab --timeout=900s
```

**Create the secrets (don't commit the filled-in copies):**

```bash
kubectl -n <namespace> create secret generic nai-credentials \
  --from-literal=NAI_BASE_URL='https://your-llm-endpoint/v1' \
  --from-literal=NAI_API_KEY='<api-key>' \
  --from-literal=NAI_MODEL='<model-name>'
```

Health check once running: `GET /healthz` returns `{"status":"ok",...}`; the LLM
layer check is `GET /api/agent/ping`.

## Verifying a build

A quick end-to-end smoke test (synthesizes a shelf video, runs UC-2, exercises
the agent chain and shift report) is included:

```bash
cd cv-lab && python e2e_agent_test.py     # requires the server running on :8000
```

A lighter import/analyzer self-check:

```bash
cd cv-lab && python selftest.py
```

## CI / publishing images

The repo ships GitHub Actions workflows under `.github/workflows/`:

- `ci.yml` — installs deps and runs the import self-check on each push/PR.
- `secret-scan.yml` — scans the tree for accidentally committed secrets.
- `publish-cvlab.yml` — builds `linux/amd64`, pushes to GHCR, and writes the
  immutable `sha-<commit>` tag into the GitOps overlay.
