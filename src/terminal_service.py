#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web终端服务 - 老王出品，支持浏览器直接连接容器终端
"""

import os
import sys
import pty
import select
import termios
import tty
import fcntl
import struct
import signal
import threading
import time
from typing import Optional, Dict, Any
import logging

class TerminalSession:
    """终端会话管理器"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.master_fd: Optional[int] = None
        self.slave_fd: Optional[int] = None
        self.process: Optional[int] = None
        self.active = False
        self.size = (80, 24)  # 默认终端大小

        logging.info(f"🖥️ 创建终端会话: {session_id}")

    def start(self, shell: str = '/bin/bash') -> bool:
        """启动终端会话"""
        try:
            # 创建伪终端
            self.master_fd, self.slave_fd = pty.openpty()

            # 设置终端大小
            self._set_terminal_size(self.master_fd, self.size[0], self.size[1])

            # 启动shell进程
            self.process = os.fork()

            if self.process == 0:
                # 子进程
                self._start_child_process(shell)
            else:
                # 父进程
                os.close(self.slave_fd)
                self.slave_fd = None
                self.active = True

                logging.info(f"✅ 终端会话启动成功: {self.session_id}, PID: {self.process}")
                return True

        except Exception as e:
            logging.error(f"❌ 终端会话启动失败: {e}")
            self.cleanup()
            return False

    def _start_child_process(self, shell: str):
        """子进程处理"""
        if self.slave_fd is None:
            return

        # 将slave_fd设置为标准输入输出
        os.dup2(self.slave_fd, sys.stdin.fileno())
        os.dup2(self.slave_fd, sys.stdout.fileno())
        os.dup2(self.slave_fd, sys.stderr.fileno())

        # 关闭不需要的文件描述符
        if self.master_fd:
            os.close(self.master_fd)
        if self.slave_fd:
            os.close(self.slave_fd)

        # 启动shell
        try:
            # 设置环境变量
            env = os.environ.copy()
            env['TERM'] = 'xterm-256color'
            env['PS1'] = '\\[\\e[32m\\]\\u@container\\[\\e[0m\\]:\\[\\e[34m\\]\\w\\[\\e[0m\\]\\$ '

            os.execve(shell, [shell], env)
        except Exception as e:
            logging.error(f"Shell启动失败: {e}")
            os._exit(1)

    def _set_terminal_size(self, fd: int, cols: int, rows: int):
        """设置终端大小"""
        try:
            # TIOCSWINSZ ioctl调用
            winsize = struct.pack('HHHH', rows, cols, 0, 0)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
        except Exception as e:
            logging.error(f"设置终端大小失败: {e}")

    def resize(self, cols: int, rows: int):
        """调整终端大小"""
        if self.master_fd:
            self.size = (cols, rows)
            self._set_terminal_size(self.master_fd, cols, rows)
            logging.debug(f"📐 终端大小调整: {cols}x{rows}")

    def write(self, data: bytes) -> int:
        """向终端写入数据"""
        if not self.active or self.master_fd is None:
            return -1

        try:
            return os.write(self.master_fd, data)
        except OSError as e:
            logging.error(f"写入终端失败: {e}")
            self.cleanup()
            return -1

    def read(self, timeout: float = 0.1) -> bytes:
        """从终端读取数据"""
        if not self.active or self.master_fd is None:
            return b''

        try:
            # 使用select检查是否有数据可读
            ready, _, _ = select.select([self.master_fd], [], [], timeout)
            if ready:
                data = os.read(self.master_fd, 4096)
                return data
        except OSError as e:
            logging.error(f"读取终端失败: {e}")
            self.cleanup()

        return b''

    def cleanup(self):
        """清理终端会话"""
        if self.active:
            self.active = False

        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except:
                pass
            self.master_fd = None

        if self.slave_fd is not None:
            try:
                os.close(self.slave_fd)
            except:
                pass
            self.slave_fd = None

        if self.process is not None:
            try:
                # 发送SIGTERM信号
                os.kill(self.process, signal.SIGTERM)
                # 等待进程结束
                os.waitpid(self.process, 0)
            except:
                pass
            self.process = None

        logging.info(f"🧹 终端会话已清理: {self.session_id}")

    def is_active(self) -> bool:
        """检查会话是否活跃"""
        if not self.active or self.process is None:
            return False

        # 检查进程是否还存在
        try:
            os.kill(self.process, 0)
            return True
        except OSError:
            self.active = False
            return False


class TerminalManager:
    """终端管理器"""

    def __init__(self):
        self.sessions: Dict[str, TerminalSession] = {}
        self.lock = threading.Lock()
        logging.info("🖥️ 终端管理器初始化完成")

    def create_session(self, session_id: str) -> Optional[TerminalSession]:
        """创建新的终端会话"""
        with self.lock:
            if session_id in self.sessions:
                # 清理旧会话
                self.sessions[session_id].cleanup()

            session = TerminalSession(session_id)
            if session.start():
                self.sessions[session_id] = session
                return session
            else:
                return None

    def get_session(self, session_id: str) -> Optional[TerminalSession]:
        """获取终端会话"""
        with self.lock:
            session = self.sessions.get(session_id)
            if session and session.is_active():
                return session
            elif session:
                # 清理无效会话
                session.cleanup()
                del self.sessions[session_id]
            return None

    def remove_session(self, session_id: str):
        """移除终端会话"""
        with self.lock:
            if session_id in self.sessions:
                self.sessions[session_id].cleanup()
                del self.sessions[session_id]
                logging.info(f"🗑️ 终端会话已移除: {session_id}")

    def cleanup_inactive_sessions(self):
        """清理不活跃的会话"""
        with self.lock:
            inactive_sessions = []
            for session_id, session in self.sessions.items():
                if not session.is_active():
                    inactive_sessions.append(session_id)

            for session_id in inactive_sessions:
                self.sessions[session_id].cleanup()
                del self.sessions[session_id]
                logging.info(f"🧹 清理不活跃会话: {session_id}")

    def get_session_count(self) -> int:
        """获取活跃会话数量"""
        with self.lock:
            return len([s for s in self.sessions.values() if s.is_active()])


# 全局终端管理器实例
terminal_manager = TerminalManager()