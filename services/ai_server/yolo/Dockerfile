FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 (OpenCV headless)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY yolo_server.py .

# 모델 디렉터리 (docker-compose volume mount)
RUN mkdir -p /app/models

EXPOSE 5005

CMD ["python", "yolo_server.py"]
