FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b
WORKDIR /app
COPY probe.py /app/probe.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PROBE_ROLE=client
USER 1000:1000
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()"]
CMD ["python", "/app/probe.py"]
