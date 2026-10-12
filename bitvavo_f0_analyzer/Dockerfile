FROM ghcr.io/home-assistant/aarch64-base:3.22

RUN apk add --no-cache python3
COPY analyze_f0.py /analyze_f0.py
COPY runner.py /runner.py
CMD ["python3", "-u", "/runner.py"]
