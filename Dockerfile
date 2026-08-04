# ---------- Build stage ----------
  FROM python:3.11-slim AS builder

  ENV PYTHONDONTWRITEBYTECODE=1 \
      PIP_NO_CACHE_DIR=1 \
      PIP_DISABLE_PIP_VERSION_CHECK=1 \
      DEBIAN_FRONTEND=noninteractive \
      PATH="/opt/venv/bin:$PATH"
  
  # System deps (build)
  RUN apt-get update \
   && apt-get install -y --no-install-recommends \
      ca-certificates gcc g++ libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1 libgcc-s1 poppler-utils \
   && rm -rf /var/lib/apt/lists/*
  
  # Venv
  RUN python -m venv /opt/venv
  
  # Python deps
  COPY requirements.txt .
  # CPU Torch (comment out and use cu118 if you really want GPU)
  RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
  # PaddlePaddle backs the OCR engines (core/document_processing/ocr). Pinned
  # to 3.2.0, NOT the latest 3.3.x: paddlepaddle 3.3.0's oneDNN/PIR CPU
  # executor is broken for text detection (upstream bug, PaddlePaddle/Paddle
  # #77340 — confirmed by actually running OCR inference against this repo's
  # code, not just reading changelogs). CPU build by default; swap the line
  # below for the GPU build to enable PaddleOCR-VL (the engine selector
  # auto-detects which one is installed via
  # paddle.device.is_compiled_with_cuda(), independent of the torch build
  # above). Re-verify the oneDNN bug is fixed before bumping past 3.2.x:
  #   RUN pip install --no-cache-dir paddlepaddle-gpu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
  RUN pip install --no-cache-dir paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
  RUN pip install --no-cache-dir -r requirements.txt
  
  # ---------- Runtime stage ----------
  FROM python:3.11-slim AS runtime

  ENV PYTHONDONTWRITEBYTECODE=1 \
      PYTHONUNBUFFERED=1 \
      DEBIAN_FRONTEND=noninteractive \
      PATH="/opt/venv/bin:$PATH"

  # Runtime libs (libgl1/libglib2.0-0/... are needed by OpenCV, a PaddleOCR
  # dependency; poppler-utils by PDF handling; no OCR-specific system package
  # is needed — PP-OCRv6/PaddleOCR-VL are pure-Python/paddle, unlike the
  # previous Tesseract-based pipeline).
  RUN apt-get update \
   && apt-get install -y --no-install-recommends \
      ca-certificates libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1 libgcc-s1 poppler-utils curl \
   && rm -rf /var/lib/apt/lists/*
  
  # Non-root user
  RUN groupadd -r app && useradd -r -g app -s /bin/bash -m app
  
  # Bring venv from builder stage
  COPY --from=builder /opt/venv /opt/venv
  
  # App files
  WORKDIR /app
  COPY --chown=app:app . .
  
  # TLS-aware launcher in PATH (no need to know WORKDIR)
  COPY start.sh /usr/local/bin/start.sh
  RUN chmod 0755 /usr/local/bin/start.sh
  
  # Data dirs & permissions
  RUN mkdir -p data/chunks data/vectors data/temp logs scripts model_weights \
   && chown -R app:app data logs scripts model_weights

  USER app

  # Bake the embedding + reranker weights into the image under ./model_weights so:
  # (a) first request in production isn't a multi-hundred-MB cold download,
  # (b) the weights are reviewable on disk (`docker exec ... ls model_weights/`).
  # Requires network access at build time. If you override EMBEDDING_MODEL or
  # RERANKER_MODEL at runtime to something not baked in here, that model is
  # fetched on first use instead — see docs/PRODUCTION_READINESS_REVIEW.md.
  RUN python -m scripts.download_models

  EXPOSE 8500

  # Healthcheck: try HTTPS (-k for self-signed), fallback to HTTP.
  # start-period covers first-boot model downloads from Hugging Face; see
  # docs/PRODUCTION_READINESS_REVIEW.md (P-4) about baking models into the image.
  HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fsSk https://localhost:8500/ || curl -fsS http://localhost:8500/ || exit 1
  
  # Use the launcher (enables HTTPS if certs are readable)
  CMD ["start.sh"]
  