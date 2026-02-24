FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY . .

RUN git init && git add -A && git commit -m "initial"

VOLUME ["/app/agent_data", "/app/extensions", "/app/workspace", "/app/data", "/app/logs"]

CMD ["python", "-m", "evo_agent"]
