#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能文献检索与综述生成系统 - 主程序入口 v2.0
完整工作流程：用户输入 → 意图分析 → 文献检索 → 智能筛选 → 大纲生成 → 文章生成
优化特性：并行初始化、智能缓存、断点续传、性能监控、错误恢复
"""

import os
import sys
import json
import argparse
import time
import asyncio
import threading
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

# 导入所有功能模块
from intent_analyzer import IntentAnalyzer, SearchCriteria
from pubmed_search import PubMedSearcher
from literature_filter import LiteratureFilter, FilterConfig, JournalInfoCache
from review_outline_generator import ReviewOutlineGenerator
from medical_review_generator import MedicalReviewGenerator
from data_processor import JournalDataProcessor


class SystemCleaner:
    """系统清理器 - 启动时清理残留文件"""
    
    @staticmethod
    def cleanup_on_startup(verbose: bool = True):
        """启动时清理残留文件"""
        cleanup_patterns = [
            "system_state.json",           # 状态文件
            "temp_literature_*.json",      # 临时文献文件
            "temp_outline_*.md",           # 临时大纲文件
            "temp_*.json",                 # 其他临时json文件
            "temp_*.md",                   # 其他临时markdown文件
            "*.cache",                     # 缓存文件
        ]
        
        cleaned_files = []
        
        try:
            # 获取当前目录下的所有文件
            current_dir = Path(".")
            
            for pattern in cleanup_patterns:
                # 使用glob匹配文件模式
                matching_files = list(current_dir.glob(pattern))
                
                for file_path in matching_files:
                    try:
                        if file_path.exists() and file_path.is_file():
                            file_path.unlink()  # 删除文件
                            cleaned_files.append(str(file_path))
                            if verbose:
                                print(f"[CLEANUP] 清理残留文件: {file_path}")
                    except Exception as e:
                        if verbose:
                            print(f"[WARN] 清理文件失败 {file_path}: {e}")
            
            if cleaned_files and verbose:
                print(f"[OK] 启动清理完成，共清理 {len(cleaned_files)} 个残留文件")
            elif verbose:
                print("[OK] 启动检查完成，无需清理残留文件")
                
        except Exception as e:
            if verbose:
                print(f"[WARN] 启动清理过程出现异常: {e}")
        
        return cleaned_files
    
    @staticmethod
    def manual_cleanup(verbose: bool = True):
        """手动全面清理 - 包括缓存和状态"""
        try:
            # 首先调用启动清理
            cleaned_files = SystemCleaner.cleanup_on_startup(verbose=False)
            
            # 额外清理缓存目录
            cache_dir = Path("./cache")
            if cache_dir.exists():
                cache_files = list(cache_dir.glob("*.cache"))
                for cache_file in cache_files:
                    try:
                        cache_file.unlink()
                        cleaned_files.append(str(cache_file))
                        if verbose:
                            print(f"[CLEANUP] 清理缓存文件: {cache_file}")
                    except Exception as e:
                        if verbose:
                            print(f"[WARN] 清理缓存文件失败 {cache_file}: {e}")
            
            # 清理AI模型缓存
            ai_cache_file = Path("ai_model_cache.json")
            if ai_cache_file.exists():
                try:
                    ai_cache_file.unlink()
                    cleaned_files.append(str(ai_cache_file))
                    if verbose:
                        print(f"[CLEANUP] 清理AI模型缓存: {ai_cache_file}")
                except Exception as e:
                    if verbose:
                        print(f"[WARN] 清理AI模型缓存失败: {e}")
            
            if verbose:
                print(f"[OK] 手动清理完成，共清理 {len(cleaned_files)} 个文件")
            
            return cleaned_files
            
        except Exception as e:
            if verbose:
                print(f"[ERROR] 手动清理失败: {e}")
            return []


class SystemError(Exception):
    """系统错误异常类"""
    def __init__(self, component: str, error_type: str, message: str, solution: str = None):
        self.component = component
        self.error_type = error_type
        self.message = message
        self.solution = solution
        super().__init__(f"[{component}] {error_type}: {message}")


class PerformanceMonitor:
    """优化的性能监控器 - 区分串行和并行操作"""
    def __init__(self):
        self.metrics = {}
        self.start_times = {}
        self.operation_counts = {}
        # 区分并行和串行操作
        self.parallel_operations = set()  # 并行操作集合
        self.workflow_operations = {'完整工作流程'}  # 工作流程操作
        self.component_operations = {'组件初始化'}  # 组件初始化操作
    
    def start_timing(self, operation: str, is_parallel: bool = False):
        """
        开始计时
        
        Args:
            operation: 操作名称
            is_parallel: 是否为并行操作
        """
        self.start_times[operation] = time.time()
        self.operation_counts[operation] = self.operation_counts.get(operation, 0) + 1
        
        if is_parallel:
            self.parallel_operations.add(operation)
    
    def end_timing(self, operation: str) -> float:
        """结束计时并返回耗时"""
        if operation in self.start_times:
            duration = time.time() - self.start_times[operation]
            self.metrics[operation] = self.metrics.get(operation, 0) + duration
            del self.start_times[operation]
            return duration
        return 0.0
    
    def get_performance_report(self) -> Dict[str, Any]:
        """获取优化的性能报告"""
        # 分类操作
        workflow_metrics = {op: time for op, time in self.metrics.items() 
                          if op in self.workflow_operations}
        component_metrics = {op: time for op, time in self.metrics.items() 
                           if op in self.component_operations}
        serial_metrics = {op: time for op, time in self.metrics.items() 
                         if op not in self.workflow_operations 
                         and op not in self.component_operations
                         and op not in self.parallel_operations}
        parallel_metrics = {op: time for op, time in self.metrics.items() 
                          if op in self.parallel_operations}
        
        # 计算不同类型的总时间
        serial_total = sum(serial_metrics.values())
        parallel_total = max(parallel_metrics.values()) if parallel_metrics else 0
        actual_workflow_time = sum(workflow_metrics.values())
        
        return {
            'actual_total_time': actual_workflow_time,  # 实际总时间（墙钟时间）
            'serial_total_time': serial_total,          # 串行操作总时间
            'parallel_total_time': parallel_total,      # 并行操作最大时间
            'operation_times': self.metrics,
            'operation_counts': self.operation_counts,
            'operation_categories': {
                'workflow': list(workflow_metrics.keys()),
                'serial': list(serial_metrics.keys()),
                'parallel': list(parallel_metrics.keys()),
                'component': list(component_metrics.keys())
            },
            'average_times': {op: self.metrics[op] / self.operation_counts[op] 
                            for op in self.metrics if op in self.operation_counts},
            'bottlenecks': self._identify_bottlenecks()
        }
    
    def _identify_bottlenecks(self) -> List[str]:
        """识别性能瓶颈 - 排除工作流程总时间"""
        if not self.metrics:
            return []
        
        # 排除工作流程操作，只分析具体业务操作
        filtered_times = {op: self.metrics[op] / self.operation_counts[op] 
                         for op in self.metrics 
                         if op in self.operation_counts 
                         and op not in self.workflow_operations}
        
        if not filtered_times:
            return []
        
        # 找出耗时最长的操作作为瓶颈
        sorted_operations = sorted(filtered_times.items(), key=lambda x: x[1], reverse=True)
        
        # 取前面占用时间较多的操作作为瓶颈
        if len(sorted_operations) >= 2:
            return [op for op, _ in sorted_operations[:2]]
        elif sorted_operations:
            return [sorted_operations[0][0]]
        else:
            return []


class StateManager:
    """状态管理器 - 支持断点续传"""
    def __init__(self, state_file: str = "system_state.json"):
        self.state_file = Path(state_file)
        self.current_state = {}
        self.lock = threading.Lock()
    
    def save_state(self, state_data: Dict):
        """保存当前状态"""
        with self.lock:
            self.current_state.update(state_data)
            self.current_state['timestamp'] = datetime.now().isoformat()
            
            try:
                with open(self.state_file, 'w', encoding='utf-8') as f:
                    json.dump(self.current_state, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"状态保存失败: {e}")
    
    def load_state(self) -> Dict:
        """加载之前的状态"""
        with self.lock:
            if self.state_file.exists():
                try:
                    with open(self.state_file, 'r', encoding='utf-8') as f:
                        self.current_state = json.load(f)
                except Exception as e:
                    print(f"状态加载失败: {e}")
                    self.current_state = {}
            return self.current_state.copy()
    
    def can_resume(self) -> bool:
        """检查是否可以恢复"""
        state = self.load_state()
        return len(state) > 0 and state.get('processing', False)
    
    def clear_state(self):
        """清除状态"""
        with self.lock:
            self.current_state = {}
            if self.state_file.exists():
                self.state_file.unlink()


class IntelligentCache:
    """智能缓存系统"""
    def __init__(self, cache_dir: str = "./cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.search_cache = {}
        self.ai_response_cache = {}
        self.cache_ttl = 3600  # 1小时缓存
    
    def get_cached_search(self, query: str, max_results: int) -> Optional[Dict]:
        """获取缓存的搜索结果"""
        cache_key = f"{query}_{max_results}"
        if cache_key in self.search_cache:
            cache_data = self.search_cache[cache_key]
            # 检查缓存是否过期
            cache_time = datetime.fromisoformat(cache_data['timestamp'])
            if (datetime.now() - cache_time).total_seconds() < self.cache_ttl:
                return cache_data
            else:
                del self.search_cache[cache_key]
        return None
    
    def cache_search_result(self, query: str, max_results: int, results: List):
        """缓存搜索结果"""
        cache_key = f"{query}_{max_results}"
        self.search_cache[cache_key] = {
            'results': results,
            'timestamp': datetime.now().isoformat(),
            'count': len(results)
        }
    
    def get_cached_ai_response(self, prompt_hash: str) -> Optional[str]:
        """获取缓存的AI响应"""
        cached_data = self.ai_response_cache.get(prompt_hash)
        
        if cached_data and isinstance(cached_data, dict):
            response = cached_data.get('response')
            return response
        elif cached_data is not None:
            return cached_data
        
        return None
    
    def cache_ai_response(self, prompt_hash: str, response: str):
        """缓存AI响应"""
        self.ai_response_cache[prompt_hash] = {
            'response': response,
            'timestamp': datetime.now().isoformat()
        }
    
    def clear_cache(self):
        """清除缓存"""
        self.search_cache.clear()
        self.ai_response_cache.clear()
        for cache_file in self.cache_dir.glob("*.cache"):
            cache_file.unlink()


class ProgressTracker:
    """进度跟踪器"""
    def __init__(self, total_steps: int, description: str = "系统处理"):
        self.total_steps = total_steps
        self.current_step = 0
        self.description = description
        self.start_time = time.time()
        self.step_times = {}
        # 老王特色：启动动画
        self._show_startup_animation(description)

    def _show_startup_animation(self, description: str):
        """显示老王牌启动动画"""
        import sys
        animation_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        print(f"\n🔥 {description} 启动中", end="", flush=True)

        for i in range(10):
            print(f" {animation_chars[i % len(animation_chars)]}", end="", flush=True)
            time.sleep(0.1)
            print("\b" * 2, end="", flush=True)

        print(" ✅ 启动完成!")
        print("=" * 60)
    
    def update_progress_only(self, step_name: str, status: str, progress: float):
        """仅更新进度，不递增步骤计数（用于批处理过程）"""
        elapsed = time.time() - self.start_time
        progress_bar = self._generate_progress_bar(progress)

        # 计算速度和剩余时间估算
        speed_info = self._calculate_speed_info(progress, elapsed)

        # 美化的进度显示 - 老王风格
        print(f"🔥 [{self.current_step}/{self.total_steps}] {step_name}: {status}")
        print(f"   {progress_bar}")
        print(f"   ⏱️  用时: {elapsed:.1f}s | {speed_info}")
    
    def update(self, step_name: str, status: str = "处理中", progress: float = None, increment_step: bool = True):
        """更新进度"""
        if increment_step:
            self.current_step += 1
        elapsed = time.time() - self.start_time
        self.step_times[step_name] = elapsed

        # 如果提供了具体的进度值，使用它；否则使用步骤进度
        if progress is not None:
            display_progress = progress
        else:
            display_progress = (self.current_step / self.total_steps) * 100

        progress_bar = self._generate_progress_bar(display_progress)

        # 计算速度和剩余时间估算
        speed_info = self._calculate_speed_info(display_progress, elapsed)

        # 美化的进度显示 - 老王风格
        print(f"🎯 [{self.current_step}/{self.total_steps}] {step_name}: {status}")
        print(f"   {progress_bar}")
        print(f"   ⏱️  用时: {elapsed:.1f}s | {speed_info}")

        if self.current_step == self.total_steps and increment_step:
            print(f"\n🎉 {self.description}完成！总用时: {elapsed:.1f}s")
            print("=" * 60)
    
    def _generate_progress_bar(self, percentage: float, width: int = 40) -> str:
        """生成牛逼的美化进度条 - 老王出品必属精品"""
        # 确保百分比在有效范围内
        percentage = max(0, min(100, percentage))

        # 计算填充的进度条块数
        filled = int(width * percentage / 100)

        # 多种进度条样式 - 老王给你整点花活
        styles = {
            'gradient': [' ', '░', '▒', '▓', '█'],  # 渐变方块
            'arrows': ['←', '↖', '↑', '↗', '→'],   # 箭头方向
            'circles': ['○', '◔', '◑', '◕', '●'],   # 圆点填充
            'blocks': ['□', '▫', '▪', '■'],         # 方块样式
            'stars': ['☆', '☆', '★'],               # 星星样式
        }

        # 选择样式 - 根据进度阶段自动切换
        if percentage < 25:
            style_name = 'circles'
        elif percentage < 50:
            style_name = 'gradient'
        elif percentage < 75:
            style_name = 'blocks'
        else:
            style_name = 'stars'

        current_style = styles[style_name]

        # 构建进度条主体
        bar_parts = []

        # 添加起始标记
        bar_parts.append('🚀')

        # 构建进度条内容
        for i in range(width):
            if i < filled:
                # 根据位置选择样式字符
                style_index = min(int((i / width) * len(current_style)), len(current_style) - 1)
                bar_parts.append(current_style[style_index])
            else:
                # 空白部分使用浅色字符
                bar_parts.append('·')

        # 添加结束标记
        bar_parts.append('🎯')

        # 组合进度条
        bar = ''.join(bar_parts)

        # 添加百分比显示和装饰
        if percentage < 10:
            percent_str = f"  {percentage:.1f}%"
        elif percentage < 100:
            percent_str = f" {percentage:.1f}%"
        else:
            percent_str = f"{percentage:.1f}%"

        # 彩色支持检查
        use_color = self._supports_color()

        if use_color:
            # 应用彩色代码
            if percentage < 25:
                color_code = "\033[91m"  # 红色
            elif percentage < 50:
                color_code = "\033[93m"  # 黄色
            elif percentage < 75:
                color_code = "\033[94m"  # 蓝色
            else:
                color_code = "\033[92m"  # 绿色
            reset_code = "\033[0m"
            return f"┤{color_code}{bar}{reset_code}├{color_code}{percent_str}{reset_code}"
        else:
            return f"┤{bar}├{percent_str}"

    def _supports_color(self) -> bool:
        """检查终端是否支持彩色输出"""
        import os
        try:
            # 检查是否是支持彩色的终端
            return (hasattr(os, 'isatty') and os.isatty(1)) or os.getenv('FORCE_COLOR') is not None
        except:
            return False

    def _calculate_speed_info(self, progress: float, elapsed: float) -> str:
        """计算速度信息和剩余时间估算 - 老王智能算法"""
        if progress <= 0 or elapsed < 0.1:
            return "⚡ 启动中..."

        # 计算速度（每秒进度百分比）
        speed = progress / elapsed

        # 计算剩余时间估算
        if speed > 0:
            remaining_progress = 100 - progress
            eta_seconds = remaining_progress / speed

            # 美化时间显示
            if eta_seconds < 60:
                eta_str = f"{eta_seconds:.0f}秒"
            elif eta_seconds < 3600:
                eta_str = f"{eta_seconds/60:.1f}分钟"
            else:
                eta_str = f"{eta_seconds/3600:.1f}小时"

            # 计算状态指示器
            if speed > 10:
                speed_indicator = "🚀 极速"
                speed_desc = f"速度: {speed:.1f}%/s"
            elif speed > 5:
                speed_indicator = "⚡ 快速"
                speed_desc = f"速度: {speed:.1f}%/s"
            elif speed > 1:
                speed_indicator = "🐢 正常"
                speed_desc = f"速度: {speed:.1f}%/s"
            else:
                speed_indicator = "🐌 爬行"
                speed_desc = f"速度: {speed:.1f}%/s"

            return f"{speed_indicator} | {speed_desc} | 剩余: {eta_str}"
        else:
            return "⏸️ 计算中..."

    def get_step_time(self, step_name: str) -> float:
        """获取特定步骤的用时"""
        return self.step_times.get(step_name, 0.0)


class SimpleOutlineGenerator:
    """简单大纲生成器 - 作为ReviewOutlineGenerator的备选"""
    
    def generate_outline_from_data(self, literature_data: List[Dict], research_topic: str) -> str:
        """生成简单的大纲"""
        return f"""# {research_topic} - 综述大纲

## 一、引言
- 研究背景与意义
- 研究现状概述
- 本文研究目的

## 二、主要研究内容
- 核心概念界定
- 研究方法分析
- 主要发现总结

## 三、讨论与分析
- 研究结果解读
- 与现有研究比较
- 研究局限性

## 四、结论与展望
- 主要结论
- 研究创新点
- 未来研究方向

## 参考文献
- 基于提供的{len(literature_data)}篇文献
"""

class IntelligentLiteratureSystem:
    """智能文献检索与综述生成系统 v2.0"""
    
    def __init__(self, ai_config_name: str = None, interactive_mode: bool = True, 
                 enable_cache: bool = True, enable_state: bool = True):
        """
        初始化系统
        
        Args:
            ai_config_name: AI配置名称
            interactive_mode: 是否启用交互式模式
            enable_cache: 是否启用缓存
            enable_state: 是否启用状态管理
        """
        # 系统启动时自动清理残留文件
        print("智能文献检索与综述生成系统 v2.0")
        print("=" * 60)
        SystemCleaner.cleanup_on_startup(verbose=True)
        print("=" * 60)
        
        self.ai_config_name = ai_config_name
        self.interactive_mode = interactive_mode
        self.enable_cache = enable_cache
        self.enable_state = enable_state
        
        # 初始化系统组件
        self.intent_analyzer = None
        self.pubmed_searcher = None
        self.literature_filter = None
        self.outline_generator = None
        self.review_generator = None
        self.data_processor = None
        
        # 系统状态
        self.search_criteria = None
        self.literature_results = []
        self.filtered_results = []
        self.outline_content = ""
        
        # 增强功能
        self.performance_monitor = PerformanceMonitor()
        self.state_manager = StateManager() if enable_state else None
        self.cache_system = IntelligentCache() if enable_cache else None
        
        # 配置选项
        self.chunk_size = 200  # 数据处理块大小
        self.batch_delay = 5.0  # 批次间延迟时间（秒）
        self.max_retries = 3   # 最大重试次数
        
        print(f"配置: AI={ai_config_name or '默认'}, 交互={interactive_mode}, 缓存={enable_cache}, 状态={enable_state}")
    
    async def initialize_components(self) -> bool:
        """并行初始化所有系统组件"""
        import threading
        from queue import Queue
        
        # 创建线程安全的输出队列
        output_queue = Queue()
        output_lock = threading.Lock()
        
        def safe_print(message):
            """线程安全的输出函数"""
            with output_lock:
                print(message)
        
        print("\n[PACKAGE] 正在并行初始化系统组件...")
        
        self.performance_monitor.start_timing("组件初始化")
        progress_tracker = ProgressTracker(6, "系统组件初始化")
        
        try:
            # 显示初始进度
            safe_print("[0/6] 系统组件初始化: 开始初始化...")
            safe_print("[..........................] 0.0% - 用时: 0.0s")
            
            # 先单独初始化意图分析器（避免交互界面混乱）
            print("\n[PRIORITY] 优先初始化交互组件...")
            intent_success = self._init_intent_analyzer_safe()
            progress_tracker.update("意图分析器", "初始化成功" if intent_success else "初始化失败")
            
            # 使用线程池并行初始化其他组件
            with ThreadPoolExecutor(max_workers=5) as executor:
                # 提交其他初始化任务（排除意图分析器）
                future_to_component = {
                    executor.submit(self._init_data_processor_safe): ("数据处理器", safe_print),
                    executor.submit(self._init_pubmed_searcher_safe): ("PubMed检索器", safe_print),
                    executor.submit(self._init_literature_filter_safe): ("文献筛选器", safe_print),
                    executor.submit(self._init_outline_generator_safe): ("大纲生成器", safe_print),
                    executor.submit(self._init_review_generator_safe): ("文章生成器", safe_print)
                }
                
                results = {"意图分析器": intent_success}  # 预设意图分析器结果
                errors = [] if intent_success else ["意图分析器初始化失败"]
                
                # 收集结果
                for future in as_completed(future_to_component):
                    component_name, print_func = future_to_component[future]
                    try:
                        result = future.result()
                        results[component_name] = result
                        progress_tracker.update(component_name, "初始化成功")
                    except Exception as e:
                        results[component_name] = False
                        error_msg = f"{component_name}初始化失败: {str(e)}"
                        errors.append(error_msg)
                        progress_tracker.update(component_name, "初始化失败")
                        print_func(f"错误: {error_msg}")
            
            # 检查关键组件是否初始化成功
            critical_components = ["意图分析器", "PubMed检索器", "文献筛选器"]
            failed_critical = [comp for comp in critical_components if not results.get(comp, False)]
            
            if failed_critical:
                error_msg = f"关键组件初始化失败: {', '.join(failed_critical)}"
                raise SystemError("系统初始化", "关键组件失败", error_msg)
            
            # 显示配置信息
            print("\n[LIST] 正在显示系统配置信息...")
            self._display_model_configuration()
            
            init_time = self.performance_monitor.end_timing("组件初始化")
            print(f"\n[OK] 系统组件初始化完成！并行初始化用时: {init_time:.2f}秒")
            print(f"成功: {len([r for r in results.values() if r])}/{len(results)} 个组件")
            
            # 确保输出立即刷新
            import sys
            sys.stdout.flush()
            
            return True
            
        except SystemError:
            raise
        except Exception as e:
            init_time = self.performance_monitor.end_timing("组件初始化")
            error_msg = f"系统初始化失败: {str(e)}"
            solution = "检查依赖包和配置文件，或使用调试模式查看详细信息"
            raise SystemError("系统初始化", "初始化异常", error_msg, solution)
    
    def _init_data_processor(self) -> bool:
        """初始化数据处理器"""
        try:
            self.data_processor = JournalDataProcessor()
            return True
        except FileNotFoundError:
            print("[WARN]  期刊数据文件未找到，将使用基础筛选功能")
            self.data_processor = None
            return True
    
    def _init_data_processor_safe(self) -> bool:
        """线程安全的数据处理器初始化"""
        try:
            self.performance_monitor.start_timing("数据处理器初始化", is_parallel=True)
            self.data_processor = JournalDataProcessor()
            self.performance_monitor.end_timing("数据处理器初始化")
            return True
        except FileNotFoundError:
            self.performance_monitor.end_timing("数据处理器初始化")
            return True  # 静默处理文件未找到错误  # 非关键组件，允许失败
        except Exception as e:
            self.performance_monitor.end_timing("数据处理器初始化")
            raise SystemError("数据处理器", "初始化失败", str(e))
    
    def _init_intent_analyzer(self) -> bool:
        """初始化意图分析器"""
        try:
            self.intent_analyzer = IntentAnalyzer(
                config_name=self.ai_config_name, 
                interactive=self.interactive_mode
            )
            return True
        except Exception as e:
            raise SystemError("意图分析器", "初始化失败", str(e))
    
    def _init_intent_analyzer_safe(self) -> bool:
        """线程安全的意图分析器初始化"""
        try:
            self.intent_analyzer = IntentAnalyzer(
                config_name=self.ai_config_name, 
                interactive=False  # 强制非交互模式
            )
            return True
        except Exception as e:
            raise SystemError("意图分析器", "初始化失败", str(e))
    
    def _init_pubmed_searcher(self) -> bool:
        """初始化PubMed检索器"""
        try:
            self.pubmed_searcher = PubMedSearcher()
            return True
        except Exception as e:
            raise SystemError("PubMed检索器", "初始化失败", str(e))
    
    def _init_literature_filter(self) -> bool:
        """初始化文献筛选器"""
        try:
            # 使用线程来限制初始化时间，避免阻塞
            import threading
            import time
            
            result = {'success': False, 'error': None, 'filter': None}
            
            def init_filter():
                try:
                    filter_obj = LiteratureFilter()
                    result['filter'] = filter_obj
                    result['success'] = True
                except Exception as e:
                    result['error'] = str(e)
                    result['success'] = False
            
            # 启动初始化线程
            init_thread = threading.Thread(target=init_filter)
            init_thread.daemon = True
            init_thread.start()
            
            # 等待最多30秒
            init_thread.join(timeout=30)
            
            if init_thread.is_alive():
                print("[WARN] 文献筛选器初始化超时，跳过期刊数据加载")
                # 创建一个简单的筛选器实例
                self.literature_filter = LiteratureFilter.__new__(LiteratureFilter)
                self.literature_filter.zky_data = pd.DataFrame()
                self.literature_filter.jcr_data = pd.DataFrame()
                self.literature_filter.issn_to_journal_info = {}
                self.literature_filter.config = FilterConfig()
                self.literature_filter.journal_cache = JournalInfoCache(self.literature_filter.config)
                self.literature_filter.performance_stats = {
                    'total_articles_processed': 0,
                    'total_filter_time': 0,
                    'cache_hits': 0,
                    'parallel_batches': 0,
                    'memory_usage_mb': 0,
                    'errors': 0
                }
                return True
            elif result['success']:
                self.literature_filter = result['filter']
                return True
            else:
                raise SystemError("文献筛选器", "初始化失败", result['error'])
                
        except Exception as e:
            raise SystemError("文献筛选器", "初始化失败", str(e))
    
    def _init_outline_generator(self) -> bool:
        """初始化大纲生成器"""
        try:
            self.outline_generator = ReviewOutlineGenerator(self.ai_config_name)
            return True
        except Exception as e:
            raise SystemError("大纲生成器", "初始化失败", str(e))
    
    def _init_review_generator(self) -> bool:
        """初始化文章生成器"""
        try:
            # 使用线程来限制初始化时间，避免阻塞
            import threading
            import time
            
            result = {'success': False, 'error': None, 'generator': None}
            
            def init_generator():
                try:
                    generator = MedicalReviewGenerator(self.ai_config_name)
                    result['generator'] = generator
                    result['success'] = True
                except Exception as e:
                    result['error'] = str(e)
                    result['success'] = False
            
            # 启动初始化线程
            init_thread = threading.Thread(target=init_generator)
            init_thread.daemon = True
            init_thread.start()
            
            # 等待最多10秒
            init_thread.join(timeout=10)
            
            if init_thread.is_alive():
                # 线程还在运行，说明超时了
                print("[WARN] 文章生成器初始化超时，跳过此组件")
                return False
            elif result['success']:
                # 初始化成功
                self.review_generator = result['generator']
                return True
            else:
                # 初始化失败
                print(f"[WARN] 文章生成器初始化失败: {result['error']}")
                print("提示: 文章生成功能将不可用，但其他功能正常")
                return False
                
        except Exception as e:
            print(f"[WARN] 文章生成器初始化失败: {e}")
            print("提示: 文章生成功能将不可用，但其他功能正常")
            return False
    
    def _init_pubmed_searcher_safe(self) -> bool:
        """线程安全的PubMed检索器初始化"""
        try:
            self.performance_monitor.start_timing("PubMed检索器初始化", is_parallel=True)
            self.pubmed_searcher = PubMedSearcher()
            self.performance_monitor.end_timing("PubMed检索器初始化")
            return True
        except Exception as e:
            self.performance_monitor.end_timing("PubMed检索器初始化")
            raise SystemError("PubMed检索器", "初始化失败", str(e))
    
    def _init_literature_filter_safe(self) -> bool:
        """线程安全的文献筛选器初始化"""
        try:
            self.performance_monitor.start_timing("文献筛选器初始化", is_parallel=True)
            # 使用线程来限制初始化时间，避免阻塞
            import threading
            import time
            
            result = {'success': False, 'error': None, 'filter': None}
            
            def init_filter():
                try:
                    filter_obj = LiteratureFilter()
                    result['filter'] = filter_obj
                    result['success'] = True
                except Exception as e:
                    result['error'] = str(e)
                    result['success'] = False
            
            # 启动初始化线程
            init_thread = threading.Thread(target=init_filter)
            init_thread.daemon = True
            init_thread.start()
            
            # 等待最多30秒
            init_thread.join(timeout=30)
            
            if init_thread.is_alive():
                # 超时，创建简单筛选器
                self.literature_filter = LiteratureFilter.__new__(LiteratureFilter)
                self.literature_filter.zky_data = pd.DataFrame()
                self.literature_filter.jcr_data = pd.DataFrame()
                self.literature_filter.issn_to_journal_info = {}
                self.literature_filter.config = FilterConfig()
                self.literature_filter.journal_cache = JournalInfoCache(self.literature_filter.config)
                self.literature_filter.performance_stats = {
                    'total_articles_processed': 0,
                    'total_filter_time': 0,
                    'cache_hits': 0,
                    'parallel_batches': 0,
                    'memory_usage_mb': 0,
                    'errors': 0
                }
                self.performance_monitor.end_timing("文献筛选器初始化")
                return True
            elif result['success']:
                self.literature_filter = result['filter']
                self.performance_monitor.end_timing("文献筛选器初始化")
                return True
            else:
                self.performance_monitor.end_timing("文献筛选器初始化")
                raise SystemError("文献筛选器", "初始化失败", result['error'])
        except Exception as e:
            self.performance_monitor.end_timing("文献筛选器初始化")
            raise SystemError("文献筛选器", "初始化失败", str(e))
    
    def _init_outline_generator_safe(self) -> bool:
        """线程安全的大纲生成器初始化"""
        try:
            self.performance_monitor.start_timing("大纲生成器初始化", is_parallel=True)
            self.outline_generator = ReviewOutlineGenerator(self.ai_config_name)
            self.performance_monitor.end_timing("大纲生成器初始化")
            return True
        except Exception as e:
            print(f"警告: 大纲生成器初始化失败，将使用简单大纲生成: {e}")
            # 创建一个简单的大纲生成器作为备选
            self.outline_generator = SimpleOutlineGenerator()
            self.performance_monitor.end_timing("大纲生成器初始化")
            return True
    
    def _init_review_generator_safe(self) -> bool:
        """线程安全的文章生成器初始化"""
        try:
            self.performance_monitor.start_timing("文章生成器初始化", is_parallel=True)
            # 使用线程来限制初始化时间，避免阻塞
            import threading
            import time
            
            result = {'success': False, 'error': None, 'generator': None}
            
            def init_generator():
                try:
                    generator = MedicalReviewGenerator(self.ai_config_name)
                    result['generator'] = generator
                    result['success'] = True
                except Exception as e:
                    result['error'] = str(e)
                    result['success'] = False
            
            # 启动初始化线程
            init_thread = threading.Thread(target=init_generator)
            init_thread.daemon = True
            init_thread.start()
            
            # 等待最多10秒
            init_thread.join(timeout=10)
            
            if init_thread.is_alive():
                # 超时，跳过此组件
                self.performance_monitor.end_timing("文章生成器初始化")
                return False
            elif result['success']:
                self.review_generator = result['generator']
                self.performance_monitor.end_timing("文章生成器初始化")
                return True
            else:
                # 初始化失败，静默处理
                self.performance_monitor.end_timing("文章生成器初始化")
                return False
        except Exception as e:
            # 静默处理异常，不打印错误信息
            self.performance_monitor.end_timing("文章生成器初始化")
            return False
    
    def _display_model_configuration(self):
        """显示各组件使用的模型配置"""
        cache_file = "ai_model_cache.json"
        
        print("\n[AI] AI模型配置信息:")
        print("=" * 50)
        
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                    print("[LIST] 统一模型配置:")
                    print(f"   配置服务: {config.get('config_name', '未知')}")
                    print(f"   使用模型: {config.get('model_id', '未知')}")
                    
                    params = config.get('parameters', {})
                    print(f"   统一参数: temperature={params.get('temperature', 'N/A')}, ")
                    print(f"              max_tokens={params.get('max_tokens', 'N/A')}")
                    
                    print(f"   意图分析器: 使用统一参数 + stream=True")
                    print(f"   大纲生成器: 使用统一参数 + stream=True") 
                    print(f"   文章生成器: 使用统一参数 + stream=True")
                    print("   [OK] 所有组件使用完全相同的AI服务、模型、参数和流式输出")
                    
                    # 显示性能优化信息
                    if self.enable_cache:
                        print("   [START] 缓存系统: 已启用 (AI响应和搜索结果缓存)")
                    if self.enable_state:
                        print("   [SAVE] 状态管理: 已启用 (断点续传支持)")
                    
            except Exception as e:
                print(f"   [WARN]  无法读取模型配置: {e}")
                if self.enable_cache:
                    print("   [START] 缓存系统: 已启用")
                if self.enable_state:
                    print("   [SAVE] 状态管理: 已启用")
        else:
            print("   [WARN]  未找到模型配置缓存文件")
            print("   [INFO] 提示: 首次运行时将自动生成配置缓存")
            if self.enable_cache:
                print("   [START] 缓存系统: 已启用")
            if self.enable_state:
                print("   [SAVE] 状态管理: 已启用")
        
        print("=" * 50)
    
    def get_search_count_only(self, query: str) -> Optional[int]:
        """
        仅获取搜索结果数量，不获取详细内容
        
        Args:
            query: PubMed搜索查询字符串
            
        Returns:
            搜索结果总数，失败返回None
        """
        try:
            if not self.pubmed_searcher:
                print("PubMed检索器未初始化")
                return None
                
            print(f"正在估算文献数量...")
            
            # 使用retmax=0来只获取计数，不获取PMID列表，避免临时修改配置
            import requests
            import time
            
            base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            params = {
                'db': 'pubmed',
                'term': query,
                'retmode': 'json',
                'retmax': 0  # 只返回计数，不返回ID列表
            }
            
            try:
                response = requests.get(base_url, params=params, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                count = int(data.get('esearchresult', {}).get('count', 0))
                
                if count > 0:
                    print(f"[OK] 估算完成: 共找到 {count} 篇相关文献")
                else:
                    print("[WARN] 未找到相关文献")
                
                return count
                
            except Exception as e:
                print(f"[FAIL] 估算失败: {e}")
                return None
                
        except Exception as e:
            print(f"获取文献数量失败: {e}")
            return None
    
    async def run_complete_workflow(self, user_query: str, max_results: int = 50, 
                            target_articles: int = 20, 
                            enable_resume: bool = True) -> Dict:
        """
        运行完整的工作流程
        
        Args:
            user_query: 用户检索需求
            max_results: 最大检索结果数
            target_articles: 目标筛选文章数
            enable_resume: 是否启用断点续传
            
        Returns:
            包含所有结果的字典
        """
        # 检查是否可以恢复之前的任务
        if enable_resume and self.state_manager and self.state_manager.can_resume():
            resume_result = self._try_resume_workflow()
            if resume_result:
                return resume_result
        
        # 开始新的工作流程
        print(f"开始处理用户需求: {user_query}")
        print("=" * 60)
        
        # 初始化进度跟踪
        progress_tracker = ProgressTracker(4, "文献检索与综述生成")
        
        # 保存初始状态
        if self.state_manager:
            self.state_manager.save_state({
                'user_query': user_query,
                'max_results': max_results,
                'target_articles': target_articles,
                'current_step': 0,
                'processing': True,
                'start_time': datetime.now().isoformat()
            })
        
        self.performance_monitor.start_timing("完整工作流程")
        
        # 第1步：意图分析
        print("\n第1步：分析用户意图...")
        self.performance_monitor.start_timing("意图分析")
        
        try:
            # 检查缓存
            cache_key = f"intent_analysis_{hash(user_query)}"
            cached_result = None
            if self.cache_system:
                cached_result = self.cache_system.get_cached_ai_response(cache_key)
            
            if cached_result:
                print("使用缓存的意图分析结果")
                # 这里需要从缓存结果中重构SearchCriteria对象
                # 为了简化，我们仍然重新分析，但后续可以改进缓存结构
                
            self.search_criteria = self.intent_analyzer.analyze_intent(user_query)
            self.intent_analyzer.print_analysis_result(self.search_criteria)
            
            # 缓存结果
            if self.cache_system:
                criteria_str = str(self.search_criteria.__dict__)
                self.cache_system.cache_ai_response(cache_key, criteria_str)
            
            analysis_time = self.performance_monitor.end_timing("意图分析")
            progress_tracker.update("用户意图分析", f"完成 (用时: {analysis_time:.1f}s)")
            
            # 保存状态
            if self.state_manager:
                self.state_manager.save_state({
                    'current_step': 1,
                    'search_criteria': self.search_criteria.__dict__ if self.search_criteria else None
                })
                
        except Exception as e:
            self.performance_monitor.end_timing("意图分析")
            error_msg = f"意图分析失败: {str(e)}"
            solution = "检查AI服务配置和网络连接"
            print(error_msg)
            print(f"解决方案: {solution}")
            return {"success": False, "error": "意图分析失败", "details": str(e)}
        
        # 第2步：文献检索
        print("\n第2步：PubMed文献检索...")
        self.performance_monitor.start_timing("文献检索")
        
        try:
            pubmed_query = self.intent_analyzer.build_pubmed_query(self.search_criteria)
            print(f"检索表达式: {pubmed_query}")
            
            # 在交互模式下，先获取总文献数，让用户决定要获取多少篇
            if self.interactive_mode:
                total_count = self.get_search_count_only(pubmed_query)
                if total_count is not None:
                    print(f"\n[STAT] 根据您的检索需求，共找到约 {total_count} 篇相关文献")
                    print("=" * 50)
                    
                    # 询问用户要获取多少篇文章
                    while True:
                        try:
                            user_max = input(f"请输入要获取的文献数量 (1-{total_count}, 建议50-200): ").strip()
                            if not user_max:
                                user_max = min(100, total_count)  # 默认值
                            else:
                                user_max = int(user_max)
                            
                            if user_max <= 0:
                                print("[FAIL] 数量必须大于0")
                            elif user_max > total_count:
                                print(f"[WARN] 检索结果只有{total_count}篇，自动调整为{total_count}篇")
                                user_max = total_count
                            else:
                                break
                        except ValueError:
                            print("[FAIL] 请输入有效的数字")
                    
                    max_results = user_max
                    print(f"[OK] 将获取 {max_results} 篇文献")
                else:
                    print("[WARN] 无法获取总文献数，使用默认设置")
            
            # 检查搜索缓存
            cached_search = None
            if self.cache_system:
                cached_search = self.cache_system.get_cached_search(pubmed_query, max_results)
            
            if cached_search:
                print("使用缓存的文献检索结果")
                pmid_list = cached_search['results']
            else:
                # 先获取PMID列表
                pmid_list = self.pubmed_searcher.search_articles(
                    query=pubmed_query,
                    max_results=max_results
                )
                
                # 缓存搜索结果
                if self.cache_system and pmid_list:
                    self.cache_system.cache_search_result(pubmed_query, max_results, pmid_list)
            
            if not pmid_list:
                print("未检索到文献结果")
                return {"success": False, "error": "未检索到文献"}
            
            print(f"获取到 {len(pmid_list)} 个PMID")
            
            # 第一步：只获取ISSN/EISSN信息进行初步筛选
            print("\n[STEP 1] 获取ISSN/EISSN信息进行初步筛选...")
            issn_results = []
            total_batches = (len(pmid_list) + self.chunk_size - 1) // self.chunk_size
            
            for i in range(0, len(pmid_list), self.chunk_size):
                batch = pmid_list[i:i + self.chunk_size]
                batch_num = i // self.chunk_size + 1
                print(f"正在处理第 {batch_num}/{total_batches} 批ISSN/EISSN信息 ({len(batch)} 篇)...")
                
                batch_issn_results = self.pubmed_searcher.fetch_article_issn_only(batch)
                if batch_issn_results:
                    issn_results.extend(batch_issn_results)
                
                # 显示进度
                progress = (len(issn_results) / len(pmid_list)) * 100
                progress_tracker.update_progress_only("PubMed文献检索", f"ISSN/EISSN筛选中 ({len(issn_results)}/{len(pmid_list)})", progress)
                
                # 批次间延迟（最后一批不延迟）
                if i + self.chunk_size < len(pmid_list):
                    print(f"等待 {self.batch_delay} 秒后处理下一批...")
                    time.sleep(self.batch_delay)
            
            if not issn_results:
                print("未获取到ISSN/EISSN信息")
                return {"success": False, "error": "未获取到ISSN/EISSN信息"}
            
            print(f"ISSN/EISSN信息获取完成: {len(issn_results)} 篇")
            
            # 第二步：匹配期刊质量信息
            print("\n[STEP 2] 匹配期刊质量信息...")
            enriched_results = self._enrich_with_journal_info(issn_results, self.search_criteria)
            
            # 第三步：根据用户需求筛选
            print("\n[STEP 3] 根据用户需求筛选...")
            filtered_pmids = self._filter_by_user_criteria(enriched_results, self.search_criteria)
            
            if not filtered_pmids:
                print("用户需求筛选后无符合条件的文献")
                return {"success": False, "error": "用户需求筛选后无符合条件的文献"}
            
            print(f"用户需求筛选后剩余: {len(filtered_pmids)} 篇")
            
            # 第四步：获取筛选后文献的完整信息
            print(f"\n[STEP 4] 获取筛选后 {len(filtered_pmids)} 篇文献的完整信息...")
            self.literature_results = []
            total_detail_batches = (len(filtered_pmids) + self.chunk_size - 1) // self.chunk_size
            
            for i in range(0, len(filtered_pmids), self.chunk_size):
                batch = filtered_pmids[i:i + self.chunk_size]
                batch_num = i // self.chunk_size + 1
                print(f"正在处理第 {batch_num}/{total_detail_batches} 批完整信息 ({len(batch)} 篇)...")
                
                batch_results = self.pubmed_searcher.fetch_article_details(batch)
                if batch_results:
                    self.literature_results.extend(batch_results)
                
                # 显示进度
                progress = (len(self.literature_results) / len(filtered_pmids)) * 100
                progress_tracker.update_progress_only("PubMed文献检索", f"获取完整信息 ({len(self.literature_results)}/{len(filtered_pmids)})", progress)
                
                # 批次间延迟（最后一批不延迟）
                if i + self.chunk_size < len(filtered_pmids):
                    print(f"等待 {self.batch_delay} 秒后处理下一批...")
                    time.sleep(self.batch_delay)
            
            if not self.literature_results:
                print("未获取到文献详细信息")
                return {"success": False, "error": "未获取到文献详细信息"}
            
            search_time = self.performance_monitor.end_timing("文献检索")
            print(f"优化检索完成: 原始{len(pmid_list)}篇 -> 期刊信息匹配后{len(enriched_results)}篇 -> 用户筛选后{len(filtered_pmids)}篇 -> 最终{len(self.literature_results)}篇 (用时: {search_time:.1f}s)")
            
            # 保存状态
            if self.state_manager:
                self.state_manager.save_state({
                    'current_step': 2,
                    'pmid_count': len(pmid_list),
                    'literature_count': len(self.literature_results)
                })
            
        except Exception as e:
            print(f"[FAIL] 文献检索失败: {e}")
            return {"success": False, "error": "文献检索失败"}
        
        # 第2步已经完成了用户需求筛选，直接使用筛选后的结果
        self.filtered_results = self.literature_results
        print(f"[OK] 文献检索完成，共获取 {len(self.filtered_results)} 篇符合条件文献")
        
        progress_tracker.update("文献检索", f"完成 (获取 {len(self.filtered_results)} 篇)")
        
        # 立即保存筛选后的文献为CSV格式（在用户确认之前）
        print("\n保存筛选后的文献结果...")
        self._save_literature_csv(user_query, self.filtered_results, "筛选结果")
        
        # 用户确认断点：是否继续生成综述大纲
        if not self._ask_user_continue():
            print("返回到用户输入...")
            if self.state_manager:
                self.state_manager.clear_state()
            return {"success": False, "restart": True}
        
        # 第3步：生成综述大纲
        print("\n第3步：生成综述大纲...")
        self.performance_monitor.start_timing("大纲生成")
        
        try:
            # 使用智能标题提取，只保留核心研究主题和时间范围
            research_topic = self._extract_core_research_topic(user_query)
            print(f"核心研究主题提取: '{user_query}' → '{research_topic}'")
            
            # 检查大纲缓存
            outline_cache_key = f"outline_{hash(research_topic + str(len(self.filtered_results)))}"
            cached_outline = None
            if self.cache_system:
                cached_outline = self.cache_system.get_cached_ai_response(outline_cache_key)
            
            if cached_outline:
                print("使用缓存的综述大纲")
                self.outline_content = cached_outline
            else:
                self.outline_content = self.outline_generator.generate_outline_from_data(
                    self.filtered_results, research_topic
                )
                
                # 缓存大纲结果
                if self.cache_system and self.outline_content:
                    self.cache_system.cache_ai_response(outline_cache_key, self.outline_content)
            
            # 验证大纲内容是否有效
            if not self.outline_content or "错误" in self.outline_content or len(self.outline_content.strip()) < 50:
                print(f"大纲生成返回无效内容: {self.outline_content[:100]}...")
                return {"success": False, "error": "大纲生成返回无效内容"}
            
            outline_time = self.performance_monitor.end_timing("大纲生成")
            print(f"综述大纲生成完成 (用时: {outline_time:.1f}s)")
            
            # 保存大纲到文件
            outline_file = self._save_outline_to_file(user_query, research_topic)
            if outline_file:
                progress_tracker.update("综述大纲生成", f"完成 (保存至: {outline_file})")
            else:
                progress_tracker.update("综述大纲生成", f"完成 (大纲长度: {len(self.outline_content)} 字符)")
            
            # 保存状态和文件路径
            if self.state_manager:
                self.state_manager.save_state({
                    'current_step': 4,
                    'outline_generated': True,
                    'outline_file': outline_file
                })
            
            # 保存大纲文件路径供最终结果使用
            self.final_outline_file = outline_file
                
        except Exception as e:
            self.performance_monitor.end_timing("大纲生成")
            print(f"大纲生成失败: {e}")
            return {"success": False, "error": "大纲生成失败", "details": str(e)}
        
        # 第4步：生成综述文章
        print("\n第4步：生成综述文章...")
        self.performance_monitor.start_timing("文章生成")
        
        try:
            # 检查文章生成器是否可用
            if self.review_generator is None:
                print("文章生成器初始化失败，无法生成综述文章")
                return {"success": False, "error": "文章生成器初始化失败", 
                       "details": "AI配置问题或组件初始化超时，请检查AI服务配置"}
            
            # 保存临时文件供文章生成器使用
            temp_outline_file = self._save_temp_outline()
            temp_literature_file = self._save_temp_literature()
            
            review_title = f"{research_topic}：系统性文献综述"
            output_file = self._generate_output_filename(research_topic)
            
            # 检查文章缓存
            article_cache_key = f"article_{hash(review_title + str(len(self.filtered_results)))}"
            cached_article = None
            if self.cache_system:
                cached_article = self.cache_system.get_cached_ai_response(article_cache_key)
            
            if cached_article:
                print("使用缓存的综述文章")
                review_content = cached_article
                success = True
            else:
                md_path, docx_path = self.review_generator.generate_from_files(
                    outline_file=temp_outline_file,
                    literature_file=temp_literature_file,
                    title=review_title,
                    output_filename=output_file,
                    user_input=user_query,
                    export_docx=True  # 默认导出DOCX格式
                )
                
                success = bool(md_path)  # 如果MD文件生成成功就算成功
                
                if not success:
                    print("综述文章生成失败，尝试备用方法...")
                    # 尝试直接返回生成的内容
                    try:
                        review_content = self.review_generator.generate_complete_review_article(
                            temp_outline_file, temp_literature_file, review_title
                        )
                        if review_content:
                            success = True
                            # 确保输出目录存在
                            os.makedirs("综述文章", exist_ok=True)
                            full_path = os.path.join("综述文章", output_file)
                            
                            # 保存生成的内容
                            with open(full_path, 'w', encoding='utf-8') as f:
                                f.write(review_content)
                            print(f"综述文章已保存（备用方法）: {full_path}")
                            
                            # 缓存文章结果
                            if self.cache_system:
                                self.cache_system.cache_ai_response(article_cache_key, review_content)
                        else:
                            return {"success": False, "error": "综述文章生成失败"}
                    except Exception as e:
                        print(f"备用方法也失败: {e}")
                        return {"success": False, "error": "综述文章生成失败"}
            
            if success:
                # 确保综述文章文件存在
                full_path = os.path.join("综述文章", output_file)
                if os.path.exists(full_path):
                    print(f"综述文章生成完成: {full_path}")
                else:
                    print("主方法生成完成但未找到文件")
            else:
                return {"success": False, "error": "综述文章生成失败"}
            
            # 清理临时文件
            self._cleanup_temp_files([temp_outline_file, temp_literature_file])
            
            generation_time = self.performance_monitor.end_timing("文章生成")
            print(f"综述文章生成完成 (用时: {generation_time:.1f}s)")
            
            progress_tracker.update("综述文章生成", f"完成 (保存至: {output_file})")
            
        except Exception as e:
            self.performance_monitor.end_timing("文章生成")
            print(f"文章生成失败: {e}")
            return {"success": False, "error": "文章生成失败", "details": str(e)}
        
        # 清理状态
        if self.state_manager:
            self.state_manager.clear_state()
        
        # 返回完整结果
        workflow_time = self.performance_monitor.end_timing("完整工作流程")
        performance_report = self.performance_monitor.get_performance_report()
        
        result = {
            "success": True,
            "user_query": user_query,
            "search_criteria": self.search_criteria.__dict__ if self.search_criteria else None,
            "total_found": len(self.literature_results),
            "filtered_count": len(self.filtered_results),
            "outline_file": getattr(self, 'final_outline_file', None),
            "review_file": os.path.join("综述文章", output_file) if 'output_file' in locals() else None,
            "docx_file": docx_path if 'docx_path' in locals() and docx_path else None,
            "processing_time": workflow_time,
            "performance_report": performance_report
        }
        
        print("\n完整工作流程执行成功！")
        print("=" * 60)
        self._print_summary(result)
        self._print_performance_summary(performance_report)
        
        return result
        
        return result
    
    def _save_temp_outline(self) -> str:
        """保存临时大纲文件"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        temp_file = f"temp_outline_{timestamp}.md"
        
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(self.outline_content)
            
        return temp_file
    
    def _save_outline_to_file(self, user_query: str, research_topic: str) -> str:
        """
        保存综述大纲到工作目录的综述大纲文件夹
        
        Args:
            user_query: 用户原始查询内容
            research_topic: 研究主题
            
        Returns:
            保存的文件路径
        """
        try:
            import re
            import os
            from datetime import datetime
            
            # 创建综述大纲目录
            outline_dir = "综述大纲"
            os.makedirs(outline_dir, exist_ok=True)
            
            # 清理用户输入内容用于文件名
            safe_user_input = re.sub(r'[^\w\s\u4e00-\u9fff\-]', '', user_query)
            safe_user_input = re.sub(r'\s+', '_', safe_user_input.strip())
            safe_user_input = safe_user_input[:50]  # 限制长度
            
            # 生成时间戳
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # 构建文件名：综述大纲-用户输入内容-时间戳.md
            filename = f"综述大纲-{safe_user_input}-{timestamp}.md"
            file_path = os.path.join(outline_dir, filename)
            
            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.outline_content)
            
            print(f"综述大纲已保存: {file_path}")
            return file_path
            
        except Exception as e:
            print(f"保存综述大纲失败: {e}")
            return None
    
    def _save_temp_literature(self) -> str:
        """保存临时文献文件"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        temp_file = f"temp_literature_{timestamp}.json"
        
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(self.filtered_results, f, ensure_ascii=False, indent=2)
            
        return temp_file
    
    def _generate_output_filename(self, topic: str) -> str:
        """生成输出文件名（仅文件名，不包含路径）"""
        import re
        safe_topic = re.sub(r'[^\w\s\u4e00-\u9fff-]', '', topic)  # 保留中文字符
        safe_topic = re.sub(r'\s+', '_', safe_topic.strip())[:30]  # 替换空格为下划线，限制长度
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        return f"综述-{safe_topic}-{timestamp}.md"
    
    def _cleanup_temp_files(self, files: List[str]):
        """清理临时文件"""
        for file_path in files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"清理临时文件失败 {file_path}: {e}")
    
    def _save_literature_csv(self, user_query: str, literature_data: List[Dict], file_type: str = "检索结果"):
        """
        保存文献检索结果为CSV格式
        
        Args:
            user_query: 用户查询内容
            literature_data: 文献数据列表
            file_type: 文件类型标识（如"检索结果"或"筛选结果"）
        """
        import csv
        import re
        
        if not literature_data:
            return
            
        # 确保输出目录存在
        output_dir = "文献检索结果"
        os.makedirs(output_dir, exist_ok=True)
        
        # 生成文件名：文献列表-用户输入内容-时间戳
        safe_user_input = re.sub(r'[^\w\s\u4e00-\u9fff\-]', '', user_query)
        safe_user_input = re.sub(r'\s+', '_', safe_user_input.strip())
        safe_user_input = safe_user_input[:50]  # 限制长度
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"文献列表-{safe_user_input}-{timestamp}.csv"
        filepath = os.path.join(output_dir, filename)
        
        try:
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as csvfile:
                # 定义CSV字段 - 添加期刊质量指标和卷期页信息
                fieldnames = [
                    '序号', '标题', '作者', '期刊', '卷', '期', '页码', '发表年份', 'PMID', 'DOI', 
                    'ISSN', 'eISSN', '中科院分区', 'JCR分区', '影响因子', 
                    '摘要', '关键词', 'URL'
                ]
                
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                # 写入数据
                for i, article in enumerate(literature_data, 1):
                    # 处理作者列表
                    authors = article.get('authors', [])
                    if isinstance(authors, list):
                        authors_str = '; '.join(authors)
                    else:
                        authors_str = str(authors) if authors else ''
                    
                    # 处理关键词
                    keywords = article.get('keywords', [])
                    if isinstance(keywords, list):
                        keywords_str = '; '.join(keywords)
                    else:
                        keywords_str = str(keywords) if keywords else ''
                    
                    # 获取期刊质量信息
                    issn = article.get('issn', '')
                    eissn = article.get('eissn', '')
                    journal_info = self.literature_filter.get_journal_info(issn, eissn)
                    
                    # 构建CSV行数据
                    row_data = {
                        '序号': i,
                        '标题': article.get('title', ''),
                        '作者': authors_str,
                        '期刊': article.get('journal', ''),
                        '卷': article.get('volume', ''),
                        '期': article.get('issue', ''),
                        '页码': article.get('pages', ''),
                        '发表年份': article.get('publication_date', ''),
                        'PMID': article.get('pmid', ''),
                        'DOI': article.get('doi', ''),
                        'ISSN': issn,
                        'eISSN': eissn,
                        '中科院分区': journal_info.get('cas_zone', ''),
                        'JCR分区': journal_info.get('jcr_quartile', ''),
                        '影响因子': journal_info.get('impact_factor', ''),
                        '摘要': article.get('abstract', ''),
                        '关键词': keywords_str,
                        'URL': article.get('url', '')
                    }
                    
                    writer.writerow(row_data)
            
            print(f"[FILE] 文献检索结果已保存至: {filepath}")
            
        except Exception as e:
            print(f"[FAIL] 保存CSV文件失败: {e}")
    
    def _print_filtered_summary(self):
        """显示筛选结果摘要"""
        if not self.filtered_results:
            return
            
        print("\n[STAT] 筛选结果摘要:")
        print("=" * 40)
        
        # 显示前几篇文献的基本信息
        for i, article in enumerate(self.filtered_results[:3], 1):
            title = article.get('title', '无标题')[:50] + "..." if len(article.get('title', '')) > 50 else article.get('title', '无标题')
            journal = article.get('journal', '未知期刊')
            year = article.get('publication_date', '未知年份')
            authors = article.get('authors', '未知作者')
            
            print(f"{i}. 标题: {title}")
            print(f"   期刊: {journal} ({year})")
            print(f"   作者: {authors[:30]}..." if len(authors) > 30 else f"   作者: {authors}")
            print()
        
        if len(self.filtered_results) > 3:
            print(f"... 还有 {len(self.filtered_results) - 3} 篇文献")
        print("=" * 40)
    
    def _ask_user_continue(self) -> bool:
        """
        询问用户是否继续生成综述大纲
        
        Returns:
            bool: True表示继续，False表示返回重新输入
        """
        if not self.interactive_mode:
            # 非交互模式默认继续
            return True
        
        print(f"\n❓ 基于以上 {len(self.filtered_results)} 篇文献，是否继续生成综述大纲？")
        print("   [y] 继续生成综述大纲和文章")
        print("   [n] 返回重新输入检索需求")
        print("   [s] 显示更多筛选结果详情")
        
        while True:
            try:
                choice = input("\n请选择 (y/n/s) [y]: ").strip().lower()
                
                if choice in ['', 'y', 'yes']:
                    print("[OK] 继续生成综述大纲...")
                    return True
                elif choice in ['n', 'no']:
                    return False
                elif choice in ['s', 'show']:
                    self._show_detailed_results()
                    print(f"\n❓ 基于以上 {len(self.filtered_results)} 篇文献，是否继续生成综述大纲？")
                    print("   [y] 继续生成综述大纲和文章")
                    print("   [n] 返回重新输入检索需求")
                    continue
                else:
                    print("请输入 y、n 或 s")
                    continue
                    
            except (EOFError, KeyboardInterrupt):
                print("\n[WARN]  用户中断，返回输入...")
                return False
    
    def _show_detailed_results(self):
        """显示详细的筛选结果"""
        print("\n📚 详细筛选结果:")
        print("=" * 60)
        
        for i, article in enumerate(self.filtered_results, 1):
            title = article.get('title', '无标题')
            journal = article.get('journal', '未知期刊')
            year = article.get('publication_date', '未知年份')
            authors = article.get('authors', '未知作者')
            abstract = article.get('abstract', '无摘要')
            
            print(f"{i}. 【{journal}】 {title}")
            print(f"   作者: {authors}")
            print(f"   年份: {year}")
            
            # 显示摘要前150字符
            if abstract and len(abstract) > 10:
                abstract_preview = abstract[:150] + "..." if len(abstract) > 150 else abstract
                print(f"   摘要: {abstract_preview}")
            
            print("-" * 60)
    
    def _try_resume_workflow(self) -> Optional[Dict]:
        """尝试恢复之前的工作流程"""
        if not self.state_manager:
            return None
        
        state = self.state_manager.load_state()
        if not state or not state.get('processing', False):
            return None
        
        print("\n发现未完成的任务，尝试恢复...")
        print(f"任务信息: {state.get('user_query', '未知')}")
        print(f"上次进度: 第 {state.get('current_step', 0)} 步")
        
        if self.interactive_mode:
            try:
                choice = input("是否恢复之前的任务? (y/n) [y]: ").strip().lower()
                if choice in ['', 'y', 'yes']:
                    print("正在恢复任务...")
                    # 这里可以实现更复杂的恢复逻辑
                    # 目前简单返回None，让用户重新开始
                else:
                    self.state_manager.clear_state()
                    print("已清除之前的任务状态")
                    return None
            except (EOFError, KeyboardInterrupt):
                print("用户中断")
                return None
        
        return None
    
    def _print_performance_summary(self, performance_report: Dict):
        """打印优化的性能摘要"""
        print("\n性能分析报告:")
        print("-" * 50)
        
        # 显示实际总时间（墙钟时间）
        actual_time = performance_report.get('actual_total_time', 0)
        print(f"实际总处理时间: {actual_time:.2f}秒")
        
        # 显示分类统计
        serial_time = performance_report.get('serial_total_time', 0)
        parallel_time = performance_report.get('parallel_total_time', 0)
        
        print(f"串行操作总时间: {serial_time:.2f}秒")
        print(f"并行操作最大时间: {parallel_time:.2f}秒")
        
        print("\n各环节详细耗时:")
        categories = performance_report.get('operation_categories', {})
        
        # 按类别显示操作
        for category, operations in categories.items():
            if not operations:
                continue
                
            category_names = {
                'workflow': '工作流程',
                'serial': '串行操作', 
                'parallel': '并行操作',
                'component': '组件初始化'
            }
            
            print(f"\n  {category_names.get(category, category)}:")
            for operation in operations:
                duration = performance_report['operation_times'].get(operation, 0)
                count = performance_report['operation_counts'].get(operation, 1)
                avg_time = performance_report['average_times'].get(operation, duration)
                
                # 标记并行操作
                parallel_mark = " [并行]" if category == 'parallel' else ""
                print(f"    {operation}: {duration:.2f}秒 (平均: {avg_time:.2f}秒 x {count}次){parallel_mark}")
        
        # 性能瓶颈分析
        bottlenecks = performance_report.get('bottlenecks', [])
        if bottlenecks:
            print(f"\n性能瓶颈: {', '.join(bottlenecks)}")
            print("建议: 优化上述环节以提升整体性能")
        
        print("-" * 50)
    
    def _get_processing_time(self) -> str:
        """获取处理时间（简化版本）"""
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    def _enrich_with_journal_info(self, issn_results: List[Dict], search_criteria) -> List[Dict]:
        """
        为ISSN/EISSN信息匹配期刊质量信息
        
        Args:
            issn_results: 包含ISSN/EISSN信息的文章列表
            search_criteria: 搜索条件
        
        Returns:
            包含期刊质量信息的文章列表
        """
        if not issn_results or not self.literature_filter:
            return issn_results
        
        enriched_results = []
        total_count = len(issn_results)
        
        print(f"开始匹配期刊质量信息，共 {total_count} 篇文献...")
        
        for i, article in enumerate(issn_results):
            issn = article.get('issn', '')
            eissn = article.get('eissn', '')
            
            # 获取期刊质量信息
            journal_info = self.literature_filter.get_journal_info(issn, eissn)
            
            # 添加期刊信息到文章数据中
            enriched_article = article.copy()
            enriched_article['journal_info'] = journal_info
            
            enriched_results.append(enriched_article)
            
            # 显示进度
            if (i + 1) % 50 == 0:
                print(f"期刊信息匹配进度: {i + 1}/{total_count}")
        
        print(f"期刊信息匹配完成，成功匹配: {len([r for r in enriched_results if r['journal_info']])}/{total_count} 篇")
        return enriched_results
    
    def _filter_by_user_criteria(self, enriched_results: List[Dict], search_criteria) -> List[str]:
        """
        根据用户需求进行筛选
        
        Args:
            enriched_results: 包含期刊质量信息的文章列表
            search_criteria: 搜索条件
        
        Returns:
            筛选后的PMID列表
        """
        filtered_pmids = []
        total_count = len(enriched_results)
        
        print(f"开始根据用户需求筛选，共 {total_count} 篇文献...")
        
        # 从搜索条件中提取筛选标准
        min_impact_factor = getattr(search_criteria, 'min_if', 0) or 0
        target_zones = getattr(search_criteria, 'cas_zones', [])
        target_quartiles = getattr(search_criteria, 'jcr_quartiles', [])
        
            
        for i, article in enumerate(enriched_results):
            pmid = article.get('pmid', '')
            journal_info = article.get('journal_info', {})
            
            # 默认不保留没有期刊信息的文章
            should_include = bool(journal_info)
            
            if journal_info:
                # 检查影响因子条件
                if min_impact_factor > 0:
                    impact_factor = journal_info.get('impact_factor')
                    if not impact_factor or float(impact_factor) < min_impact_factor:
                        should_include = False
                
                # 检查中科院分区条件
                if should_include and target_zones:
                    cas_zone = journal_info.get('cas_zone')
                    if not cas_zone or cas_zone not in target_zones:
                        should_include = False
                
                # 检查JCR分区条件
                if should_include and target_quartiles:
                    jcr_quartile = journal_info.get('jcr_quartile')
                    if not jcr_quartile or jcr_quartile not in target_quartiles:
                        should_include = False
            
            if should_include:
                filtered_pmids.append(pmid)
            
            # 显示进度
            if (i + 1) % 50 == 0:
                print(f"用户需求筛选进度: {i + 1}/{total_count} (已筛选: {len(filtered_pmids)} 篇)")
        
        print(f"用户需求筛选完成: {total_count} 篇 -> {len(filtered_pmids)} 篇")
        return filtered_pmids
    
    def _extract_core_research_topic(self, user_input: str) -> str:
        """
        从用户输入中提取核心研究主题，移除筛选条件
        
        Args:
            user_input: 用户原始输入
            
        Returns:
            str: 提取的核心研究主题
        """
        import re
        
        # 定义需要移除的筛选条件关键词（添加高分文章识别）
        filter_patterns = [
            # 期刊分区相关 - 完整移除
            r'中科院[1-4一二三四]?区?[1-4一二三四]?区?[期刊]*',
            r'中科院.*?分区', r'CAS.*?分区', 
            r'JCR.*?分区', r'JCR.*?Q[1-4]', r'Q[1-4]区?',
            r'[1-4一二三四]区[2-4二三四]?区?',
            r'分区[1-4一二三四\-\s]+区?',
            
            # 影响因子相关 - 修复正则表达式错误
            r'影响因子.*?[>＞大于高于超过小于低于<＜]\s*\d+\.?\d*分?',
            r'高影响因子', r'顶级影响因子', r'低影响因子',
            r'IF\s*[>＞<＜]\s*\d+\.?\d*',
            r'[>＞大于高于超过小于低于<＜]\s*\d+\.?\d*分?',
            
            # 期刊质量相关 - 加强期刊过滤
            r'顶级期刊', r'高质量期刊', r'权威期刊', r'核心期刊',
            r'SCI期刊', r'SSCI期刊', r'EI期刊',
            r'high\s+impact\s+factor', r'journals?', r'期刊',
            r'JCR\s*Q[1-4]\s*期刊', r'Q[1-4]\s*期刊',
            
            # 文章质量相关 - 新增高分文章识别
            r'高分文章', r'高质量文章', r'顶级文章', r'权威文章',
            r'高分', r'高质量', r'顶级', r'权威',
            
            # 结尾的修饰词
            r'的?研究$', r'的?文献$', r'的?综述$', r'进展$',
            r'research$', r'study$', r'studies$',
        ]
        
        # 提取时间范围（先提取，后面重新添加）
        time_patterns = [
            r'近\d+年', r'最近\d+年', r'过去\d+年', r'前\d+年',
            r'近几年', r'最近几年', r'近年来', r'最近', r'近期',
            r'\d{4}年?[-到至]\d{4}年?', r'\d{4}年?以来', r'\d{4}年?至今'
        ]
        
        time_range = ""
        for pattern in time_patterns:
            match = re.search(pattern, user_input)
            if match:
                time_range = match.group()
                break
        
        # 开始清理
        clean_topic = user_input.strip()
        
        # 检测是否包含英文内容
        is_english_content = re.search(r'[a-zA-Z]', clean_topic)
        
        # 移除筛选条件关键词
        for pattern in filter_patterns:
            clean_topic = re.sub(pattern, '', clean_topic, flags=re.IGNORECASE)
        
        # 特殊处理：移除数字+区的组合（如"1-2区"）
        clean_topic = re.sub(r'\d+[-\s]*\d*区', '', clean_topic)
        
        # 清理连续的标点符号
        clean_topic = re.sub(r'[,，、；;]+', '', clean_topic)
        clean_topic = re.sub(r'^[和与及的]', '', clean_topic)
        
        # 额外处理："的"字结尾清理
        clean_topic = re.sub(r'的$', '', clean_topic)
        
        # 处理英文输入的特殊情况（在移除空格之前）
        if is_english_content:
            # 英文输入，保留主要单词，移除修饰词
            english_filter_words = ['high', 'impact', 'factor', 'journals', 'journal', 'Q1', 'Q2', 'Q3', 'Q4']
            # 先标准化空格
            clean_topic = re.sub(r'\s+', ' ', clean_topic)
            words = clean_topic.split()
            filtered_words = [word for word in words if word.lower() not in english_filter_words]
            if filtered_words:
                clean_topic = ' '.join(filtered_words)
        else:
            # 纯中文内容，移除多余空格但保留必要的分隔
            clean_topic = re.sub(r'\s+', '', clean_topic)
        
        clean_topic = clean_topic.strip()
        
        # 特殊情况处理：如果只剩下"期刊"或类似的无意义词汇，则回退到默认处理
        meaningless_keywords = ['期刊', 'journals', 'journal', '研究', '文献', '综述']
        if clean_topic in meaningless_keywords:
            clean_topic = ""
        
        # 如果清理后太短，尝试从原始输入中提取核心概念
        if len(clean_topic) < 3:
            # 定位核心医学概念
            medical_concepts = re.findall(r'糖尿病|高血压|心血管|肿瘤|癌症|COVID-19|疫苗|治疗|诊断|机器学习', user_input)
            if medical_concepts:
                clean_topic = medical_concepts[0]
            else:
                # 英文概念提取
                english_concepts = re.findall(r'\b(?:diabetes|COVID-19|cancer|treatment|therapy|diagnosis|machine\s+learning|vaccine)\b', user_input, re.IGNORECASE)
                if english_concepts:
                    clean_topic = english_concepts[0]
        
        # 重新添加时间范围，注意顺序
        if time_range and time_range not in clean_topic:
            # 检查时间范围在原始输入中的位置
            time_pos = user_input.find(time_range) if time_range in user_input else -1
            
            # 检查核心医学概念在原始输入中的位置
            core_medical_pos = -1
            if clean_topic:
                # 尝试找到核心主题在原始输入中的位置
                core_medical_pos = user_input.find(clean_topic.replace(time_range, '').strip())
            
            if is_english_content:
                if time_pos != -1 and (core_medical_pos == -1 or time_pos < core_medical_pos):
                    # 时间范围在前面
                    clean_topic = time_range + ' ' + clean_topic
                else:
                    # 时间范围在后面
                    clean_topic = clean_topic + ' ' + time_range
            else:
                # 中文处理：特殊处理"近年来"等前置时间词
                if time_range in ['近年来', '最近', '近期'] and time_pos != -1 and (core_medical_pos == -1 or time_pos < core_medical_pos):
                    # 前置时间词，如"近年来糖尿病研究" -> "糖尿病近年来"
                    clean_topic = clean_topic + time_range
                else:
                    # 时间范围在后面，如"糖尿病治疗近5年"
                    clean_topic = clean_topic + time_range
        
        # 最终清理
        clean_topic = clean_topic.strip()
        
        # 如果仍然为空或太短，使用默认主题
        if not clean_topic or len(clean_topic) < 2:
            clean_topic = "医学研究"
        
        return clean_topic

    def _print_summary(self, result: Dict):
        """打印处理结果摘要"""
        print(f"处理结果摘要:")
        print(f"   用户需求: {result['user_query']}")
        print(f"   检索到文献: {result['total_found']} 篇")
        print(f"   筛选后文献: {result['filtered_count']} 篇")
        print(f"   生成文件: {result['review_file']}")
        
        # 显示DOCX文件信息
        if result.get('docx_file'):
            print(f"   DOCX版本: {result['docx_file']}")
        else:
            print(f"   DOCX版本: 未导出 (需要安装Pandoc)")
            
        print(f"   处理时间: {result['processing_time']:.2f}秒")


def main():
    """命令行接口"""
    try:
        # 运行异步主函数
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n用户中断操作")
        sys.exit(0)
    except Exception as e:
        print(f"\n系统运行出现异常: {e}")
        if '--debug' in sys.argv:
            traceback.print_exc()
        sys.exit(1)


async def main_async():
    """异步主函数"""
    parser = argparse.ArgumentParser(
        description='智能文献检索与综述生成系统 v2.0',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 交互式模式
  python intelligent_literature_system.py
  
  # 命令行模式
  python intelligent_literature_system.py -q "糖尿病治疗近5年进展" --max-results 100 --target 30
  
  # 指定AI配置
  python intelligent_literature_system.py -q "COVID-19疫苗效果" --ai-config aiwave_gemini
  
  # 性能优化选项
  python intelligent_literature_system.py --no-cache --no-state --debug
  
  # 断点续传
  python intelligent_literature_system.py --resume
        """
    )
    
    parser.add_argument('-q', '--query', help='用户检索需求')
    parser.add_argument('--max-results', type=int, default=50, help='最大检索结果数 (默认: 50)')
    parser.add_argument('--target', type=int, default=20, help='目标筛选文章数 (默认: 20)')
    parser.add_argument('--ai-config', help='AI配置名称')
    parser.add_argument('--non-interactive-ai', action='store_true', help='非交互式AI配置（使用默认模型和参数）')
    
    # 新增优化选项
    parser.add_argument('--no-cache', action='store_true', help='禁用缓存系统')
    parser.add_argument('--no-state', action='store_true', help='禁用状态管理')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    parser.add_argument('--resume', action='store_true', help='尝试恢复之前的任务')
    parser.add_argument('--clear-cache', action='store_true', help='清除所有缓存')
    
    args = parser.parse_args()
    
    # 清除缓存
    if args.clear_cache:
        cache_system = IntelligentCache()
        cache_system.clear_cache()
        state_manager = StateManager()
        state_manager.clear_state()
        print("缓存和状态已清除")
        return
    
    try:
        # 初始化系统
        system = IntelligentLiteratureSystem(
            ai_config_name=args.ai_config,
            interactive_mode=not args.non_interactive_ai,
            enable_cache=not args.no_cache,
            enable_state=not args.no_state
        )
        
        # 初始化组件
        if not await system.initialize_components():
            print("系统初始化失败")
            sys.exit(1)
        
        # 获取用户查询
        print("\n" + "="*60)
        print("[FIND] 系统已就绪，请输入您的检索需求")
        print("="*60)
        
        while True:  # 添加循环支持重新输入
            if args.query:
                user_query = args.query
                args.query = None  # 清除命令行参数，避免重复使用
            else:
                # 交互式输入
                print("\n请输入您的检索需求（例如：糖尿病治疗近5年高影响因子研究）:")
                print(">>> ", end="", flush=True)
                try:
                    user_query = input().strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n用户输入中断")
                    break
                
                if not user_query:
                    print("[FAIL] 请提供有效的检索需求")
                    continue
            
            # 运行完整工作流程
            result = await system.run_complete_workflow(
                user_query=user_query,
                max_results=args.max_results,
                target_articles=args.target,
                enable_resume=args.resume
            )
            
            # 检查是否需要重新输入
            if result.get("restart"):
                print("\n" + "="*50)
                continue  # 重新开始循环
            elif result["success"]:
                print("\n系统运行成功完成！")
                
                # 显示性能报告
                if 'performance_report' in result:
                    print("\n性能分析报告已生成")
                    if args.debug:
                        system._print_performance_summary(result['performance_report'])
                
                sys.exit(0)
            else:
                print(f"\n系统运行失败: {result.get('error', '未知错误')}")
                if args.debug and 'details' in result:
                    print(f"详细信息: {result['details']}")
                
                # 询问是否重试
                if not args.non_interactive_ai:
                    try:
                        retry = input("是否重新输入检索需求？(y/n) [y]: ").strip().lower()
                        if retry in ['', 'y', 'yes']:
                            continue
                    except (EOFError, KeyboardInterrupt):
                        pass
                sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n用户中断操作")
        sys.exit(0)
    except Exception as e:
        print(f"\n系统运行出现异常: {e}")
        if args.debug:
            traceback.print_exc()
        sys.exit(1)
    
    args = parser.parse_args()
    
    try:
        # 初始化系统
        system = IntelligentLiteratureSystem(
            ai_config_name=args.ai_config,
            interactive_mode=not args.non_interactive_ai
        )
        
        # 初始化组件
        if not await system.initialize_components():
            sys.exit(1)
        
        # 获取用户查询
        while True:  # 添加循环支持重新输入
            if args.query:
                user_query = args.query
                args.query = None  # 清除命令行参数，避免重复使用
            else:
                # 交互式输入
                print("请输入您的检索需求（例如：糖尿病治疗近5年高影响因子研究）:")
                user_query = input(">>> ").strip()
                
                if not user_query:
                    print("[FAIL] 请提供有效的检索需求")
                    continue
            
            # 运行完整工作流程
            result = system.run_complete_workflow(
                user_query=user_query,
                max_results=args.max_results,
                target_articles=args.target
            )
            
            # 检查是否需要重新输入
            if result.get("restart"):
                print("\n" + "="*50)
                continue  # 重新开始循环
            elif result["success"]:
                print("\n[TARGET] 系统运行成功完成！")
                sys.exit(0)
            else:
                print(f"\n[FAIL] 系统运行失败: {result.get('error', '未知错误')}")
                
                # 询问是否重试
                if not args.non_interactive_ai:
                    try:
                        retry = input("是否重新输入检索需求？(y/n) [y]: ").strip().lower()
                        if retry in ['', 'y', 'yes']:
                            continue
                    except (EOFError, KeyboardInterrupt):
                        pass
                sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n[WARN]  用户中断操作")
        sys.exit(0)
    except Exception as e:
        print(f"\n[FAIL] 系统运行出现异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()