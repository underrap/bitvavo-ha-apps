FROM ghcr.io/home-assistant/aarch64-base:3.22

RUN apk add --no-cache python3 py3-pip
RUN python3 -m pip install --no-cache-dir --break-system-packages requests websocket-client

COPY collect_event_m0.py /collect_event_m0.py
COPY quality_report.py /quality_report.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh
CMD ["/run.sh"]
