#!/bin/bash

echo "===================================="
echo "  智能文献系统 Docker 启动脚本"
echo "===================================="
echo

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "[错误] 未检测到 Docker，请先安装 Docker"
    echo "安装指南: https://docs.docker.com/get-docker/"
    exit 1
fi

# 检查 Docker 是否运行
if ! docker ps &> /dev/null; then
    echo "[错误] Docker 未运行，请启动 Docker 服务"
    echo "Linux: sudo systemctl start docker"
    echo "Mac: 启动 Docker Desktop"
    exit 1
fi

# 检查配置文件
if [ ! -f ai_config.yaml ]; then
    echo "[警告] ai_config.yaml 不存在，从示例复制..."
    cp ai_config_example.yaml ai_config.yaml
    echo "[提示] 请编辑 ai_config.yaml 配置您的 AI 服务"
fi

# 创建必要的目录
mkdir -p data logs cache pubmed_cache

echo "[1] 构建并启动容器..."
docker-compose up --build -d

if [ $? -ne 0 ]; then
    echo "[错误] 容器启动失败"
    exit 1
fi

echo
echo "[成功] 容器已启动"
echo
echo "常用命令:"
echo "  查看日志: docker-compose logs -f"
echo "  进入容器: docker-compose exec ultrathink bash"
echo "  停止容器: docker-compose down"
echo "  重启容器: docker-compose restart"
echo
echo "[2] 查看运行日志 (按 Ctrl+C 退出)"
sleep 2
docker-compose logs -f
