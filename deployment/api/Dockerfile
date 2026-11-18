FROM python:3.12.10-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements/phase7-api.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock
COPY pyproject.toml README.md MANIFEST.in /opt/package/
COPY src /opt/package/src
RUN pip install --no-deps --no-build-isolation /opt/package && useradd --uid 10001 --create-home app
WORKDIR /workspace
COPY configs/phase7 /workspace/configs/phase7
USER 10001
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18080/api/v1/health/live',timeout=3)"
CMD ["python", "-m", "factorygraph.phase7.server"]
