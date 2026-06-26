# Clark Discord bot. Python 3.14, runs as non-root. .env mounted read-only at runtime.
FROM python:3.14-slim
WORKDIR /app
# ffmpeg for voice/yt-dlp; libsodium/libffi for PyNaCl; build deps + image libs for any source builds
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg gcc libffi-dev libsodium-dev libjpeg-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app
CMD ["python","clark.py"]
