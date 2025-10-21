#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能文献检索系统 - Docker简化启动脚本
专为Docker容器环境优化，移除虚拟环境管理
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime

def print_status(message: str, level: str = "INFO"):
    """打印状态信息"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    colors = {
        "INFO": "\033[36m",     # 青色
        "SUCCESS": "\033[32m",  # 绿色
        "WARNING": "\033[33m",  # 黄色
        "ERROR": "\033[31m",    # 红色
        "RESET": "\033[0m"      # 重置
    }

    color = colors.get(level, colors["INFO"])
    reset = colors["RESET"]

    level_icons = {
        "INFO": "ℹ️",
        "SUCCESS": "✅",
        "WARNING": "⚠️",
        "ERROR": "❌"
    }

    icon = level_icons.get(level, "ℹ️")
    print(f"{color}[{timestamp}] {icon} {message}{reset}")

def get_base_dir():
    """获取项目根目录"""
    return Path(__file__).parent.parent

def check_dependencies():
    """检查依赖包"""
    print_status("🔍 检查依赖包...")

    base_dir = get_base_dir()
    requirements_file = base_dir / "requirements.txt"

    if not requirements_file.exists():
        print_status(f"requirements.txt 不存在: {requirements_file}", "WARNING")
        return True

    try:
        # 检查已安装的包
        result = subprocess.run([
            sys.executable, "-m", "pip", "list", "--format=json"
        ], capture_output=True, text=True, check=True)

        installed_packages = {pkg["name"].lower(): pkg["version"]
                            for pkg in json.loads(result.stdout)}

        # 读取requirements.txt
        with open(requirements_file, 'r', encoding='utf-8') as f:
            requirements = f.read().strip().split('\n')

        missing_packages = []
        for req in requirements:
            if req.strip() and not req.strip().startswith('#'):
                pkg_name = req.split('==')[0].split('>=')[0].split('<=')[0].strip()
                if pkg_name.lower() not in installed_packages:
                    missing_packages.append(pkg_name)

        if missing_packages:
            print_status(f"缺少依赖包: {', '.join(missing_packages)}", "WARNING")
            print_status("正在安装缺少的依赖包...", "INFO")

            subprocess.run([
                sys.executable, "-m", "pip", "install", "-r", str(requirements_file)
            ], check=True)

            print_status("依赖包安装完成", "SUCCESS")
        else:
            print_status("所有依赖包已安装", "SUCCESS")

        return True

    except Exception as e:
        print_status(f"检查依赖包失败: {e}", "ERROR")
        return False

def check_config_files():
    """检查配置文件"""
    print_status("🔍 检查配置文件...")

    base_dir = get_base_dir()
    config_file = base_dir / "ai_config.yaml"

    if not config_file.exists():
        print_status(f"配置文件不存在: {config_file}", "WARNING")
        print_status("请确保ai_config.yaml文件存在并配置正确", "INFO")
        return False

    print_status("配置文件检查完成", "SUCCESS")
    return True

def start_web_tty():
    """启动Web TTY服务器"""
    print_status("🌐 启动Web TTY服务器...", "INFO")
    print_status("📱 访问地址: http://localhost:8891", "INFO")
    print_status("🔌 WebSocket地址: ws://localhost:8889/ws", "INFO")
    print_status("💡 提示: 在浏览器中打开 http://localhost:8891 即可使用", "INFO")
    print_status("🔐 认证已启用，需要用户名和密码", "INFO")
    print_status("⚠️  注意: 不要在公网暴露此端口！", "WARNING")

    # 读取认证配置
    username = os.getenv('WEB_TTY_USERNAME', 'admin')
    password = os.getenv('WEB_TTY_PASSWORD', 'password')

    if password == 'password':
        print_status("⚠️  使用默认密码不安全，请修改WEB_TTY_PASSWORD环境变量！", "WARNING")

    base_dir = get_base_dir()

    try:
        cmd = [
            sys.executable,
            str(base_dir / "src" / "web_tty_server.py"),
            "--serve-html",
            "--host", "0.0.0.0",
            "--port", "8889",
            "--username", username,
            "--password", password
        ]

        print_status(f"执行命令: {' '.join(cmd)}", "INFO")

        # 直接执行，不返回
        subprocess.run(cmd)

    except KeyboardInterrupt:
        print_status("用户中断Web TTY服务器", "INFO")
    except Exception as e:
        print_status(f"启动Web TTY服务器失败: {e}", "ERROR")
        return False

def start_main_app():
    """启动主应用"""
    print_status("🚀 启动智能文献检索系统...", "INFO")

    base_dir = get_base_dir()

    try:
        cmd = [sys.executable, str(base_dir / "src" / "main.py")]
        print_status(f"执行命令: {' '.join(cmd)}", "INFO")

        # 直接执行，不返回
        subprocess.run(cmd)

    except KeyboardInterrupt:
        print_status("用户中断主应用", "INFO")
    except Exception as e:
        print_status(f"启动主应用失败: {e}", "ERROR")
        return False

def main():
    """主函数"""
    print_status("🐳 Docker环境启动脚本", "INFO")
    print_status("=" * 50, "INFO")

    # 检查环境变量决定启动模式
    web_tty_mode = os.getenv('WEB_TTY', '').lower() == 'true'

    if web_tty_mode:
        print_status("启动模式: Web TTY", "INFO")

        # 基础检查
        if not check_dependencies():
            print_status("依赖检查失败，但继续启动", "WARNING")

        # 启动Web TTY
        start_web_tty()
    else:
        print_status("启动模式: 主应用", "INFO")

        # 完整检查
        if not check_dependencies():
            print_status("依赖检查失败", "ERROR")
            sys.exit(1)

        if not check_config_files():
            print_status("配置检查失败", "ERROR")
            sys.exit(1)

        # 启动主应用
        start_main_app()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        if command == "web-tty":
            os.environ['WEB_TTY'] = 'true'
        elif command == "start":
            os.environ['WEB_TTY'] = 'false'

    main()