# CV Lab — Manual Kubernetes Deployment Guide

Exact, copy-paste commands to deploy the Retail-Supermarket-Grocery CV Live-Analysis app to a
Kubernetes (NKP) cluster **by hand**, with no CI/CD and no container registry.

The app is a single FastAPI backend that also serves the static frontend. It
needs:

- An S3-compatible bucket (Nutanix Objects) for uploaded videos.
- A persistent volume for the pip dependency cache + YOLO model weights.
- An ingress (Traefik on NKP) that proxies HTTP **and** WebSockets.

There are two deployment paths:

- **Path A — Registry-free (recommended for the lab).** Runs on the stock
  `python:3.12` image; the app source is shipped as a ConfigMap tarball and
  dependencies are pip-installed once onto a PVC. No Docker build, no registry.
- **Path B — Image-based (production).** Build the Dockerfile, push to a
  registry, and deploy that image. GPU-ready.

All commands assume you run them from the repo root
(the project working directory) and that the manifests live in `cv-lab/deploy/k8s/`.

---

## 0. Prerequisites

```bash
# Tools
kubectl version --client
tar --version            # bsdtar on Windows/macOS is fine

# Point kubectl at the target cluster, then confirm you can reach it
kubectl config current-context
kubectl get nodes
```

You also need a working **StorageClass** for volumes and (for Path A) an
**ObjectBucket** provisioner. Check what your cluster offers:

```bash
kubectl get storageclass
# Expect something like:
#   nutanix-volume      (RWO block volumes)         -> used by the deps PVC
#   dkp-object-store    (ObjectBucketClaim / S3)    -> used by the OBC
```

If your class names differ, edit `cv-lab/deploy/k8s/deps-pvc.yaml` and
`cv-lab/deploy/k8s/obc.yaml` accordingly before applying.

---

## 1. Namespace

```bash
kubectl apply -f cv-lab/deploy/k8s/namespace.yaml
# namespace/retail-supermarket-grocery-cv created
```

Everything below lives in the `retail-supermarket-grocery-cv` namespace.

---

## 2. Object storage (S3 bucket + credentials)

### Option 2a — ObjectBucketClaim (in-cluster Ceph/Objects)

```bash
kubectl apply -f cv-lab/deploy/k8s/obc.yaml

# Wait until the claim is Bound
kubectl -n retail-supermarket-grocery-cv get objectbucketclaim retail-supermarket-grocery-cv-bucket -w
```

This auto-creates, in the `retail-supermarket-grocery-cv` namespace:

- `ConfigMap/retail-supermarket-grocery-cv-bucket` → `BUCKET_HOST`, `BUCKET_PORT`, `BUCKET_NAME`
- `Secret/retail-supermarket-grocery-cv-bucket` → `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`

The Path A deployment reads exactly these names, so nothing else to wire up.

Verify:

```bash
kubectl -n retail-supermarket-grocery-cv get configmap retail-supermarket-grocery-cv-bucket -o yaml
kubectl -n retail-supermarket-grocery-cv get secret    retail-supermarket-grocery-cv-bucket -o yaml
```

### Option 2b — External Nutanix Objects bucket (manual secret)

If you are pointing at an existing Objects store instead of an OBC, create the
credentials secret yourself and set the S3 env vars on the Deployment manually:

```bash
kubectl -n retail-supermarket-grocery-cv create secret generic objects-credentials \
  --from-literal=S3_ACCESS_KEY='<access-key>' \
  --from-literal=S3_SECRET_KEY='<secret-key>'
```

(See `cv-lab/deploy/k8s/objects-secret.example.yaml` and the env block in
`cv-lab/deploy/k8s/backend-deployment.yaml` for the variable names.)

### Option 2c — NAI credentials (agentic ops)

The agentic-ops layer (incident-response agent + shift report) calls an
OpenAI-compatible LLM endpoint (e.g. Nutanix Enterprise AI / NAI, vLLM, Ollama,
OpenAI). Both deployment paths read the endpoint and API key from a
`nai-credentials` Secret — the key must never ride in the source ConfigMap (the
tarball excludes `backend/.env` for this reason):

```bash
kubectl -n retail-supermarket-grocery-cv create secret generic nai-credentials \
  --from-literal=NAI_BASE_URL='https://your-llm-endpoint/v1' \
  --from-literal=NAI_API_KEY='<api-key>' \
  --from-literal=NAI_MODEL='<model-name>'
```

(Or copy `cv-lab/deploy/k8s/nai-secret.example.yaml` to `nai-secret.yaml`,
fill in the key, and `kubectl apply -f` it.)

Pre-flight check once the pod is up: `GET /api/agent/ping` must return
`{"ok": true, ...}`.

---

## 3. Dependency / model cache volume (Path A)

```bash
kubectl apply -f cv-lab/deploy/k8s/deps-pvc.yaml

kubectl -n retail-supermarket-grocery-cv get pvc cvlab-deps
# STATUS should be Bound (or Pending until the first pod mounts it,
# depending on the StorageClass volumeBindingMode)
```

This 8Gi RWO volume keeps the (slow) pip install + downloaded YOLO weights, so
restarts are fast. Skip this step for Path B.

---

# Path A — Registry-free deployment (recommended)

## A.4 Package the application source as a ConfigMap

The init container extracts this tarball into the pod, so the ConfigMap **is**
your deploy artifact. Re-run this step every time you change the code.

```bash
# Build the tarball (backend + frontend only).
# IMPORTANT: --exclude backend/.env keeps the NAI API key out of the ConfigMap;
# in-cluster the key comes from the nai-credentials Secret instead.
tar -czf cvlab-src.tgz --exclude backend/.env --exclude "backend/data" --exclude "__pycache__" -C cv-lab backend frontend

# Create/refresh the ConfigMap idempotently
kubectl -n retail-supermarket-grocery-cv create configmap cvlab-src \
  --from-file=cvlab-src.tgz=cvlab-src.tgz \
  --dry-run=client -o yaml | kubectl apply -f -
```

> Note: a ConfigMap has a ~1 MiB limit. The tarball here is well under that
> (~50 KiB). If it ever grows past the limit, switch to Path B or bake the
> source into an image.

## A.5 Deploy the app

```bash
kubectl apply -f cv-lab/deploy/k8s/deployment-incluster.yaml
kubectl apply -f cv-lab/deploy/k8s/backend-service.yaml
```

The first start runs the init container, which:

1. extracts the source,
2. pip-installs dependencies onto the PVC (a few minutes — **first run only**),
3. forces headless OpenCV (no system GL libs needed),
4. downloads the YOLOv8 weights.

Watch it come up:

```bash
# Follow the init container (dependency install) on first deploy
kubectl -n retail-supermarket-grocery-cv logs -f deploy/cv-lab -c setup

# Then the app container
kubectl -n retail-supermarket-grocery-cv logs -f deploy/cv-lab -c cv-lab

# Wait for the rollout to report Ready (allow up to ~10 min on first run)
kubectl -n retail-supermarket-grocery-cv rollout status deploy/cv-lab --timeout=900s
```

Jump to [Section 6 — Ingress](#6-ingress-external-access).

---

# Path B — Image-based deployment (production)

## B.4 Build and push the image

```bash
# Build from the backend Dockerfile (frontend is copied in by the Dockerfile)
docker build -t <registry>/retail-supermarket-grocery-cv-lab:0.1.0 cv-lab/backend

# Push to a registry the cluster can pull from
docker push <registry>/retail-supermarket-grocery-cv-lab:0.1.0
```

## B.5 Set the image and deploy

Edit `cv-lab/deploy/k8s/backend-deployment.yaml` and replace
`image: ghcr.io/your-org/cvlab-retail:0.1.0` with your pushed image. Confirm the
S3 env vars / `objects-credentials` secret (Section 2b) are correct, then:

```bash
kubectl apply -f cv-lab/deploy/k8s/backend-deployment.yaml
kubectl apply -f cv-lab/deploy/k8s/backend-service.yaml
kubectl -n retail-supermarket-grocery-cv rollout status deploy/cv-lab --timeout=300s
```

> The sample manifest requests `nvidia.com/gpu: 1` (needs the NVIDIA GPU
> Operator). Remove that limit and set `DEVICE=cpu` to run CPU-only.

---

## 6. Ingress (external access)

Edit the host in `cv-lab/deploy/k8s/ingress.yaml` to match your cluster's
domain, confirm the `ingressClassName` (e.g. `nginx` or `traefik`), then:

```bash
kubectl apply -f cv-lab/deploy/k8s/ingress.yaml
kubectl -n retail-supermarket-grocery-cv get ingress cv-lab
```

Traefik proxies WebSockets transparently, so `/ws/analyze` works with no extra
annotations.

---

## 7. Verify

```bash
# Pod is Running and Ready (1/1)
kubectl -n retail-supermarket-grocery-cv get pods -o wide

# Health endpoint via the service (port-forward as a quick check)
kubectl -n retail-supermarket-grocery-cv port-forward deploy/cv-lab 8000:8000 &
curl -s http://localhost:8000/healthz        # -> {"status":"ok"} (or similar)
curl -s http://localhost:8000/api/usecases   # -> list of 20 use cases
kill %1

# Via the ingress (replace with your host)
curl -sk -o /dev/null -w "%{http_code}\n" https://cv-lab.<your-domain>/
```

Open `https://cv-lab.<your-domain>/` for the live analysis page and
`/library.html` for the use-case portal.

---

## 8. Updating the app

### Path A (code change)

```bash
tar -czf cvlab-src.tgz --exclude backend/.env --exclude "backend/data" --exclude "__pycache__" -C cv-lab backend frontend
kubectl -n retail-supermarket-grocery-cv create configmap cvlab-src \
  --from-file=cvlab-src.tgz=cvlab-src.tgz \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n retail-supermarket-grocery-cv rollout restart deploy/cv-lab
kubectl -n retail-supermarket-grocery-cv rollout status  deploy/cv-lab --timeout=300s
```

Dependencies persist on the PVC, so restarts after the first deploy take well
under a minute.

### Path B (new image)

```bash
docker build -t <registry>/retail-supermarket-grocery-cv-lab:0.2.0 cv-lab/backend
docker push <registry>/retail-supermarket-grocery-cv-lab:0.2.0
kubectl -n retail-supermarket-grocery-cv set image deploy/cv-lab cv-lab=<registry>/retail-supermarket-grocery-cv-lab:0.2.0
kubectl -n retail-supermarket-grocery-cv rollout status deploy/cv-lab --timeout=300s
```

---

## 9. Troubleshooting

```bash
# Describe the pod for events (scheduling, image pulls, probe failures)
kubectl -n retail-supermarket-grocery-cv describe pod -l app=cv-lab

# Logs (init vs app container)
kubectl -n retail-supermarket-grocery-cv logs deploy/cv-lab -c setup     # dependency install
kubectl -n retail-supermarket-grocery-cv logs deploy/cv-lab -c cv-lab    # FastAPI / uvicorn

# Exec into the running pod
kubectl -n retail-supermarket-grocery-cv exec -it deploy/cv-lab -c cv-lab -- /bin/sh
```

Common issues:

- **Pod stuck `Pending`** — PVC not Bound or no node capacity. Check
  `kubectl -n retail-supermarket-grocery-cv get pvc` and `kubectl describe pod`.
- **First start slow / probe restarts** — the dependency install is running.
  The `startupProbe` allows ~10 min; tail the `setup` container logs.
- **`ImagePullBackOff` (Path B)** — the cluster can't reach your registry, or
  the image tag is wrong. Verify with `kubectl describe pod`.
- **Ingress 404 / 503** — wrong `ingressClassName` or host; the pod isn't Ready
  yet (no endpoints). Check `kubectl -n retail-supermarket-grocery-cv get endpoints cv-lab`.
- **Uploads fail** — S3 wiring is off. Confirm the `retail-supermarket-grocery-cv-bucket`
  ConfigMap/Secret (Path A) or the `objects-credentials` secret and S3 env
  (Path B).

---

## 10. Teardown

```bash
# Remove the app but keep the data/bucket
kubectl -n retail-supermarket-grocery-cv delete -f cv-lab/deploy/k8s/ingress.yaml
kubectl -n retail-supermarket-grocery-cv delete -f cv-lab/deploy/k8s/backend-service.yaml
kubectl -n retail-supermarket-grocery-cv delete -f cv-lab/deploy/k8s/deployment-incluster.yaml
kubectl -n retail-supermarket-grocery-cv delete configmap cvlab-src

# Full cleanup (also deletes the bucket, its data, and the deps cache)
kubectl delete namespace retail-supermarket-grocery-cv
```

---

## Quick reference — full Path A deploy from scratch

```bash
kubectl apply -f cv-lab/deploy/k8s/namespace.yaml
kubectl apply -f cv-lab/deploy/k8s/obc.yaml
kubectl -n retail-supermarket-grocery-cv get objectbucketclaim retail-supermarket-grocery-cv-bucket -w   # wait: Bound
kubectl apply -f cv-lab/deploy/k8s/deps-pvc.yaml

tar -czf cvlab-src.tgz --exclude backend/.env --exclude "backend/data" --exclude "__pycache__" -C cv-lab backend frontend
kubectl -n retail-supermarket-grocery-cv create configmap cvlab-src \
  --from-file=cvlab-src.tgz=cvlab-src.tgz \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f cv-lab/deploy/k8s/deployment-incluster.yaml
kubectl apply -f cv-lab/deploy/k8s/backend-service.yaml
kubectl apply -f cv-lab/deploy/k8s/ingress.yaml          # edit host first
kubectl -n retail-supermarket-grocery-cv rollout status deploy/cv-lab --timeout=900s
```
