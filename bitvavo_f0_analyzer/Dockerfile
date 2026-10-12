FROM ghcr.io/home-assistant/aarch64-base:3.22

RUN apk add --no-cache python3
COPY analyze_f0.py /analyze_f0.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh
CMD ["/run.sh"]
