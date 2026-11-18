FROM python:3.12.10-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements/phase7-dashboard.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock && useradd --uid 10001 --create-home app
WORKDIR /app
COPY apps/factorygraph_dashboard /app
USER 10001
HEALTHCHECK --interval=15s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18501/_stcore/health',timeout=3)"
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=18501", "--server.headless=true", "--server.enableXsrfProtection=true", "--browser.gatherUsageStats=false", "--server.fileWatcherType=none"]
