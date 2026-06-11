# Retail-Supermarket-Grocery CV Live-Analysis backend (+ static frontend).
# Build context must be the cv-lab/ directory:
#   docker build -f backend/Dockerfile -t retail-supermarket-grocery-cv-lab .
#
# CPU image by default. For GPU on NKP, switch the base image to an NVIDIA CUDA
# runtime (e.g. nvidia/cuda:12.4.1-runtime-ubuntu22.04 + python) and request a
# GPU in the k8s Deployment.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    YOLO_CONFIG_DIR=/app/.ultralytics

# OpenCV / video runtime libraries.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        -r backend/requirements.txt

COPY backend backend
COPY frontend frontend

# Pre-fetch the COCO person model into the resolved models dir so the container
# can run offline (models.py looks under MODELS_DIR first).
RUN mkdir -p /app/backend/models && cd /app/backend/models \
    && python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" || true

WORKDIR /app/backend
ENV FRONTEND_DIR=/app/frontend \
    MODELS_DIR=/app/backend/models

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
