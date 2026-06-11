# Getting started

This guide is written for **all skill levels**. If you have never run a Python
web app before, follow the Docker path — it is the simplest. If a term is
unfamiliar, check the [Glossary](GLOSSARY.md).

## What you'll end up with

A web page at `http://localhost:8000` where you pick a retail computer-vision
use case, give it a video (a file, your webcam, or a camera stream), press
**Start**, and watch the system draw boxes/zones/heatmaps on the video and show
live numbers.

## Prerequisites

Pick one of the two paths below.

| Path | You need | Best for |
|---|---|---|
| **A. Docker** | [Docker Desktop](https://www.docker.com/products/docker-desktop/) | The quickest start; no Python setup |
| **B. Python** | Python 3.11+ and `pip` | Developing / changing the code |

A webcam is optional. A GPU is optional (everything runs on CPU, just slower).

---

## Path A — Run with Docker (recommended)

1. Install Docker Desktop and make sure it is running.
2. Open a terminal in the project folder and run:

   ```bash
   cd cv-lab/deploy
   docker compose up --build
   ```

   The first build downloads dependencies and can take several minutes.
3. When you see the backend logs settle, open **http://localhost:8000** in your
   browser.
4. This also starts a local **MinIO** object store (an S3 stand-in) at
   `http://localhost:9001` (login `minioadmin` / `minioadmin`) — you usually do
   not need to touch it.

To stop: press `Ctrl+C`, then `docker compose down`.

---

## Path B — Run with Python (no Docker)

1. Open a terminal in `cv-lab/backend`.
2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # macOS / Linux:
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Use simple local-disk storage so you don't need S3/MinIO:

   ```bash
   # Windows PowerShell:
   $env:STORAGE_BACKEND="local"
   # macOS / Linux:
   export STORAGE_BACKEND=local
   ```

5. Start the server:

   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

6. Open **http://localhost:8000**.

> The first analysis run downloads the YOLOv8 model weights (~6 MB) automatically.

---

## Your first analysis

1. **Pick a use case** in the left panel (try **UC-6 Queue Length** or
   **UC-2 Shelf Out-of-Stock**).
2. **Choose a source** at the bottom-left:
   - **Video** — upload an `.mp4`, or pick one you uploaded before.
   - **Camera** — use your laptop webcam.
   - **Stream** — paste an RTSP or HTTP (MJPEG) URL.
3. If the use case shows a **"draw zone"** hint, click on the video to draw a
   polygon (e.g. the checkout queue area). Zones are saved per use case.
4. Adjust any **sliders** (thresholds, limits) — these update live.
5. Click **Start**. Annotated frames stream into the main view and metrics
   update on the right.

## Turning on the agentic-ops layer (optional)

Out of the box the agent panel runs on built-in deterministic logic. To use a
real LLM (for richer reasoning and the natural-language shift report), set an
OpenAI-compatible endpoint — see [AGENTIC_OPS.md](AGENTIC_OPS.md) and
[CONFIGURATION.md](CONFIGURATION.md). You can leave it off entirely; the demo
still works.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `http://localhost:8000` won't load | Confirm the server/compose is still running; check the terminal for errors. |
| Port 8000 already in use | Run on another port: `uvicorn app.main:app --port 8080` (or change the compose port mapping). |
| Webcam doesn't appear | Browsers only allow camera access on `localhost` or HTTPS; grant the permission prompt. |
| "video_id is required" | You selected the **Video** source but didn't pick/upload a video. |
| Analysis is very slow | You're on CPU. Lower `TARGET_FPS`/`MAX_STREAM_WIDTH`, use a smaller video, or run on a GPU (`DEVICE=cuda:0`). |
| RTSP stream won't open | Verify the URL works in VLC; some cameras need credentials in the URL. |
| Model download fails | Check internet access; or pre-place `yolov8n.pt` in `cv-lab/backend/models/`. |

Still stuck? Open an issue (see [../SECURITY.md](../SECURITY.md) before pasting
logs — don't include secrets).
