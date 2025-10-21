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
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename

# 导入核心模块
from intelligent_literature_system import IntelligentLiteratureSystem

app = Flask(__name__)
app.config['SECRET_KEY'] = 'intelligent-literature-review-2024'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# 全局系统实例
literature_system = None

@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')

@app.route('/api/search', methods=['POST'])
def api_search():
    """文献检索API"""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()

        if not query:
            return jsonify({'error': '请输入研究主题'}), 400

        # 异步执行检索
        result = asyncio.run(literature_system.search_literature(query))

        return jsonify({
            'success': True,
            'message': f'检索到 {len(result.get("papers", []))} 篇文献',
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

def init_system():
    """初始化系统"""
    global literature_system
    try:
        literature_system = IntelligentLiteratureSystem()
        print("✅ 系统初始化成功")
        return True
    except Exception as e:
        print(f"❌ 系统初始化失败: {e}")
        return False

if __name__ == '__main__':
    # 创建必要目录
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    os.makedirs('output', exist_ok=True)

    # 初始化系统
    if init_system():
        print("🌐 启动Web服务器...")
        print("📱 访问地址: http://localhost:5000")
        app.run(host='0.0.0.0', port=5000, debug=True)
    else:
        print("❌ 系统初始化失败，无法启动Web服务")
        sys.exit(1)