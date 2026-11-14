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
| `MODEL_FORMAT` | `auto` | Inference runtime. `auto` picks the fastest one for the hardware (below). Force with `pytorch`, `tensorrt`, `openvino` or `onnx`. |
| `MODEL_FP16` | _(blank)_ | Blank = FP16 on GPU, FP32 on CPU. `false` forces FP32 on GPU. FP16 is never used on CPU. |
| `MODEL_IMGSZ` | `640` | Model input size (also the size exported models are built for). |
| `EXPORT_DIR` | `<MODELS_DIR>/exported` | Cache for exported models. Put it on a persistent volume so exports survive restarts. |
| `MODEL_WARMUP` | `true` | Load (and, on first run, export) the COCO model in the background at startup. |

### How `MODEL_FORMAT=auto` chooses

| Hardware | Package present | Runtime used |
|---|---|---|
| NVIDIA GPU | `tensorrt` (`requirements-gpu.txt`) | **TensorRT engine, FP16** |
| NVIDIA GPU | — | PyTorch on CUDA, FP16 |
| CPU only | `openvino` (in `requirements.txt`) | **OpenVINO IR, FP32** |
| CPU only | `onnxruntime` + `onnx` | ONNX Runtime |
| CPU only | — | PyTorch |

- The export runs once from the `.pt` weights and is cached in `EXPORT_DIR`.
  OpenVINO takes seconds; a TensorRT engine takes a few minutes on first start.
- TensorRT engines only run on the GPU model and TensorRT version that built
  them. Both are in the cache file name, so moving to different hardware just
  builds a new engine.
- Any export or load error falls back to PyTorch on the same device and is
  logged, so a missing package can only make inference slower, never break it.
- `auto` only picks runtimes whose packages are already installed, so
  Ultralytics never pip-installs anything at runtime.
- `GET /api/gpu` reports the plan (`runtime`) and what each loaded model is
  using (`models`). The UI's accelerator panel shows the same information.
- Measured on a 4-core CPU (Ultralytics 8.4, 1280×720 frames, mean of 40):

  | Weights | PyTorch | OpenVINO |
  |---|---|---|
  | `yolov8n.pt` | 37 ms | 19 ms |
  | `yolo11n.pt` (default) | 40 ms | 22 ms |
  | `yolo26n.pt` | 42 ms | 22 ms |

  Detections match between runtimes. YOLO11n is more accurate than YOLOv8n
  (COCO mAP 39.5 vs 37.3) for about the same cost.

Install GPU extras with `pip install -r requirements.txt -r requirements-gpu.txt`,
or build the image with `--build-arg ACCEL=gpu`.

## Models

| Variable | Default | Description |
|---|---|---|
| `MODELS_DIR` | `models` | Where model weights live / are downloaded. |
| `PERSON_MODEL` | `yolo11n.pt` | YOLO weights (COCO). Person class = 0. Any Ultralytics detector works (e.g. `yolo26n.pt`, `yolo11s.pt`). |
| `EMPTY_SHELF_MODEL` | _(blank)_ | Optional custom `.pt` for UC-2 (out-of-stock). |
| `SPILL_MODEL` | _(blank)_ | Optional custom `.pt` for UC-16 (spill). |
| `OPEN_VOCAB_MODEL` | `yoloe-26n-seg.pt` | Text-prompted YOLOE checkpoint for prompt-driven features (UC-16 wet-floor sign). Blank disables them. |

**Open-vocabulary (text-prompted) models.** `get_prompted_model([...prompts])`
in `core/models.py` turns the YOLOE checkpoint into a detector for any list of
text prompts. Each prompt set is exported and cached like the other models
(OpenVINO on CPU, TensorRT on GPU), so the text encoder only runs on first use.
The first export downloads the YOLOE weights and a MobileCLIP text encoder; on
air-gapped hosts, run once with internet access and keep `EXPORT_DIR` on a
persistent volume. If `clip-anytorch` is missing, prompted features switch off
and log a warning.

In zero-shot tests on the bundled videos, prompts were reliable for distinct
objects (e.g. "wet floor sign") but **not** for empty shelf gaps, liquid spills
or telling products apart ("salsa jar" vs "tortilla chips"). Those use cases
keep their heuristics or optional trained weights. A YOLOE model fine-tuned on
your own shelf images is the path to SKU-level results.

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
