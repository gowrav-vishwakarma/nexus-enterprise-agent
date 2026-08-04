# Nexus reference deployment
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY nexus ./nexus
COPY examples ./examples

RUN pip install --no-cache-dir ".[serve,litellm,sqlite]"

ENV NEXUS_DATA_ROOT=/data
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "examples.nexus_saas_api:app", "--host", "0.0.0.0", "--port", "8000"]
