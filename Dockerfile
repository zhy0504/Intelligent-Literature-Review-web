FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    pandoc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 创建原始数据备份目录（用于volume挂载时的初始化）
RUN mkdir -p /app/original_data /app/original_prompts /app/logs /app/cache /app/pubmed_cache

# 备份原始数据（如果volume挂载失败时使用）
RUN if [ -d "/app/data" ]; then cp -r /app/data/* /app/original_data/ || true; fi
RUN if [ -f "/app/prompts/prompts_config.yaml" ]; then cp /app/prompts/prompts_config.yaml /app/original_prompts/ || true; fi

# 复制初始化脚本
COPY init-data.sh /docker-entrypoint-init.d/init-data.sh
RUN chmod +x /docker-entrypoint-init.d/init-data.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "src/web_app.py"]
