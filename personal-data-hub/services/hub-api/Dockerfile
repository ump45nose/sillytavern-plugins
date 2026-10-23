FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /app
COPY deploy/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY --chown=1000:1001 src /app/src
ENV PYTHONPATH=/app/src
USER 1000:1001
EXPOSE 8080
CMD ["uvicorn", "hub_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-server-header"]
