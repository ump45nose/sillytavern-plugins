FROM denoland/deno:bin-2.9.5@sha256:0d1262facd139e815217c001945eb822c7a78584cf660142c34a6b53effec1aa AS deno

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

ARG FFMPEG_VERSION=7:7.1.5-0+deb13u1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EMBY_THEME_CONFIG=/config/config.yaml

RUN apt-get update \
    && apt-get install -y --no-install-recommends "ffmpeg=${FFMPEG_VERSION}" ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deno /deno /usr/local/bin/deno

WORKDIR /app
COPY pyproject.toml README.md requirements.lock /app/
RUN PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=8 python -m pip install --no-cache-dir -r requirements.lock
COPY requirements-audio.lock /app/
RUN python -m pip install --no-cache-dir -r requirements-audio.lock \
    && python -m pip install --no-cache-dir --no-deps inaSpeechSegmenter==0.8.0
COPY --from=models keras_speech_music_noise_cnn.hdf5 /opt/theme-models/keras_speech_music_noise_cnn.hdf5
RUN echo 'f04b5e3c86fa2e81666d106b0867350fe7858c7bd006c2a74c27b5b45507e7d8  /opt/theme-models/keras_speech_music_noise_cnn.hdf5' | sha256sum -c -
ENV KERAS_HOME=/tmp/keras MPLCONFIGDIR=/tmp/matplotlib
COPY emby_theme_worker /app/emby_theme_worker
RUN PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=8 python -m pip install --no-cache-dir --no-deps . \
    && python -c "import yt_dlp; assert yt_dlp.version.__version__ == '2026.08.19'" \
    && ffmpeg -version | grep -F 'ffmpeg version 7.1.5' \
    && deno --version | grep -F 'deno 2.9.5'

RUN mkdir -p /data /config /run/secrets \
    && chown -R 1000:1001 /data /config /run/secrets

USER 1000:1001
ENTRYPOINT ["/usr/bin/tini", "--", "emby-theme-worker"]
CMD ["serve"]
