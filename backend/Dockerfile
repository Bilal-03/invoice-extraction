# Full local OCR image for Intel Macs: Docker supplies Linux x86_64 and the
# official Paddle image supplies a compatible Python/Paddle runtime.
FROM paddlepaddle/paddle:3.3.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PADDLE_DEVICE=cpu

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./

# PaddlePaddle is already present in the base image. Install the large OCR and
# document-parsing layers before copying application code so normal code edits
# keep these expensive Docker layers cached.
RUN python -m pip install --no-cache-dir "paddleocr[doc-parser]>=3.0.0"

# Docling supports CPU-only inference, but the default Linux PyTorch index can
# select CUDA wheels. Pin the compatible CPU wheels explicitly for this image.
RUN python -m pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    "torch==2.5.1" "torchvision==0.20.1"
RUN printf 'torch==2.5.1\n' > /tmp/pytorch-constraints.txt \
    && python -m pip install --no-cache-dir \
        --constraint /tmp/pytorch-constraints.txt \
        "docling>=2.0.0"

COPY app ./app
COPY eval ./eval
COPY alembic.ini ./
COPY alembic ./alembic

# Install the application dependencies last so pip does not backtrack through
# the large OCR/Docling graph as one optional extra.
RUN python -m pip install --no-cache-dir .

EXPOSE 8000

# Render supplies PORT at runtime; keep 8000 as the local/default fallback.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
