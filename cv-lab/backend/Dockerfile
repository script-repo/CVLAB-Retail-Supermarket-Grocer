# Retail-Supermarket-Grocery CV Live-Analysis backend (+ static frontend).
# Build context must be the cv-lab/ directory:
#   docker build -f backend/Dockerfile -t retail-supermarket-grocery-cv-lab .
#
# Single image, runs on CPU-only or GPU nodes. PyTorch's standard (CUDA-enabled)
# wheel is installed instead of the CPU-only build, so torch.cuda.is_available()
# is True when a GPU + NVIDIA driver are exposed to the container (via the
# NVIDIA device plugin and a `nvidia.com/gpu` resource request in the k8s
# Deployment) and False otherwise. The app's DEVICE=auto setting (see
# docs/CONFIGURATION.md) picks CUDA when available and falls back to CPU
# automatically — no separate GPU image or build is needed.
#
# Inference runtime is also picked automatically (MODEL_FORMAT=auto): OpenVINO
# on CPU (always installed), TensorRT FP16 on GPU when the image is built with
#   --build-arg ACCEL=gpu      (adds requirements-gpu.txt, several GB larger)
# Without it a GPU still runs PyTorch CUDA FP16. Mount a volume at
# /app/backend/models/exported to keep exported models across restarts.
FROM python:3.11-slim

ARG ACCEL=cpu

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    YOLO_CONFIG_DIR=/app/.ultralytics

# OpenCV / video runtime libraries.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements-gpu.txt backend/
RUN pip install -r backend/requirements.txt \
    && if [ "$ACCEL" = "gpu" ]; then pip install -r backend/requirements-gpu.txt; fi

COPY backend backend
COPY frontend frontend

# Pre-fetch the COCO person model into the resolved models dir so the container
# can run offline (models.py looks under MODELS_DIR first).
RUN mkdir -p /app/backend/models && cd /app/backend/models \
    && python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')" || true

WORKDIR /app/backend
ENV FRONTEND_DIR=/app/frontend \
    MODELS_DIR=/app/backend/models \
    LOCAL_STORAGE_DIR=/data

RUN groupadd --gid 1001 cvlab \
    && useradd --uid 1001 --gid cvlab --no-create-home --home-dir /app cvlab \
    && mkdir -p /app/.ultralytics /data \
    && chown -R cvlab:cvlab /app /data

USER 1001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
