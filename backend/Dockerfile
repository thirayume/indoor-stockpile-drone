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

# Dependencies first, in their own layer: code edits then rebuild in seconds
# instead of re-resolving pip (and re-compiling OpenSfM below).
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt

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
# Mirrors upstream's Dockerfile.ubuntu24 (scikit-build-core + cmake build).
# Upstream installs no console entry point, so a small /usr/local/bin/opensfm
# wrapper invokes bin/opensfm_main.py from the editable checkout.
ARG INSTALL_OPENSFM=false
RUN if [ "$INSTALL_OPENSFM" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            build-essential cmake git pkg-config \
            libeigen3-dev libopencv-dev libceres-dev \
        && git clone --recursive --depth 1 https://github.com/mapillary/OpenSfM.git /opt/opensfm \
        && pip install --no-cache-dir -e /opt/opensfm \
            --config-settings=cmake.define.OPENSFM_BUILD_TESTS=OFF \
        && printf '#!/bin/sh\nexec python3 /opt/opensfm/bin/opensfm_main.py "$@"\n' > /usr/local/bin/opensfm \
        && chmod +x /usr/local/bin/opensfm \
        && rm -rf /var/lib/apt/lists/* ; \
    fi

# Application code last — the cheapest layer to rebuild.
COPY src ./src
COPY run_example_reconstruction.py ./
RUN pip install --no-cache-dir --no-deps -e .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
