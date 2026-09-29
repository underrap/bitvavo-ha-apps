FROM ghcr.io/home-assistant/aarch64-base:3.22

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache python3 py3-requests

COPY collect_bitvavo_microstructure.py /collect_bitvavo_microstructure.py
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]
