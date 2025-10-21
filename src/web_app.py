#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能文献检索与综述生成系统 - Web接口
提供简单易用的Web界面，替代命令行操作
"""

import os
import sys
import json
import asyncio
import uuid
import threading
import time
import logging
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from werkzeug.utils import secure_filename
from functools import wraps
from flask_socketio import SocketIO, emit

# 导入核心模块
from intelligent_literature_system import IntelligentLiteratureSystem
from terminal_service import terminal_manager

app = Flask(__name__)
app.config['SECRET_KEY'] = 'intelligent-literature-review-2024'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# 初始化SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 认证配置
AUTH_USER = os.getenv('AUTH_USER', 'admin')
AUTH_PASSWORD = os.getenv('AUTH_PASSWORD', 'password')

# 全局系统实例
literature_system = None

# 配置日志
logging.basicConfig(level=logging.INFO)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == AUTH_USER and password == AUTH_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        return render_template('login.html', error='用户名或密码错误')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    """主页面"""
    return render_template('index.html')

@app.route('/terminal')
@login_required
def terminal():
    """Web终端页面"""
    return render_template('terminal.html')

@app.route('/api/search', methods=['POST'])
@login_required
def api_search():
    """文献检索API"""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()

        if not query:
            return jsonify({'error': '请输入研究主题'}), 400

        # 异步执行检索
        result = asyncio.run(literature_system.run_complete_workflow(query, max_results=50, target_articles=20, enable_resume=False))

        return jsonify({
            'success': True,
            'message': f'检索到 {result.get("filtered_count", 0)} 篇文献',
            'data': result
        })

    except Exception as e:
        return jsonify({'error': f'检索失败: {str(e)}'}), 500

@app.route('/api/filter', methods=['POST'])
def api_filter():
    """文献筛选API"""
    try:
        data = request.get_json()
        papers = data.get('papers', [])
        filter_config = data.get('config', {})

        # 执行筛选
        filtered_papers = literature_system.filter_literature(papers, filter_config)

        return jsonify({
            'success': True,
            'message': f'筛选后剩余 {len(filtered_papers)} 篇文献',
            'data': filtered_papers
        })

    except Exception as e:
        return jsonify({'error': f'筛选失败: {str(e)}'}), 500

@app.route('/api/outline', methods=['POST'])
def api_outline():
    """大纲生成API"""
    try:
        data = request.get_json()
        papers = data.get('papers', [])
        topic = data.get('topic', '')

        # 生成大纲
        outline = literature_system.generate_outline(papers, topic)

        return jsonify({
            'success': True,
            'message': '大纲生成成功',
            'data': outline
        })

    except Exception as e:
        return jsonify({'error': f'大纲生成失败: {str(e)}'}), 500

@app.route('/api/review', methods=['POST'])
def api_review():
    """综述生成API"""
    try:
        data = request.get_json()
        papers = data.get('papers', [])
        outline = data.get('outline', '')
        topic = data.get('topic', '')

        # 生成综述
        review = literature_system.generate_review(papers, outline, topic)

        return jsonify({
            'success': True,
            'message': '综述生成成功',
            'data': review
        })

    except Exception as e:
        return jsonify({'error': f'综述生成失败: {str(e)}'}), 500

@app.route('/api/download/<file_type>')
def api_download(file_type):
    """文件下载API"""
    try:
        if file_type == 'docx':
            filename = 'literature_review.docx'
        elif file_type == 'pdf':
            filename = 'literature_review.pdf'
        else:
            return jsonify({'error': '不支持的文件格式'}), 400

        file_path = Path('output') / filename
        if not file_path.exists():
            return jsonify({'error': '文件不存在'}), 404

        return send_file(file_path, as_attachment=True)

    except Exception as e:
        return jsonify({'error': f'下载失败: {str(e)}'}), 500

@app.route('/api/models')
def api_models():
    """获取可用模型列表"""
    try:
        models = [
            "gpt-3.5-turbo", "gpt-4", "claude-3-sonnet", "claude-3-haiku",
            "gemini-pro", "qwen-max", "deepseek-chat", "moonshot-v1-8k"
        ]
        return jsonify({'success': True, 'models': models})
    except Exception as e:
        return jsonify({'error': f'获取模型列表失败: {str(e)}'}), 500

@app.route('/api/init', methods=['POST'])
@login_required
def api_init():
    """系统初始化API"""
    try:
        data = request.get_json()
        model = data.get('model')

        if not model:
            return jsonify({'error': '请选择模型'}), 400

        return jsonify({'success': True, 'message': f'系统已使用 {model} 模型初始化'})
    except Exception as e:
        return jsonify({'error': f'初始化失败: {str(e)}'}), 500

@app.route('/api/status')
def api_status():
    """系统状态API"""
    try:
        status = {
            'system_ready': literature_system is not None,
            'ai_services': literature_system.get_ai_status() if literature_system else {},
            'timestamp': datetime.now().isoformat()
        }
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': f'状态获取失败: {str(e)}'}), 500

async def init_system():
    """初始化系统"""
    global literature_system
    try:
        literature_system = IntelligentLiteratureSystem(interactive_mode=False)
        await literature_system.initialize_components()
        print("✅ 系统初始化成功")
        return True
    except Exception as e:
        print(f"❌ 系统初始化失败: {e}")
        return False

def check_and_init_data():
    """老王我添加的数据检查和初始化函数"""
    print("🔍 老王我正在检查数据文件...")

    data_dir = Path("/app/data")
    prompts_dir = Path("/app/prompts")
    original_data_dir = Path("/app/original_data")
    original_prompts_dir = Path("/app/original_prompts")

    data_files = ["jcr.csv", "zky.csv", "processed_jcr_data.csv", "processed_zky_data.csv"]

    # 检查data文件
    missing_data = []
    for file in data_files:
        if not (data_dir / file).exists():
            missing_data.append(file)

    # 如果有缺失文件，尝试从原始数据恢复
    if missing_data and original_data_dir.exists():
        print(f"🔄 发现缺失数据文件: {missing_data}")
        print("📦 老王我正在从原始数据恢复...")

        for file in missing_data:
            src_file = original_data_dir / file
            dst_file = data_dir / file
            if src_file.exists():
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(src_file, dst_file)
                print(f"✅ 恢复文件: {file}")
            else:
                print(f"⚠️  原始数据中也没有: {file}")

    # 检查prompts配置
    if not (prompts_dir / "prompts_config.yaml").exists() and original_prompts_dir.exists():
        prompts_src = original_prompts_dir / "prompts_config.yaml"
        if prompts_src.exists():
            prompts_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(prompts_src, prompts_dir / "prompts_config.yaml")
            print("✅ 恢复prompts配置文件")

    # 最终验证
    print("🔍 最终数据检查:")
    for file in data_files:
        file_path = data_dir / file
        if file_path.exists():
            size = file_path.stat().st_size
            print(f"✅ {file}: {size:,} bytes")
        else:
            print(f"❌ {file}: 文件不存在")

    prompts_file = prompts_dir / "prompts_config.yaml"
    if prompts_file.exists():
        print(f"✅ prompts_config.yaml: {prompts_file.stat().st_size:,} bytes")
    else:
        print("❌ prompts_config.yaml: 文件不存在")


# ===== WebSocket事件处理 =====

@socketio.on('connect')
def handle_connect():
    """WebSocket连接处理"""
    logging.info(f"🔌 WebSocket客户端连接: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    """WebSocket断开处理"""
    logging.info(f"🔌 WebSocket客户端断开: {request.sid}")

@socketio.on('terminal_connect')
def handle_terminal_connect():
    """终端连接请求"""
    try:
        # 为客户端创建唯一的会话ID
        session_id = str(uuid.uuid4())

        # 创建终端会话
        terminal_session = terminal_manager.create_session(session_id)

        if terminal_session:
            # 启动终端数据读取线程
            def read_terminal():
                while terminal_session.is_active():
                    data = terminal_session.read(timeout=0.1)
                    if data:
                        socketio.emit('terminal_output', {
                            'session_id': session_id,
                            'data': data.decode('utf-8', errors='ignore')
                        }, room=request.sid)
                    time.sleep(0.01)  # 10ms间隔

            thread = threading.Thread(target=read_terminal, daemon=True)
            thread.start()

            # 发送连接成功消息
            socketio.emit('terminal_connected', {
                'session_id': session_id,
                'message': '终端连接成功！'
            }, room=request.sid)

            logging.info(f"🖥️ 终端会话创建成功: {session_id}")

        else:
            socketio.emit('terminal_error', {
                'message': '终端创建失败，请检查系统权限'
            }, room=request.sid)

    except Exception as e:
        logging.error(f"终端连接失败: {e}")
        socketio.emit('terminal_error', {
            'message': f'终端连接失败: {str(e)}'
        }, room=request.sid)

@socketio.on('terminal_input')
def handle_terminal_input(data):
    """终端输入处理"""
    try:
        session_id = data.get('session_id')
        input_data = data.get('data', '')

        if session_id:
            terminal_session = terminal_manager.get_session(session_id)
            if terminal_session:
                # 处理特殊命令（如终端大小调整）
                if data.get('resize'):
                    cols = data['resize'].get('cols', 80)
                    rows = data['resize'].get('rows', 24)
                    terminal_session.resize(cols, rows)
                    logging.debug(f"📐 终端大小调整: {cols}x{rows}")
                else:
                    # 发送输入到终端
                    terminal_session.write(input_data.encode('utf-8'))
            else:
                socketio.emit('terminal_error', {
                    'message': '终端会话已断开'
                }, room=request.sid)
        else:
            socketio.emit('terminal_error', {
                'message': '无效的会话ID'
            }, room=request.sid)

    except Exception as e:
        logging.error(f"终端输入处理失败: {e}")
        socketio.emit('terminal_error', {
            'message': f'终端输入失败: {str(e)}'
        }, room=request.sid)

@socketio.on('terminal_disconnect')
def handle_terminal_disconnect(data):
    """终端断开请求"""
    try:
        session_id = data.get('session_id')
        if session_id:
            terminal_manager.remove_session(session_id)
            logging.info(f"🖥️ 终端会话断开: {session_id}")

    except Exception as e:
        logging.error(f"终端断开处理失败: {e}")


if __name__ == '__main__':
    # 创建必要目录
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    os.makedirs('output', exist_ok=True)

    # 老王我添加的数据检查
    check_and_init_data()

    # 初始化系统
    if asyncio.run(init_system()):
        print("🌐 启动Web服务器...")
        print("📱 访问地址: http://localhost:5000")
        print("🖥️ 终端地址: http://localhost:5000/terminal")
        # 使用SocketIO启动应用
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
    else:
        print("❌ 系统初始化失败，无法启动Web服务")
        sys.exit(1)