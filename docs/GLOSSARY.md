# Glossary

Plain-language definitions of terms used across this project — for readers of all
skill levels.

### Analyzer
A small Python file that implements one use case: it looks at each video frame
and returns the drawn-on frame plus some numbers. See
[ADDING_A_USE_CASE.md](ADDING_A_USE_CASE.md).

### Annotation / overlay
The boxes, zones, labels, and banners the app draws on top of the video to show
what it detected.

### Agentic ops
The optional layer that reacts to detections like a store operations assistant:
it opens work orders, sends notifications, and writes a shift report. See
[AGENTIC_OPS.md](AGENTIC_OPS.md).

### Bounding box
The rectangle drawn around a detected object or person.

### ByteTrack
A tracking algorithm that keeps a stable ID on each person/object across frames,
so we can measure things like dwell time. Provided via the `supervision` library.

### COCO
A common image dataset. The default YOLOv8 weights are trained on COCO, which
includes a "person" class (used by the people-tracking use cases).

### CORS
"Cross-Origin Resource Sharing" — a browser security setting controlling which
web origins may call the API. Configured with `CORS_ORIGINS`.

### CUDA
NVIDIA's GPU computing platform. With CUDA-enabled PyTorch and a GPU, inference
runs much faster (`DEVICE=cuda:0`).

### Detection
Finding objects/people in an image and where they are (as bounding boxes).

### Docker / Docker Compose
Tools that package and run the app in containers. Compose starts multiple
containers (here: the backend + a MinIO object store) with one command.

### Dwell time
How long a tracked person stays in a region — used for queue wait estimates and
product engagement.

### FastAPI
The Python web framework powering the backend (REST endpoints + WebSockets).

### Frame
A single still image from a video. Video is just many frames per second.

### FPS (frames per second)
How many frames are processed/shown each second. Lower `TARGET_FPS` to reduce CPU
load.

### GHCR
GitHub Container Registry — a place to publish Docker images
(`ghcr.io/<org>/<image>`).

### Heatmap
A color overlay showing where activity concentrates over time (hot = busy).

### Ingress
The Kubernetes object that exposes the app to the outside world at a hostname.

### Inference
Running a trained model on new data (here: running YOLOv8 on a frame to detect
things).

### JPEG
The compressed image format used to send each annotated frame to the browser.

### Kubernetes (k8s)
A platform for running containers across a cluster of machines. Manifests for it
live in `cv-lab/deploy/k8s/`.

### LLM (Large Language Model)
The AI model that powers the agent's reasoning and the shift report. Optional;
any OpenAI-compatible endpoint works (NAI, vLLM, Ollama, OpenAI).

### Manifest
A YAML file describing a Kubernetes object (Deployment, Service, Ingress, ...).

### MinIO
A lightweight, S3-compatible object store used locally to stand in for a
production store like Nutanix Objects.

### NAI (Nutanix Enterprise AI)
The LLM service used by the reference deployment. The `NAI_*` settings accept any
OpenAI-compatible endpoint, not just NAI.

### Object storage / S3
A way to store files (videos, thumbnails) by key in "buckets". This project uses
an S3-compatible API (boto3), or local disk as a fallback.

### OpenAI-compatible API
Any LLM server that speaks the same `/chat/completions` request/response format
as OpenAI, so the same client code works against many providers.

### OpenCV
A computer-vision library used to read video, draw overlays, and run lightweight
image heuristics.

### Planogram
A retailer's plan for how products should be arranged on a shelf. UC-3 checks
compliance against it.

### PVC (PersistentVolumeClaim)
A request for disk storage in Kubernetes, used here to cache dependencies/models
and store data.

### RTSP
A streaming protocol used by IP/CCTV cameras (`rtsp://...`). The app can also pull
HTTP MJPEG streams.

### Use case
One retail scenario the app demonstrates (e.g. queue monitoring). There are 20;
see [USE_CASES.md](USE_CASES.md).

### WebSocket
A persistent two-way browser↔server connection. Used to stream frames and metrics
(`/ws/analyze`) and agent events (`/ws/agent`).

### YOLOv8
The object-detection model (by Ultralytics) used for detection. It is licensed
**AGPL-3.0**, which is why this whole project is AGPL-3.0.

### Zone
A region you draw on the frame (a polygon) telling an analyzer where to look —
e.g. the checkout queue area.
