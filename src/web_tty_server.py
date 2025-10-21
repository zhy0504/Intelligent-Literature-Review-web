#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轻量级Web TTY服务器 - 老王出品，简单粗暴好用
提供浏览器直接连接容器终端的功能
支持简单的用户名密码认证
"""

import os
import sys
import asyncio
import websockets
import json
import logging
import signal
import uuid
import hashlib
import secrets
import time
from typing import Dict, Set, Optional, Tuple
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AuthManager:
    """认证管理器"""

    def __init__(self, enable_auth: bool = True, username: str = "admin", password: str = "password"):
        self.enable_auth = enable_auth
        self.username = username
        self.password = password
        self.active_sessions: Dict[str, Dict] = {}  # session_id -> {created_at, last_activity}
        self.session_timeout = 3600  # 1小时超时

    def hash_password(self, password: str) -> str:
        """密码哈希"""
        return hashlib.sha256(password.encode()).hexdigest()

    def verify_credentials(self, username: str, password: str) -> bool:
        """验证用户凭据"""
        if not self.enable_auth:
            return True

        return (username == self.username and
                self.hash_password(password) == self.hash_password(self.password))

    def create_session(self) -> str:
        """创建会话"""
        session_id = secrets.token_urlsafe(32)
        self.active_sessions[session_id] = {
            'created_at': time.time(),
            'last_activity': time.time()
        }
        return session_id

    def validate_session(self, session_id: str) -> bool:
        """验证会话"""
        if not self.enable_auth:
            return True

        if session_id not in self.active_sessions:
            return False

        # 检查会话是否超时
        session = self.active_sessions[session_id]
        if time.time() - session['last_activity'] > self.session_timeout:
            del self.active_sessions[session_id]
            return False

        # 更新最后活动时间
        session['last_activity'] = time.time()
        return True

    def revoke_session(self, session_id: str):
        """撤销会话"""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]

    def cleanup_expired_sessions(self):
        """清理过期会话"""
        current_time = time.time()
        expired_sessions = [
            sid for sid, session in self.active_sessions.items()
            if current_time - session['last_activity'] > self.session_timeout
        ]
        for sid in expired_sessions:
            del self.active_sessions[sid]

class WebTTYServer:
    """Web TTY服务器"""

    def __init__(self, host='0.0.0.0', port=8889, enable_auth: bool = True,
                 username: str = "admin", password: str = "password"):
        self.host = host
        self.port = port
        self.connections: Dict[str, websockets.WebSocketServerProtocol] = {}
        self.shell_processes: Dict[str, asyncio.subprocess.Process] = {}
        self.authenticated_clients: Dict[str, str] = {}  # client_id -> session_id

        # 初始化认证管理器
        self.auth_manager = AuthManager(enable_auth, username, password)

        if enable_auth:
            logger.info(f"🔐 认证已启用 - 用户名: {username}")
        else:
            logger.warning("⚠️  认证已禁用 - 任何人都可以访问!")

    async def handle_websocket(self, websocket, path):
        """处理WebSocket连接"""
        # 验证WebSocket路径
        if path != "/ws":
            await websocket.close(code=1008, reason="Invalid path")
            return

        client_id = str(uuid.uuid4())
        self.connections[client_id] = websocket
        logger.info(f"🔌 新的TTY连接: {client_id} from {websocket.remote_address}")

        try:
            # 发送连接成功消息，要求认证
            await websocket.send(json.dumps({
                'type': 'auth_required',
                'client_id': client_id,
                'message': '请进行身份验证',
                'auth_enabled': self.auth_manager.enable_auth
            }))

            # 等待客户端消息
            async for message in websocket:
                try:
                    data = json.loads(message)

                    # 处理认证消息
                    if data.get('type') == 'auth':
                        await self.handle_auth(client_id, data)
                        continue

                    # 检查是否已认证
                    if self.auth_manager.enable_auth:
                        if client_id not in self.authenticated_clients:
                            await websocket.send(json.dumps({
                                'type': 'error',
                                'message': '未授权访问，请先进行身份验证'
                            }))
                            continue

                        # 验证会话
                        session_id = self.authenticated_clients[client_id]
                        if not self.auth_manager.validate_session(session_id):
                            await websocket.send(json.dumps({
                                'type': 'auth_expired',
                                'message': '会话已过期，请重新登录'
                            }))
                            del self.authenticated_clients[client_id]
                            continue

                    await self.handle_message(client_id, data)
                except json.JSONDecodeError:
                    logger.error(f"收到无效JSON消息: {message}")
                except Exception as e:
                    logger.error(f"处理消息时出错: {e}")
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': f'处理消息失败: {str(e)}'
                    }))

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"🔌 TTY连接断开: {client_id}")
        except Exception as e:
            logger.error(f"TTY连接处理出错: {e}")
        finally:
            # 清理连接和进程
            await self.cleanup_connection(client_id)

    async def handle_auth(self, client_id: str, data: dict):
        """处理认证请求"""
        websocket = self.connections.get(client_id)
        if not websocket:
            return

        username = data.get('username', '')
        password = data.get('password', '')

        if self.auth_manager.verify_credentials(username, password):
            # 认证成功，创建会话
            session_id = self.auth_manager.create_session()
            self.authenticated_clients[client_id] = session_id

            await websocket.send(json.dumps({
                'type': 'auth_success',
                'message': f'认证成功，欢迎 {username}!',
                'session_id': session_id
            }))

            logger.info(f"✅ 用户 {username} 认证成功: {client_id}")
        else:
            # 认证失败
            await websocket.send(json.dumps({
                'type': 'auth_failed',
                'message': '用户名或密码错误'
            }))

            logger.warning(f"❌ 认证失败: {username} from {websocket.remote_address}")

    async def handle_message(self, client_id: str, data: dict):
        """处理客户端消息"""
        websocket = self.connections.get(client_id)
        if not websocket:
            return

        msg_type = data.get('type')

        if msg_type == 'start_shell':
            await self.start_shell(client_id, data)
        elif msg_type == 'input':
            await self.send_input(client_id, data.get('data', ''))
        elif msg_type == 'resize':
            await self.resize_terminal(client_id, data)
        elif msg_type == 'ping':
            await websocket.send(json.dumps({'type': 'pong'}))
        else:
            logger.warning(f"未知消息类型: {msg_type}")

    async def start_shell(self, client_id: str, data: dict):
        """启动shell进程"""
        websocket = self.connections.get(client_id)
        if not websocket:
            return

        # 如果已经有shell在运行，先关闭
        if client_id in self.shell_processes:
            await self.cleanup_connection(client_id)

        try:
            # 启动shell进程
            shell_cmd = data.get('shell', '/bin/bash')
            if os.name == 'nt':  # Windows
                shell_cmd = 'cmd.exe'

            process = await asyncio.create_subprocess_exec(
                shell_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                preexec_fn=None if os.name == 'nt' else os.setsid
            )

            self.shell_processes[client_id] = process

            # 发送启动成功消息
            await websocket.send(json.dumps({
                'type': 'shell_started',
                'message': f'Shell启动成功: {shell_cmd}'
            }))

            # 启动输出读取任务
            asyncio.create_task(self.read_shell_output(client_id, process))

            logger.info(f"🖥️ 为客户端 {client_id} 启动Shell: {shell_cmd}")

        except Exception as e:
            logger.error(f"启动Shell失败: {e}")
            await websocket.send(json.dumps({
                'type': 'error',
                'message': f'启动Shell失败: {str(e)}'
            }))

    async def send_input(self, client_id: str, data: str):
        """发送输入到shell"""
        process = self.shell_processes.get(client_id)
        if not process or process.stdin:
            return

        try:
            process.stdin.write(data.encode('utf-8'))
            await process.stdin.drain()
        except Exception as e:
            logger.error(f"发送输入到Shell失败: {e}")

    async def resize_terminal(self, client_id: str, data: dict):
        """调整终端大小"""
        # 这个功能在纯Python实现中比较复杂，暂时记录日志
        cols = data.get('cols', 80)
        rows = data.get('rows', 24)
        logger.info(f"📐 客户端 {client_id} 请求调整终端大小: {cols}x{rows}")

        # 在实际应用中，这里需要发送SIGWINCH信号并调整pty大小
        # 暂时只记录日志

    async def read_shell_output(self, client_id: str, process: asyncio.subprocess.Process):
        """读取shell输出"""
        websocket = self.connections.get(client_id)
        if not websocket:
            return

        try:
            while process.returncode is None and client_id in self.connections:
                try:
                    # 读取输出
                    output = await asyncio.wait_for(
                        process.stdout.read(4096),
                        timeout=0.1
                    )

                    if output:
                        await websocket.send(json.dumps({
                            'type': 'output',
                            'data': output.decode('utf-8', errors='ignore')
                        }))
                    else:
                        # 没有输出，短暂休眠
                        await asyncio.sleep(0.01)

                except asyncio.TimeoutError:
                    # 超时，继续循环
                    await asyncio.sleep(0.01)
                except Exception as e:
                    logger.error(f"读取Shell输出时出错: {e}")
                    break

            # 进程结束，发送退出消息
            if client_id in self.connections:
                await websocket.send(json.dumps({
                    'type': 'shell_exited',
                    'code': process.returncode,
                    'message': f'Shell进程已退出，返回码: {process.returncode}'
                }))

        except Exception as e:
            logger.error(f"读取Shell输出任务出错: {e}")
        finally:
            await self.cleanup_connection(client_id)

    async def cleanup_connection(self, client_id: str):
        """清理连接资源"""
        # 清理认证会话
        if client_id in self.authenticated_clients:
            session_id = self.authenticated_clients[client_id]
            self.auth_manager.revoke_session(session_id)
            del self.authenticated_clients[client_id]
            logger.info(f"🔐 撤销会话: {session_id}")

        # 关闭shell进程
        if client_id in self.shell_processes:
            process = self.shell_processes[client_id]
            try:
                if process.returncode is None:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=5.0)
            except Exception as e:
                logger.error(f"关闭Shell进程失败: {e}")
                try:
                    process.kill()
                except:
                    pass
            finally:
                del self.shell_processes[client_id]

        # 移除连接
        if client_id in self.connections:
            del self.connections[client_id]

        logger.info(f"🧹 清理连接资源: {client_id}")

    async def cleanup_expired_sessions_task(self):
        """定期清理过期会话的任务"""
        while True:
            try:
                await asyncio.sleep(300)  # 每5分钟清理一次
                self.auth_manager.cleanup_expired_sessions()
                logger.debug("🧹 清理过期会话完成")
            except Exception as e:
                logger.error(f"清理过期会话时出错: {e}")

    async def start_server(self):
        """启动服务器"""
        logger.info(f"🚀 启动Web TTY服务器...")
        logger.info(f"🌐 访问地址: http://{self.host}:{self.port}")
        logger.info(f"📱 WebSocket地址: ws://{self.host}:{self.port}/ws")
        logger.info(f"💡 提示: 在浏览器中打开 http://localhost:{self.port} 即可使用")

        if self.auth_manager.enable_auth:
            logger.info(f"🔐 认证已启用 - 用户名: {self.auth_manager.username}")

        # 创建WebSocket服务器
        server = await websockets.serve(
            self.handle_websocket,
            self.host,
            self.port
        )

        # 启动会话清理任务
        if self.auth_manager.enable_auth:
            asyncio.create_task(self.cleanup_expired_sessions_task())

        logger.info("✅ Web TTY服务器启动成功！")

        # 设置信号处理
        def signal_handler(signum, frame):
            logger.info("🛑 收到退出信号，正在关闭服务器...")
            asyncio.create_task(self.shutdown())

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        return server

    async def shutdown(self):
        """关闭服务器"""
        logger.info("🔄 正在关闭所有连接...")

        # 清理所有连接
        for client_id in list(self.connections.keys()):
            await self.cleanup_connection(client_id)

        logger.info("👋 Web TTY服务器已关闭")
        sys.exit(0)


# 带认证的HTML页面
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Web TTY - 老王出品</title>
    <meta charset="utf-8">
    <style>
        body {
            margin: 0;
            padding: 20px;
            font-family: 'Courier New', monospace;
            background-color: #000;
            color: #00ff00;
        }
        .auth-container {
            max-width: 400px;
            margin: 50px auto;
            padding: 20px;
            border: 1px solid #00ff00;
            border-radius: 5px;
        }
        .auth-container h2 {
            text-align: center;
            margin-bottom: 20px;
        }
        .form-group {
            margin-bottom: 15px;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
        }
        .form-group input {
            width: 100%;
            background-color: #000;
            border: 1px solid #00ff00;
            color: #00ff00;
            padding: 10px;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            box-sizing: border-box;
        }
        .auth-button {
            width: 100%;
            background-color: #00ff00;
            color: #000;
            border: none;
            padding: 10px 20px;
            cursor: pointer;
            font-weight: bold;
            font-size: 16px;
        }
        .auth-button:hover {
            background-color: #00cc00;
        }
        .auth-button:disabled {
            background-color: #666;
            cursor: not-allowed;
        }
        .error-message {
            color: #ff0000;
            margin-top: 10px;
            text-align: center;
        }
        .terminal-container {
            display: none;
        }
        #terminal {
            width: 100%;
            height: 70vh;
            background-color: #000;
            border: 1px solid #00ff00;
            padding: 10px;
            overflow-y: auto;
            white-space: pre-wrap;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            box-sizing: border-box;
        }
        #input {
            width: 100%;
            background-color: #000;
            border: 1px solid #00ff00;
            color: #00ff00;
            padding: 10px;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            box-sizing: border-box;
            margin-top: 10px;
        }
        .controls {
            margin-bottom: 10px;
        }
        button {
            background-color: #00ff00;
            color: #000;
            border: none;
            padding: 10px 20px;
            margin-right: 10px;
            cursor: pointer;
            font-weight: bold;
        }
        button:hover {
            background-color: #00cc00;
        }
        button:disabled {
            background-color: #666;
            cursor: not-allowed;
        }
        .status {
            margin-bottom: 10px;
            color: #00ff00;
        }
        .hidden {
            display: none;
        }
    </style>
</head>
<body>
    <!-- 认证界面 -->
    <div id="authContainer" class="auth-container">
        <h2>🔐 Web TTY 认证</h2>
        <div class="form-group">
            <label for="username">用户名:</label>
            <input type="text" id="username" placeholder="请输入用户名" autocomplete="username">
        </div>
        <div class="form-group">
            <label for="password">密码:</label>
            <input type="password" id="password" placeholder="请输入密码" autocomplete="current-password">
        </div>
        <button id="loginBtn" class="auth-button" onclick="login()">登录</button>
        <div id="errorMessage" class="error-message hidden"></div>
    </div>

    <!-- 终端界面 -->
    <div id="terminalContainer" class="terminal-container">
        <h1>🖥️ Web TTY - 老王出品</h1>
        <div class="status" id="status">状态: 未连接</div>
        <div class="controls">
            <button onclick="startShell()" id="startShellBtn" disabled>启动Shell</button>
            <button onclick="disconnect()">断开连接</button>
            <button onclick="clearTerminal()">清屏</button>
            <button onclick="logout()" id="logoutBtn">退出登录</button>
        </div>
        <div id="terminal"></div>
        <input type="text" id="input" placeholder="输入命令..." disabled>
    </div>

    <script>
        let ws = null;
        let clientId = null;
        let shellActive = false;
        let isAuthenticated = false;
        let sessionId = null;

        // 页面加载时连接WebSocket
        window.onload = function() {
            connect();
        };

        function connect() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.hostname}:8889/ws`;

            ws = new WebSocket(wsUrl);

            ws.onopen = function() {
                console.log('WebSocket连接已建立');
            };

            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                handleMessage(data);
            };

            ws.onclose = function() {
                console.log('WebSocket连接已断开');
                updateStatus('连接断开');
                if (isAuthenticated) {
                    // 如果已认证，显示重新连接提示
                    appendToTerminal('\\n🔌 连接已断开，正在尝试重新连接...\\n');
                    setTimeout(connect, 3000); // 3秒后重新连接
                }
            };

            ws.onerror = function(error) {
                console.error('WebSocket错误:', error);
                updateStatus('连接错误');
            };
        }

        function handleMessage(data) {
            switch(data.type) {
                case 'auth_required':
                    console.log('服务器要求认证');
                    if (!data.auth_enabled) {
                        // 如果不需要认证，直接显示终端
                        showTerminal();
                        updateStatus('已连接（无需认证）');
                    }
                    break;

                case 'auth_success':
                    isAuthenticated = true;
                    sessionId = data.session_id;
                    hideError();
                    showTerminal();
                    updateStatus('认证成功');
                    appendToTerminal('✅ ' + data.message + '\\n');
                    document.getElementById('startShellBtn').disabled = false;
                    break;

                case 'auth_failed':
                    showError(data.message);
                    document.getElementById('loginBtn').disabled = false;
                    break;

                case 'auth_expired':
                    isAuthenticated = false;
                    sessionId = null;
                    showAuth();
                    showError(data.message);
                    break;

                case 'shell_started':
                    shellActive = true;
                    appendToTerminal('✅ ' + data.message + '\\n');
                    document.getElementById('input').disabled = false;
                    break;

                case 'output':
                    appendToTerminal(data.data);
                    break;

                case 'shell_exited':
                    shellActive = false;
                    appendToTerminal('🔴 ' + data.message + '\\n');
                    document.getElementById('input').disabled = true;
                    break;

                case 'error':
                    appendToTerminal('❌ 错误: ' + data.message + '\\n');
                    break;

                case 'pong':
                    // 心跳响应，忽略
                    break;
            }
        }

        function login() {
            const username = document.getElementById('username').value.trim();
            const password = document.getElementById('password').value;

            if (!username || !password) {
                showError('请输入用户名和密码');
                return;
            }

            document.getElementById('loginBtn').disabled = true;

            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: 'auth',
                    username: username,
                    password: password
                }));
            }
        }

        function logout() {
            isAuthenticated = false;
            sessionId = null;
            shellActive = false;
            showAuth();

            // 清空表单
            document.getElementById('username').value = '';
            document.getElementById('password').value = '';

            // 禁用输入
            document.getElementById('input').disabled = true;
            document.getElementById('startShellBtn').disabled = true;
        }

        function startShell() {
            if (ws && ws.readyState === WebSocket.OPEN && isAuthenticated) {
                ws.send(JSON.stringify({
                    type: 'start_shell',
                    shell: '/bin/bash'
                }));
            }
        }

        function disconnect() {
            if (ws) {
                ws.close();
            }
        }

        function clearTerminal() {
            document.getElementById('terminal').textContent = '';
        }

        function showAuth() {
            document.getElementById('authContainer').style.display = 'block';
            document.getElementById('terminalContainer').style.display = 'none';
        }

        function showTerminal() {
            document.getElementById('authContainer').style.display = 'none';
            document.getElementById('terminalContainer').style.display = 'block';
        }

        function showError(message) {
            const errorElement = document.getElementById('errorMessage');
            errorElement.textContent = '❌ ' + message;
            errorElement.classList.remove('hidden');
        }

        function hideError() {
            document.getElementById('errorMessage').classList.add('hidden');
        }

        function updateStatus(message) {
            document.getElementById('status').textContent = '状态: ' + message;
        }

        function appendToTerminal(text) {
            const terminal = document.getElementById('terminal');
            terminal.textContent += text;
            terminal.scrollTop = terminal.scrollHeight;
        }

        // 处理输入
        document.getElementById('input').addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && shellActive && isAuthenticated) {
                const command = this.value;
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({
                        type: 'input',
                        data: command + '\\n'
                    }));
                    appendToTerminal(command + '\\n');
                    this.value = '';
                }
            }
        });

        // 处理回车键登录
        document.getElementById('password').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                login();
            }
        });

        // 定期心跳
        setInterval(function() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({type: 'ping'}));
            }
        }, 30000);
    </script>
</body>
</html>
"""


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="Web TTY服务器 - 老王出品")
    parser.add_argument('--host', default='0.0.0.0', help='服务器地址')
    parser.add_argument('--port', type=int, default=8889, help='服务器端口')
    parser.add_argument('--serve-html', action='store_true', help='同时提供HTML页面')
    parser.add_argument('--disable-auth', action='store_true', help='禁用认证（不安全）')
    parser.add_argument('--username', default=None, help='认证用户名（默认从环境变量读取）')
    parser.add_argument('--password', default=None, help='认证密码（默认从环境变量读取）')

    args = parser.parse_args()

    # 从环境变量读取认证配置
    enable_auth = not args.disable_auth
    username = args.username or os.getenv('WEB_TTY_USERNAME', 'admin')
    password = args.password or os.getenv('WEB_TTY_PASSWORD', 'password')

    # 创建TTY服务器
    server = WebTTYServer(
        host=args.host,
        port=args.port,
        enable_auth=enable_auth,
        username=username,
        password=password
    )

    # 启动服务器
    ws_server = await server.start_server()

    if args.serve_html:
        # 如果需要提供HTML页面，创建简单的HTTP服务器
        from aiohttp import web

        async def handle_html(request):
            return web.Response(text=HTML_TEMPLATE, content_type='text/html')

        app = web.Application()
        app.router.add_get('/', handle_html)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, args.host, args.port + 1)
        await site.start()

        logger.info(f"📄 HTML页面服务已启动: http://{args.host}:{args.port + 1}")

    try:
        # 保持服务器运行
        await asyncio.Future()  # 永远等待
    except KeyboardInterrupt:
        logger.info("🛑 收到键盘中断，正在关闭服务器...")
    finally:
        await server.shutdown()
        ws_server.close()
        await ws_server.wait_closed()


if __name__ == '__main__':
    asyncio.run(main())