FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser
WORKDIR /app
COPY requirements.txt requirements-space.txt ./
RUN pip install --no-cache-dir -r requirements-space.txt
COPY --chown=appuser:appuser dashboard/ ./dashboard/
COPY --chown=appuser:appuser entrypoint.sh .
RUN mkdir -p /app/db && chown appuser:appuser /app/db
USER appuser
ENV HOST=0.0.0.0 PORT=7860 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2
EXPOSE 7860
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
