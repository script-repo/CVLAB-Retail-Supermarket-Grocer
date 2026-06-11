# Retail-Supermarket-Grocery CV Live-Analysis App

Live computer-vision analysis for Retail-Supermarket-Grocery retail use cases. Upload a looping
video, pick a use case, and the backend streams annotated frames + live metrics
to the browser over a WebSocket. Videos are saved to object storage (Nutanix
Objects / S3) for reuse. Styled with the shared Retail-Supermarket-Grocery design tokens so it
matches the use-case library (`../cv-portal`).

## Implemented use cases

- **UC-2 — Real-Time Shelf Out-of-Stock Detection** (`shelf-vision`): per-zone shelf occupancy + replenishment alerts. Draw shelf zones on the frame.
- **UC-6 — Queue Length & Wait-Time Monitoring** (`people-tracking`): person detection + tracking in a queue zone, wait-time estimate, "open another lane" alert.
- **UC-7 — Customer Traffic Heat Maps & Flow Analytics** (`people-tracking`): accumulating heatmap + movement traces + unique-visitor count.
- **UC-16 — Spill & Hazard Detection** (`task-ops`): floor-region spill detection with an unattended dwell timer.

## Agentic ops (NAI)

CV detections drive an autonomous store-operations agent served by **NAI
(Nutanix Enterprise AI)**:

- Every analyzer's `status: ok|alert` stream is watched for *sustained*
  transitions; these become discrete events (with frame snapshots) on an
  internal event bus — works for all 20 use cases with no analyzer changes.
- On a detection, an agent run starts against the NAI OpenAI-compatible
  endpoint (`llama3-1-8b`): it verifies via live metrics, checks the (mock)
  staff roster, opens a work order, and notifies the assignee. On clearance it
  verifies and resolves the work order. Every step streams to the UI over
  `/ws/agent`.
- **Shift report**: one click turns the session's events + work orders into a
  manager briefing written by NAI.
- Guardrails: mode-restricted toolsets, server-side assignee validation, retry
  on NAI timeouts, and a deterministic fallback so a live demo never stalls.
- Agentic state (events, snapshots, work orders, notifications) persists to
  SQLite under `LOCAL_STORAGE_DIR`, so a pod restart keeps the morning's log.

Configure via `backend/.env` (local) or the `nai-credentials` Secret
(in-cluster): `NAI_BASE_URL`, `NAI_API_KEY`, `NAI_MODEL`, `NAI_VERIFY_SSL`.
Pre-flight: `GET /api/agent/ping`. End-to-end check: `python e2e_agent_test.py`
with the server running.

## Settings, multi-view, GPU attribution

- The **gear icon** (top right) opens global settings, persisted in
  `localStorage`: hide/show individual use cases, **advanced GPU stats**
  (stacked per-use-case utilization bar — hover a segment for the use case and
  its share), and **multi-view**.
- **Multi-view** turns the library page into a CCTV wall: every visible use
  case streams live simultaneously (unlimited tiles; per-tile FPS adapts to
  tile count). Each tile replays the last video used with that use case.
- `/api/gpu` reports per-use-case processing shares (`streams`): the driver
  only reports utilization per process, so utilization is apportioned by each
  stream's measured share of inference time.

All 20 analyzers run GPU inference: the five formerly heuristic-only use cases
(UC-8/11/12/15/18) now include a YOLO person/product pass that feeds their
logic and overlays.

## Architecture

```
Browser (Retail-Supermarket-Grocery theme)
  | REST  /api/videos            upload / list / get / delete  ──► Object storage (S3)
  | WS    /ws/analyze            annotated JPEG frames + JSON metrics
  v
FastAPI backend
  ├── core/pipeline.py     decode (OpenCV) → analyze → throttle → JPEG encode
  ├── core/models.py       Ultralytics YOLO loader (COCO + optional weights)
  ├── core/tracking.py     supervision ByteTrack wrapper
  ├── core/storage.py      S3 (Nutanix Objects / MinIO) with local fallback
  └── usecases/*.py        one pluggable analyzer per use case
```

## Tech stack

- Backend: FastAPI, Uvicorn, WebSockets
- CV: Ultralytics YOLOv8 (COCO person), `supervision` (zones, ByteTrack, traces), OpenCV, NumPy
- Storage: boto3 → Nutanix Objects / MinIO (S3-compatible)

## Run locally (Docker)

The easiest path brings up MinIO (S3 stand-in) + the app:

```bash
cd cv-lab/deploy
docker compose up --build
# open http://localhost:8000
```

## Run locally (Python, no Docker)

```bash
cd cv-lab/backend
python -m venv .venv && . .venv/Scripts/activate    # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Use local-disk storage (no S3 needed):
$env:STORAGE_BACKEND="local"      # PowerShell  (export STORAGE_BACKEND=local on bash)
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000
```

CPU works (slower). With an NVIDIA GPU + CUDA torch, set `DEVICE=cuda:0`.

## Configuration (env vars)

- `STORAGE_BACKEND` — `auto` | `s3` | `local` (default `auto`)
- `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_USE_PATH_STYLE`, `S3_VERIFY_SSL`
- `DEVICE` — `auto` | `cpu` | `cuda:0`
- `TARGET_FPS`, `JPEG_QUALITY`, `MAX_STREAM_WIDTH`, `MAX_UPLOAD_MB`
- `PERSON_MODEL` (default `yolov8n.pt`), `EMPTY_SHELF_MODEL`, `SPILL_MODEL`

### Optional pretrained weights (UC-2 / UC-16)

UC-2 and UC-16 ship with heuristic fallbacks that need no weights. For stronger
detection, drop a YOLO `.pt` into `backend/models/` and point the env var at it:

- UC-2 empty shelf: e.g. Roboflow Universe [empty-slots-in-shelves](https://universe.roboflow.com/fyp-qtd0e/empty-slots-in-shelves/model/3) → `EMPTY_SHELF_MODEL=empty-shelf.pt`
- UC-16 spill: e.g. Roboflow Universe [wet-floor](https://universe.roboflow.com/frc-5881/wet-floor-nhjwl/dataset/1) → `SPILL_MODEL=spill.pt`

Export the dataset in YOLOv8 format and train, or download the model weights,
then place the resulting `.pt` in `backend/models/`. Self-hosting keeps the demo
fully offline (no external API calls).

## Deploy to Kubernetes

For a registry-free path (deliver source via a ConfigMap) plus full CPU and GPU
walkthroughs, see [DEPLOYMENT.md](DEPLOYMENT.md). Image-based quickstart:

```bash
cd cv-lab/deploy/k8s
# 1. Build & push the image, update image: in backend-deployment.yaml
docker build -f ../../backend/Dockerfile -t ghcr.io/your-org/cvlab-retail:0.1.0 ../..
docker push ghcr.io/your-org/cvlab-retail:0.1.0
# 2. Create namespace + object-store credentials
kubectl apply -f namespace.yaml
cp objects-secret.example.yaml objects-secret.yaml   # fill in real keys
kubectl apply -f objects-secret.yaml
# 3. Deploy
kubectl apply -f backend-deployment.yaml -f backend-service.yaml -f ingress.yaml
```

The Deployment requests `nvidia.com/gpu: 1` (needs the NVIDIA GPU Operator).
Remove that limit to run CPU-only. Most ingress controllers (NGINX, Traefik)
proxy the WebSocket without extra configuration.

## Adding another use case

Create `backend/app/usecases/ucNN_name.py`, subclass `UseCaseAnalyzer`,
implement `setup()` and `process_frame()`, decorate with `@register`, and import
it in `usecases/__init__.py`. It then appears automatically in `/api/usecases`
and the UI.
