# syntax=docker/dockerfile:1
FROM ubuntu:26.04@sha256:2260313b31c8c011cd2eebe728008efac1b3982be73eb71348ea2648d2c0e09b

ARG DEBIAN_FRONTEND=noninteractive
ARG BLENDER_PACKAGE=5.0.1+dfsg-1ubuntu1
RUN apt-get update && apt-get install -y --no-install-recommends \
      blender=${BLENDER_PACKAGE} xvfb openbox \
      python3 python3-xlib python3-pil xclip tini \
      libgl1-mesa-dri mesa-utils fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /bin/sh blender \
    && mkdir -p /workspace /opt/use-blender \
    && chown blender:blender /workspace

RUN mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix

LABEL org.opencontainers.image.title="use-blender" \
      org.opencontainers.image.description="Blender with a small computer-use REST API" \
      org.opencontainers.image.version="0.1.0"

ENV DISPLAY=:99 \
    HOME=/home/blender \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    GALLIUM_DRIVER=llvmpipe \
    LP_NUM_THREADS=2 \
    OMP_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=1 \
    RESOLUTION=1280x800 \
    PORT=8000
COPY runtime/ /opt/use-blender/
USER blender
WORKDIR /workspace
EXPOSE 8000
VOLUME ["/workspace"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python3", "/opt/use-blender/healthcheck.py"]
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "/opt/use-blender/server.py"]
