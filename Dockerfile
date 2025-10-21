# 构建阶段
FROM python:3.10-slim as builder

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 安装Python依赖到用户目录
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# 运行阶段
FROM python:3.10-slim

WORKDIR /app

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    pandoc \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制Python包
COPY --from=builder /root/.local /root/.local

# 复制项目文件
COPY . .

# 创建目录
RUN mkdir -p /app/original_data /app/original_prompts /app/logs /app/cache /app/pubmed_cache /app/output

# 创建简化启动命令
RUN ln -s /app/src/intelligent_literature_system.py /usr/local/bin/zhy && \
    chmod +x /usr/local/bin/zhy

# 备份原始数据
RUN if [ -d "/app/data" ]; then cp -r /app/data/* /app/original_data/ || true; fi
RUN if [ -f "/app/prompts/prompts_config.yaml" ]; then cp /app/prompts/prompts_config.yaml /app/original_prompts/ || true; fi

# 复制初始化脚本
COPY init-data.sh /docker-entrypoint-init.d/init-data.sh
RUN chmod +x /docker-entrypoint-init.d/init-data.sh

# 确保Python能找到用户安装的包
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "src/start_docker.py"]
