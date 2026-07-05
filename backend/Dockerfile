FROM python:3.11-slim

# Runtime libraries required by Open3D's manylinux wheel. Even fully headless,
# `import open3d` dynamically links its visualization stack:
#   libgl1 / libegl1  - OpenGL/EGL
#   libgomp1          - OpenMP (parallel geometry ops)
#   libglib2.0-0      - glib, pulled in via the GUI toolkit
#   libx11-6          - X11 client library
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libegl1 \
    libgomp1 \
    libglib2.0-0 \
    libx11-6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY run_example_reconstruction.py ./

RUN pip install --no-cache-dir -e .

# Datasets (the ODMdata submodule and the OpenSfM project) are NOT baked into
# the image — they are large and change independently of the code.
# docker-compose mounts the host's ./data at /app/data and points
# STOCKPILE_DATA_DIR / OPEN_SFM_DATA_ROOT there.

# Optional: build the OpenSfM CLI from source. Disabled by default because it
# compiles OpenCV-/Ceres-dependent C++ and adds several GB / many minutes:
#   docker compose build --build-arg INSTALL_OPENSFM=true backend
# Toolchain: build-essential, cmake, git, pkg-config.
# Libraries: libeigen3-dev (linear algebra), libopencv-dev (features/matching),
#            libceres-dev (bundle-adjustment solver).
# Upstream installs no console entry point, so we build in a source checkout
# (per OpenSfM's docs) and add a small /usr/local/bin/opensfm wrapper.
ARG INSTALL_OPENSFM=false
RUN if [ "$INSTALL_OPENSFM" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            build-essential cmake git pkg-config \
            libeigen3-dev libopencv-dev libceres-dev \
        && git clone --recursive --depth 1 https://github.com/mapillary/OpenSfM.git /opt/opensfm \
        && pip install --no-cache-dir -r /opt/opensfm/requirements.txt \
        && cd /opt/opensfm && python setup.py build \
        && printf '#!/bin/sh\nPYTHONPATH=/opt/opensfm exec python3 /opt/opensfm/bin/opensfm_main.py "$@"\n' > /usr/local/bin/opensfm \
        && chmod +x /usr/local/bin/opensfm \
        && rm -rf /var/lib/apt/lists/* ; \
    fi

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
