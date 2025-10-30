# ---------- Build stage ----------
  FROM python:3.10-slim AS builder

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
  RUN pip install --no-cache-dir -r requirements.txt
  
  # ---------- Runtime stage ----------
  FROM python:3.10-slim AS runtime
  
  ENV PYTHONDONTWRITEBYTECODE=1 \
      PYTHONUNBUFFERED=1 \
      DEBIAN_FRONTEND=noninteractive \
      PATH="/opt/venv/bin:$PATH"
  
  # Runtime libs
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
  RUN mkdir -p data/chunks data/vectors data/temp logs scripts \
   && chown -R app:app data logs scripts
  
  USER app
  EXPOSE 8500
  
  # Healthcheck: try HTTPS (-k for self-signed), fallback to HTTP
  HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsSk https://localhost:8500/ || curl -fsS http://localhost:8500/ || exit 1
  
  # Use the launcher (enables HTTPS if certs are readable)
  CMD ["start.sh"]
  