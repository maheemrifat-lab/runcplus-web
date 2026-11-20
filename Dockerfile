FROM gcc:14-bookworm

# Install Python 3 runtime and essentials
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy application files
COPY . /app

# Ensure directories exist
RUN mkdir -p /app/cache /app/downloads /app/static

ENV PORT=8080
ENV BIND_HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python3", "server/server.py"]
