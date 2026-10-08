FROM python:3.11-slim-bookworm
ARG TARGETARCH
ARG TDL_VERSION=0.20.4
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git tzdata libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in amd64) tdl_arch=64bit ;; arm64) tdl_arch=arm64 ;; *) exit 1 ;; esac; \
    cd /tmp; \
    curl -fsSL --retry 3 "https://github.com/iyear/tdl/releases/download/v${TDL_VERSION}/tdl_Linux_${tdl_arch}.tar.gz" -o tdl.tar.gz; \
    curl -fsSL --retry 3 "https://github.com/iyear/tdl/releases/download/v${TDL_VERSION}/tdl_checksums.txt" -o checksums; \
    awk -v name="tdl_Linux_${tdl_arch}.tar.gz" '$2 == name {print $1 "  tdl.tar.gz"}' checksums > check; \
    test -s check; sha256sum -c check; \
    tar -xzf tdl.tar.gz -C /usr/local/bin tdl; \
    rm tdl.tar.gz checksums check
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir 'setuptools>=68' wheel \
    && python -c 'import tomllib,subprocess,sys; p=tomllib.load(open("pyproject.toml","rb"))["project"]; subprocess.check_call([sys.executable,"-m","pip","install","--no-cache-dir",*p["dependencies"],*p["optional-dependencies"]["all"]])'
COPY favsync ./favsync
RUN python -m favsync.companion_ocr
RUN pip install --no-cache-dir --no-deps --no-build-isolation . \
    && tdl version && gallery-dl --version \
    && python -c 'import gallery_dl.extractor.exhentai' \
    && xhs --help >/dev/null
ENTRYPOINT ["favsync"]
