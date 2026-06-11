# Configuration reference

All settings are environment variables (read by `cv-lab/backend/app/config.py`).
For local development, copy [`../.env.example`](../.env.example) to
`cv-lab/backend/.env` and edit it. In Kubernetes, set them via the Deployment
`env:` block and `Secret` objects.

> Never commit a real `.env` or filled-in secret file — they are gitignored.

## Application

| Variable | Default | Description |
|---|---|---|
| `APP_NAME` | `Retail-Supermarket-Grocery CV Live-Analysis` | Shown in the UI/title. |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins. Restrict in production. |
| `FRONTEND_DIR` | `cv-lab/frontend` | Static files to serve; unset to run API-only. |

## Inference device

| Variable | Default | Description |
|---|---|---|
| `DEVICE` | `auto` | `auto` picks CUDA if available, else CPU. Force with `cpu` or `cuda:0`. |

## Models

| Variable | Default | Description |
|---|---|---|
| `MODELS_DIR` | `models` | Where model weights live / are downloaded. |
| `PERSON_MODEL` | `yolov8n.pt` | YOLOv8 weights (COCO). Person class = 0. |
| `EMPTY_SHELF_MODEL` | _(blank)_ | Optional custom `.pt` for UC-2 (out-of-stock). |
| `SPILL_MODEL` | _(blank)_ | Optional custom `.pt` for UC-16 (spill). |

> **Swapping the detector / AGPL note:** YOLOv8 is AGPL-3.0, which is why this
> project is AGPL-3.0. To use a different license, replace the YOLOv8 dependency
> (`ultralytics`) and the loader in `core/models.py` with a model under terms you
> can accept, and remove `ultralytics` from `requirements.txt`.

## Object storage (S3-compatible)

Used when `STORAGE_BACKEND` is `s3` (or `auto` and S3 is reachable). Works with
Nutanix Objects, MinIO, AWS S3, etc.

| Variable | Default | Description |
|---|---|---|
| `STORAGE_BACKEND` | `auto` | `auto` / `s3` / `local`. Use `local` for the simplest setup. |
| `LOCAL_STORAGE_DIR` | `data` | Directory for the local backend. |
| `S3_ENDPOINT` | `http://localhost:9000` | S3 endpoint URL. |
| `S3_REGION` | `us-east-1` | S3 region. |
| `S3_BUCKET` | `retail-supermarket-grocery-cv` | Bucket name. |
| `S3_ACCESS_KEY` | `minioadmin` | Access key (use a Secret in production). |
| `S3_SECRET_KEY` | `minioadmin` | Secret key (use a Secret in production). |
| `S3_USE_PATH_STYLE` | `true` | Required by MinIO and Nutanix Objects. |
| `S3_VERIFY_SSL` | `false` | Set `true` with valid TLS certs. |

## LLM endpoint (agentic ops — optional)

Any OpenAI-compatible chat-completions API. Leave `NAI_BASE_URL` blank to disable
the LLM and use the deterministic local fallback.

| Variable | Default | Description |
|---|---|---|
| `NAI_BASE_URL` | _(blank)_ | e.g. `https://your-llm-endpoint/v1`. Blank = disabled. |
| `NAI_API_KEY` | _(blank)_ | Bearer token. Store as a Secret. |
| `NAI_MODEL` | `llama3-1-8b` | Model name the endpoint serves. |
| `NAI_VERIFY_SSL` | `false` | TLS verification toggle. |
| `NAI_TIMEOUT_S` | `120` | Per-request timeout (seconds). |
| `REPORT_DEADLINE_S` | `30` | Cap before the shift report falls back to local briefing. |

> The `NAI_*` names are historical (the reference deployment used Nutanix
> Enterprise AI). They accept **any** OpenAI-compatible endpoint.

## Agentic ops behavior

| Variable | Default | Description |
|---|---|---|
| `STORE_NAME` | `Demo Grocery — Main St` | Store name used in events/reports. |
| `AGENT_DETECT_FRAMES` | `10` | Sustained alert frames before an event fires. |
| `AGENT_CLEAR_FRAMES` | `24` | Sustained OK frames before a clearance fires. |
| `AGENT_MAX_STEPS` | `8` | Tool-use loop cap per agent run. |

## Streaming / performance

| Variable | Default | Description |
|---|---|---|
| `TARGET_FPS` | `12` | Server-side stream throttle. Lower it on CPU. |
| `JPEG_QUALITY` | `70` | JPEG quality (1–100) for streamed frames. |
| `MAX_STREAM_WIDTH` | `960` | Downscale wider frames before encoding. |
| `MAX_UPLOAD_MB` | `200` | Maximum upload size. |
| `OPENCV_FFMPEG_CAPTURE_OPTIONS` | _(unset)_ | e.g. `rtsp_transport;tcp\|stimeout;8000000` for RTSP. |

## Tips

- **Lowest-friction local run:** `STORAGE_BACKEND=local`, no LLM. Everything
  works offline.
- **CPU performance:** reduce `TARGET_FPS` (e.g. 6–8) and `MAX_STREAM_WIDTH`
  (e.g. 640).
- **Production:** restrict `CORS_ORIGINS`, enable TLS verification, and supply
  all keys via Kubernetes Secrets.
