# WolfPack MLflow tracking server.
# Extends the official image with psycopg2 for the Postgres artifact store.
FROM python:3.11-slim

RUN pip install --no-cache-dir \
    mlflow>=3.5.1 \
    psycopg2-binary>=2.9.9

EXPOSE 5000

# Default: file-based artifact store. Override via MLflow env vars in compose.
ENTRYPOINT ["mlflow", "server"]
CMD ["--host", "0.0.0.0", "--port", "5000"]