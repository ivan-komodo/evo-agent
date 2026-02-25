FROM python:3.11-slim

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUTF8=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends git locales && \
    sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen en_US.UTF-8 && \
    rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY . .

RUN git init && git add -A && git commit -m "initial"

VOLUME ["/app/agent_data", "/app/extensions", "/app/workspace", "/app/data", "/app/logs"]

CMD ["python", "-m", "evo_agent"]
