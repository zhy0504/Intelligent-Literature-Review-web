@echo off
chcp 65001 >nul
echo ====================================
echo   智能文献系统 Docker 启动脚本
echo ====================================
echo.

REM 检查 Docker 是否安装
docker --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Docker，请先安装 Docker Desktop
    echo 下载地址: https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)

REM 检查 Docker 是否运行
docker ps >nul 2>&1
if errorlevel 1 (
    echo [错误] Docker 未运行，请启动 Docker Desktop
    pause
    exit /b 1
)

REM 检查配置文件
if not exist ai_config.yaml (
    echo [警告] ai_config.yaml 不存在，从示例复制...
    copy ai_config_example.yaml ai_config.yaml
    echo [提示] 请编辑 ai_config.yaml 配置您的 AI 服务
)

REM 创建必要的目录
if not exist data mkdir data
if not exist logs mkdir logs
if not exist cache mkdir cache
if not exist pubmed_cache mkdir pubmed_cache

echo [1] 构建并启动容器...
docker-compose up --build -d

if errorlevel 1 (
    echo [错误] 容器启动失败
    pause
    exit /b 1
)

echo.
echo [成功] 容器已启动
echo.
echo 常用命令:
echo   查看日志: docker-compose logs -f
echo   进入容器: docker-compose exec ultrathink bash
echo   停止容器: docker-compose down
echo   重启容器: docker-compose restart
echo.
echo [2] 查看运行日志 (按 Ctrl+C 退出)
timeout /t 2 >nul
docker-compose logs -f
