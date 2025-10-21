#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
医学综述文章生成器 - 简化版本
基于大纲和文献检索结果生成专业的中文医学综述文章
采用旧版本的简单直接架构，移除复杂的缓存和并行处理
支持Pandoc导出DOCX格式
"""

import json
import os
import re
import subprocess
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import yaml
import sys
import os
# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_client import AIClient, ConfigManager, ChatMessage
from prompts_manager import PromptsManager


@dataclass
class ReviewSection:
    """综述章节数据类"""
    title: str
    content: str
    word_count_suggestion: Optional[int] = None
    subsections: List['ReviewSection'] = None
    
    def __post_init__(self):
        if self.subsections is None:
            self.subsections = []


@dataclass
class Literature:
    """文献数据类"""
    id: int
    title: str
    authors: str
    journal: str
    year: int
    doi: str
    abstract: str
    url: str
    volume: str = ""
    issue: str = ""
    pages: str = ""
    relevance_score: float = 0.0
    
    def get_ama_citation(self) -> str:
        """生成标准AMA格式引用"""
        import re
        
        # 1. 处理作者（最多6位，超过则前3位+et al.）
        authors = self.authors if self.authors else ""
        
        # 处理authors可能是列表或字符串的情况
        if isinstance(authors, list):
            # 如果是列表，直接使用
            author_list = [str(author).strip().strip("'\"") for author in authors if str(author).strip()]
        else:
            # 如果是字符串，则按照原来的逻辑处理
            authors = str(authors).strip() if authors else ""
            if authors:
                # 如果作者以方括号包围，移除方括号
                if authors.startswith('[') and authors.endswith(']'):
                    authors = authors[1:-1]

                # 分割作者并处理格式
                # 优先使用分号分隔（PubMed格式），如果没有分号则使用逗号
                if ';' in authors:
                    # PubMed格式：Boggild, Andrea K; Geduld, Jennifer; ...
                    author_list = [author.strip().strip("'\"") for author in authors.split(';') if author.strip().strip("'\"")]
                else:
                    # 传统格式：用逗号分隔（但可能有问题）
                    author_list = [author.strip().strip("'\"") for author in authors.split(',') if author.strip().strip("'\"")]
            else:
                author_list = []
        
        # 格式化作者列表为AMA格式
        if author_list:
            # 转换为AMA格式：去掉姓和名之间的逗号，名字缩写
            ama_authors = []
            for author in author_list:
                # 如果作者格式是 "Boggild, Andrea K"，转换为 "Boggild AK"
                if ',' in author:
                    parts = author.split(',', 1)
                    last_name = parts[0].strip()
                    first_name = parts[1].strip() if len(parts) > 1 else ""
                    # 移除名字中的点和空格，只保留缩写字母
                    initials = ''.join([c for c in first_name if c.isupper()])
                    ama_authors.append(f"{last_name} {initials}" if initials else last_name)
                else:
                    ama_authors.append(author)

            if len(ama_authors) > 6:
                # 超过6位作者，取前3位 + et al.
                formatted_authors = ', '.join(ama_authors[:3]) + ', et al.'
            else:
                formatted_authors = ', '.join(ama_authors)
        else:
            formatted_authors = "Anonymous"
        
        # 2. 处理标题（首字母大写，其余小写，专有名词除外）
        title = self.title.strip() if self.title else "Untitled"
        # 移除末尾的句点，AMA格式标题后不加句点
        if title.endswith('.'):
            title = title[:-1]
        
        # 3. 处理期刊名称（斜体，使用缩写）
        journal = self.journal.strip() if self.journal else "Unknown Journal"
        
        # 4. 处理日期和卷期页信息
        year = self.year if self.year else "Unknown"
        volume = getattr(self, 'volume', '') or ""
        issue = getattr(self, 'issue', '') or ""
        pages = getattr(self, 'pages', '') or ""
        
        # 构建期刊引用部分：期刊名. 年份;卷(期):页码
        journal_part = journal
        if year:
            journal_part += f". {year}"
        
        # 添加卷期页信息
        if volume or issue or pages:
            volume_issue_pages = ""
            if volume:
                volume_issue_pages += volume
            if issue:
                volume_issue_pages += f"({issue})" if volume else issue
            if pages:
                volume_issue_pages += f":{pages}" if (volume or issue) else pages
            
            if volume_issue_pages:
                journal_part += f";{volume_issue_pages}"
        
        # 构建基本引用格式：作者. 标题. 期刊信息
        citation_parts = [
            formatted_authors,
            title,
            journal_part
        ]
        
        # 5. 添加DOI（如果有）
        doi_part = ""
        if hasattr(self, 'doi') and self.doi and self.doi.strip():
            doi = self.doi.strip()
            # 确保DOI格式正确
            if not doi.startswith('doi:'):
                doi_part = f". doi:{doi}"
            else:
                doi_part = f". {doi}"
        
        # 6. 组合完整引用
        citation = '. '.join(citation_parts) + doi_part
        
        return citation


class PandocExporter:
    """Pandoc DOCX导出器 - 支持便携版"""
    
    def __init__(self):
        self.pandoc_path = self._find_pandoc_executable()
        self.pandoc_available = bool(self.pandoc_path)
        if self.pandoc_available:
            print(f"Pandoc已找到: {self.pandoc_path}")
        else:
            print("未找到Pandoc，请安装后使用DOCX导出功能")
            print("安装方法: https://pandoc.org/installing.html")
    
    def _find_pandoc_executable(self) -> Optional[str]:
        """查找pandoc可执行文件，支持便携版和系统安装"""
        import platform
        
        # 1. 优先查找项目便携版
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        system = platform.system().lower()
        
        # 便携版路径映射
        portable_paths = {
            'windows': 'tools/pandoc/windows/pandoc.exe',
            'linux': 'tools/pandoc/linux/pandoc',
            'darwin': 'tools/pandoc/macos/pandoc'  # macOS
        }
        
        if system in portable_paths:
            portable_path = os.path.join(project_root, portable_paths[system])
            if os.path.exists(portable_path):
                # 测试便携版Pandoc是否工作
                try:
                    result = subprocess.run([portable_path, '--version'], 
                                          capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        print(f"使用便携版Pandoc: {portable_path}")
                        return portable_path
                except Exception:
                    pass
        
        # 2. 查找系统PATH中的pandoc
        pandoc_cmd = 'pandoc.exe' if system == 'windows' else 'pandoc'
        
        try:
            result = subprocess.run([pandoc_cmd, '--version'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                # 使用shutil.which获取完整路径
                full_path = shutil.which(pandoc_cmd)
                if full_path:
                    print(f"使用系统Pandoc: {full_path}")
                    return pandoc_cmd  # 返回命令名，让系统自动解析路径
                
        except FileNotFoundError:
            pass
        
        return None
    
    def convert_to_docx(self, md_file: str, output_file: str = None, 
                       custom_template: str = None, style: str = "academic") -> str:
        """
        使用pandoc将Markdown文件转换为DOCX
        
        Args:
            md_file: 输入的Markdown文件路径
            output_file: 输出的DOCX文件路径（可选）
            custom_template: 自定义Word模板路径（可选）
            style: 预设样式（academic/simple）
            
        Returns:
            str: 生成的DOCX文件路径
        """
        if not self.pandoc_available:
            raise RuntimeError("Pandoc未安装或不可用，无法导出DOCX")
        
        if not os.path.exists(md_file):
            raise FileNotFoundError(f"Markdown文件不存在: {md_file}")
        
        # 生成输出文件名
        if not output_file:
            output_file = md_file.replace('.md', '.docx')
        
        # 构建pandoc命令 - 使用动态路径
        cmd = [self.pandoc_path, md_file, '-o', output_file]
        
        # 添加样式参数
        if style == "academic":
            # 学术风格：更紧凑的行距，标准字体
            cmd.extend(['--variable', 'fontfamily=Times'])
        
        # 使用自定义模板
        if custom_template and os.path.exists(custom_template):
            cmd.extend(['--reference-doc', custom_template])
        
        try:
            # 执行转换
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            print(f"成功导出DOCX: {output_file}")
            return output_file
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Pandoc转换失败: {e.stderr}"
            print(error_msg)
            raise RuntimeError(error_msg)
    
    def is_available(self) -> bool:
        """检查Pandoc是否可用"""
        return self.pandoc_available


class MedicalReviewGenerator:
    """医学综述文章生成器 - 简化版本"""
    
    def __init__(self, config_name: str = None, output_dir: str = "综述文章"):
        """
        初始化综述生成器
        
        Args:
            config_name: AI配置名称
            output_dir: 输出目录
        """
        self.config_manager = ConfigManager()
        self.ai_client = AIClient()
        self.config_name = config_name
        self.output_dir = output_dir
        self.model_id = None
        self.model_parameters = {
            "temperature": 0.3,  # 较低的温度保证专业性和一致性
            "stream": True,      # 启用流式输出进行测试
            "max_tokens": None   # 不限制输出长度，让AI自己决定
        }
        
        # 初始化提示词管理器
        self.prompts_manager = PromptsManager()
        
        # 初始化Pandoc导出器
        self.pandoc_exporter = PandocExporter()
        
        # 输出目录将在实际保存文件时创建
        # os.makedirs(self.output_dir, exist_ok=True)  # 移除提前创建
        
        # 初始化AI配置
        self.config = self._select_config()
        if self.config:
            self.adapter = self.ai_client.create_adapter(self.config)
            
            # 使用aiwave_gemini服务配置
            cached_model = self._load_cached_model_config()
            if cached_model:
                # 使用缓存的Gemini模型配置，但禁用流式输出
                self.model_id = cached_model['model_id']
                self.model_parameters = cached_model['parameters'].copy()
                self.model_parameters['stream'] = True   # Gemini模型启用流式输出进行测试
                print(f"使用Gemini模型配置: {self.model_id} (启用流式输出)")
            else:
                # 如果没有缓存，使用默认的Gemini模型
                self.model_id = "gemini-2.5-pro"  # 默认使用Gemini 2.5 Pro
                self.model_parameters['stream'] = True
                print(f"使用默认Gemini模型: {self.model_id} (启用流式输出)")
        else:
            raise RuntimeError("未找到可用的AI配置")
    
    def _select_config(self):
        """选择AI配置"""
        configs = self.config_manager.list_configs()
        
        if not configs:
            return None
        
        if self.config_name:
            return self.config_manager.get_config(self.config_name)
        else:
            # 与大纲生成器保持一致，使用第一个可用配置
            return self.config_manager.get_config(configs[0])
    
    def _load_cached_model_config(self):
        """加载缓存的模型配置，与意图分析器保持一致"""
        cache_file = "ai_model_cache.json"
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    # 检查缓存数据有效性
                    if cached_data.get('model_id'):
                        return cached_data
            except Exception as e:
                print(f"加载模型配置缓存失败: {e}")
        return None
    
    def load_outline(self, outline_file: str) -> List[ReviewSection]:
        """
        加载综述大纲
        
        Args:
            outline_file: 大纲文件路径
            
        Returns:
            List[ReviewSection]: 章节列表
        """
        try:
            with open(outline_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 检查文件内容是否包含错误信息（放宽条件）
            if len(content.strip()) < 30:
                print(f"大纲文件内容过短: {content[:100]}...")
                return []
            
            # 解析大纲结构
            sections = []
            lines = content.split('\n')
            current_section = None
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # 匹配章节标题和字数建议
                # 格式：## 1. 标题 (建议字数：XXX字) - 只处理二级及以下标题
                if line.startswith('#') and not line.startswith('# '):
                    # 匹配标题部分（排除一级标题）
                    header_match = re.match(r'#+\s*(\d+\.?\s*)?(.+)', line)
                    if header_match:
                        full_title = header_match.group(2).strip()
                        
                        # 提取字数建议
                        word_count = None
                        word_count_match = re.search(r'\(建议字数：(\d+)字?\)', full_title)
                        if word_count_match:
                            word_count = int(word_count_match.group(1))
                            # 从标题中移除字数建议部分
                            title = re.sub(r'\s*\(建议字数：\d+字?\)', '', full_title).strip()
                        else:
                            title = full_title
                        
                        current_section = ReviewSection(
                            title=title,
                            content="",
                            word_count_suggestion=word_count
                        )
                        sections.append(current_section)
                elif current_section and line:
                    # 将内容添加到当前章节
                    if current_section.content:
                        current_section.content += "\n" + line
                    else:
                        current_section.content = line
            
            return sections
            
        except Exception as e:
            print(f"加载大纲失败: {e}")
            return []
    
    def load_literature(self, literature_file: str) -> List[Literature]:
        """
        加载文献检索结果
        
        Args:
            literature_file: 文献文件路径
            
        Returns:
            List[Literature]: 文献列表
        """
        try:
            with open(literature_file, 'r', encoding='utf-8') as f:
                if literature_file.endswith('.json'):
                    data = json.load(f)
                elif literature_file.endswith('.csv'):
                    # 处理CSV格式
                    import csv
                    reader = csv.DictReader(f)
                    data = []
                    for i, row in enumerate(reader, 1):
                        # 安全地检查标题字段
                        title_value = row.get('标题') or ''
                        if isinstance(title_value, str) and title_value.strip():
                            data.append({
                                'id': i,
                                'title': title_value.strip(),
                                'authors': row.get('作者', ''),
                                'journal': row.get('期刊', ''),
                                'volume': row.get('卷', ''),
                                'issue': row.get('期', ''),
                                'pages': row.get('页码', ''),
                                'year': int(row.get('发表年份', '2023')) if row.get('发表年份') and row.get('发表年份').isdigit() else 2023,
                                'doi': row.get('DOI', ''),
                                'abstract': row.get('摘要', ''),
                                'url': row.get('URL', '')
                            })
                else:
                    # 假设是文本格式，每行一篇文献
                    lines = f.readlines()
                    data = []
                    for i, line in enumerate(lines, 1):
                        if line.strip():
                            # 简单解析文献信息
                            parts = line.strip().split('\t')
                            if len(parts) >= 3:
                                data.append({
                                    'id': i,
                                    'title': parts[0],
                                    'authors': parts[1] if len(parts) > 1 else "Unknown",
                                    'journal': parts[2] if len(parts) > 2 else "Unknown Journal",
                                    'year': int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 2023,
                                    'doi': parts[4] if len(parts) > 4 else "",
                                    'abstract': parts[5] if len(parts) > 5 else "",
                                    'url': parts[6] if len(parts) > 6 else ""
                                })
            
            # 转换为Literature对象
            literature_list = []
            for item in data:
                if isinstance(item, dict):
                    lit = Literature(
                        id=item.get('id', len(literature_list) + 1),
                        title=item.get('title', ''),
                        authors=item.get('authors', ''),
                        journal=item.get('journal', ''),
                        year=item.get('publication_date', '2023').split('-')[0] if item.get('publication_date') else '2023',
                        doi=item.get('doi', ''),
                        abstract=item.get('abstract', ''),
                        url=item.get('url', ''),
                        volume=item.get('volume', ''),
                        issue=item.get('issue', ''),
                        pages=item.get('pages', ''),
                        relevance_score=item.get('relevance_score', 0.0)
                    )
                    literature_list.append(lit)
            
            return literature_list
            
        except Exception as e:
            print(f"加载文献失败: {e}")
            return []
    
    def generate_section_content(self, section: ReviewSection, literature: List[Literature], context: str = "") -> str:
        """
        生成章节内容
        
        Args:
            section: 章节信息
            literature: 文献列表
            context: 上下文信息
            
        Returns:
            str: 生成的章节内容
        """
        # 构建提示词
        literature_info = ""
        for i, lit in enumerate(literature, 1):
            literature_info += f"\n[{i}] {lit.title}\n作者: {lit.authors}\n期刊: {lit.journal} ({lit.year})\n摘要: {lit.abstract}\n"
        
        word_count_hint = f"建议字数约{section.word_count_suggestion}字" if section.word_count_suggestion else "详细阐述"
        
        prompt = f"""
你是一位资深的医学综述撰写专家。请根据以下信息撰写综述文章的一个章节：

**章节标题**: {section.title}
**章节要求**: {section.content if section.content else "详细论述该主题"}
**字数要求**: {word_count_hint}

**可参考文献**:
{literature_info}

**上下文**: {context}

**撰写要求**:
1. 内容必须基于提供的文献信息，不得编造
2. 使用专业的医学术语和学术语言
3. 正文每个自然段落开头使用两个全角空格（　　）缩进
4. 在引用文献时使用中括号数字标注，如[1]、[2]等
5. 段落之间逻辑连贯，语言流畅自然
6. 不使用分点列项，写成连续的自然段落
7. 避免过度使用"此外"、"然而"等过渡词
8. 不要包含任何解释性文字，只输出章节正文内容

请直接输出章节内容，不要包含标题：
"""
        
        try:
            # 构建消息
            messages = [ChatMessage(role="user", content=prompt)]
            
            # 调用AI生成内容
            response = self.adapter.send_message(
                messages, 
                self.model_id, 
                self.model_parameters
            )
            
            # 格式化响应
            content = self.ai_client.format_response(response, self.adapter.config.api_type)
            
            # 清理内容
            content = content.strip()
            
            # 标准化段落缩进
            content = self._normalize_paragraph_indentation(content)
            
            return content
            
        except Exception as e:
            print(f"生成章节内容失败 ({section.title}): {e}")
            return f"　　本章节内容生成失败，请检查AI服务配置。错误信息：{e}"
    
    def _normalize_paragraph_indentation(self, content: str) -> str:
        """
        标准化段落缩进，确保每个段落只有两个全角空格缩进
        
        Args:
            content: 原始内容
            
        Returns:
            str: 标准化缩进后的内容
        """
        if not content:
            return content
        
        lines = content.split('\n')
        processed_lines = []
        
        for line in lines:
            # 如果是空行，直接保留
            if not line.strip():
                processed_lines.append(line)
                continue
            
            # 如果是标题行（以#开头），不处理缩进
            if line.strip().startswith('#'):
                processed_lines.append(line)
                continue
            
            # 处理段落缩进
            stripped_line = line.lstrip('　 ')  # 移除开头的全角空格和普通空格
            
            # 如果移除空格后还有内容，说明这是一个需要缩进的段落
            if stripped_line:
                # 统一添加两个全角空格
                processed_lines.append('　　' + stripped_line)
            else:
                # 如果移除空格后没有内容，保留原行
                processed_lines.append(line)
        
        return '\n'.join(processed_lines)
    
    def generate_complete_review_article(self, outline_file: str, literature_file: str, title: str = None) -> str:
        """
        生成完整的综述文章 - 一次性整体生成而非逐章节拼接
        
        Args:
            outline_file: 大纲文件路径
            literature_file: 文献文件路径
            title: 文章标题（可选）
            
        Returns:
            str: 生成的完整文章内容
        """
        print("开始生成完整医学综述文章...")
        
        # 加载大纲和文献
        print("加载综述大纲...")
        with open(outline_file, 'r', encoding='utf-8') as f:
            outline_content = f.read()
        
        print("加载文献检索结果...")
        literature = self.load_literature(literature_file)
        
        if "错误" in outline_content or len(outline_content.strip()) < 50:
            print("大纲内容无效")
            return ""
        
        if not literature:
            print("文献加载失败")
            return ""
        
        print(f"成功加载大纲和 {len(literature)} 篇文献")
        
        # 构建完整的文献信息
        literature_info = ""
        for i, lit in enumerate(literature, 1):
            literature_info += f"\n[{i}] {lit.title}\n作者: {lit.authors}\n期刊: {lit.journal} ({lit.year})\n摘要: {lit.abstract}\n"
        
        # 构建专业的提示词
        try:
            prompt = self.prompts_manager.get_review_generation_prompt(
                title=title or "医学综述",
                outline_content=outline_content,
                literature_info=literature_info
            )
        except Exception as e:
            print(f"[WARN] 使用自定义提示词失败，回退到默认提示词: {e}")
            
            # 回退到默认提示词
            prompt = f"""你是一位资深的医学综述撰写专家。请根据以下大纲和文献，撰写一篇完整、连贯的医学综述文章。

**文章标题**: {title or "医学综述"}

**综述大纲**:
{outline_content}

**参考文献库**:
{literature_info}

**撰写要求**:
1. 严格按照提供的大纲结构撰写，保持层次分明
2. 内容必须基于提供的文献信息，不得编造事实
3. 使用专业的医学术语和学术语言
4. 正文每个自然段落开头使用两个全角空格（　　）缩进
5. 在引用文献时使用中括号数字标注，如[1]、[2]等，对应上述文献编号
6. 各章节之间保持逻辑连贯，形成完整的论述体系
7. 段落内语言流畅自然，避免生硬的拼接感
8. 结论部分要总结全文，提出展望
9. 输出完整的Markdown格式文章，包含标题层级
10. **重要：文章结尾不要包含参考文献部分**，参考文献将由系统自动添加

请直接输出完整的综述文章："""
        
        try:
            # 构建消息
            messages = [ChatMessage(role="user", content=prompt)]
            
            print("正在生成完整综述文章...")
            print(f"提示词长度: {len(prompt)} 字符")
            
            # 调用AI生成完整文章
            response = self.adapter.send_message(
                messages, 
                self.model_id, 
                self.model_parameters
            )
            
            # 格式化响应
            article_content = self.ai_client.format_response(response, self.adapter.config.api_type)
            
            # 保存原始AI输出到md文件
            self._save_raw_output(article_content, title or "医学综述")
            
            # 清理AI引导语，只保留文章标题开始的内容
            article_content = self._clean_ai_intro(article_content)
            
            # 标准化段落缩进，确保只有两个全角空格
            article_content = self._normalize_paragraph_indentation(article_content)
            
            # 首先添加完整的AMA格式参考文献列表
            article_content = self._add_complete_references(article_content, literature)
            
            # 然后重新排序引用标记和参考文献
            article_content = self._reorder_citations_and_references(article_content, literature)
            
            print("完整医学综述文章生成完成!")
            
            return article_content.strip()
            
        except Exception as e:
            print(f"完整文章生成失败: {e}")
            return ""
    
    def _build_default_review_prompt(self, title: str, outline_content: str, literature_info: str) -> str:
        """构建默认综述生成提示词（兼容性保证）"""
        return f"""
你是一位资深的医学综述撰写专家。请根据以下大纲和文献，撰写一篇完整、连贯的医学综述文章。

**文章标题**: {title or "医学综述"}

**综述大纲**:
{outline_content}

**参考文献库**:
{literature_info}

**撰写要求**:
1. 严格按照提供的大纲结构撰写，保持层次分明
2. 内容必须基于提供的文献信息，不得编造事实
3. 使用专业的医学术语和学术语言
4. 正文每个自然段落开头使用两个全角空格（　　）缩进
5. 在引用文献时使用中括号数字标注，如[1]、[2]等，对应上述文献编号
6. 各章节之间保持逻辑连贯，形成完整的论述体系
7. 段落内语言流畅自然，避免生硬的拼接感
8. 结论部分要总结全文，提出展望
9. 输出完整的Markdown格式文章，包含标题层级
10. **重要：文章结尾不要包含参考文献部分**，参考文献将由系统自动添加

请直接输出完整的综述文章：
"""
    
    def _add_complete_references(self, article_content: str, literature: List[Literature]) -> str:
        """
        添加完整的AMA格式参考文献列表到文章末尾
        
        Args:
            article_content: 原始文章内容
            literature: 完整文献列表
            
        Returns:
            str: 添加了完整参考文献列表的文章内容
        """
        # 如果文章中已经有参考文献部分，先移除它
        # 匹配从"## 参考文献"开始到文章结尾或下一个二级标题的内容
        reference_section_pattern = r'##\s*参考文献\s*\n.*$'
        article_content = re.sub(reference_section_pattern, '', article_content, flags=re.MULTILINE | re.DOTALL)
        
        # 清理末尾多余的空行
        article_content = article_content.rstrip()
        
        # 生成完整的AMA格式参考文献列表
        complete_references = self.generate_references(literature)
        
        # 在文章末尾添加完整的参考文献列表
        article_content += f"\n\n## 参考文献\n\n{complete_references}"
        
        print(f"已添加完整参考文献列表 ({len(literature)} 篇文献)")
        return article_content

    def _reorder_citations_and_references(self, article_content: str, literature: List[Literature]) -> str:
        """
        重新排序引用标记和参考文献
        按文章中引用出现的顺序重新编号，只保留被引用的文献
        支持多种引用格式：[1], [5, 12], [15, 18, 40, 51]
        
        Args:
            article_content: 原始文章内容
            literature: 文献列表
            
        Returns:
            str: 重新编号后的文章内容
        """
        import re
        
        # 保存原始内容长度用于调试
        original_length = len(article_content)
        print(f"重新编号前内容长度: {original_length} 字符")
        
        # 1. 提取文章中所有的引用标记，支持单个和多个引用
        # 匹配格式: [数字] 或 [数字, 数字, ...] 
        citation_pattern = r'\[([0-9, ]+)\]'
        citation_matches = re.findall(citation_pattern, article_content)
        
        # 解析所有引用的数字
        all_citations = []
        for match in citation_matches:
            # 分割逗号分隔的数字
            numbers = [num.strip() for num in match.split(',')]
            for num_str in numbers:
                if num_str.isdigit():
                    all_citations.append(num_str)
        
        print(f"找到的引用标记: {all_citations[:10]}...")  # 只显示前10个
        
        if not all_citations:
            print("文章中未发现引用标记，跳过重新编号")
            return article_content
        
        # 2. 按出现顺序去重，保持顺序
        cited_indices = []
        seen = set()
        for citation in all_citations:
            idx = int(citation) - 1  # 转换为0基索引
            if idx not in seen and 0 <= idx < len(literature):
                cited_indices.append(idx)
                seen.add(idx)
        
        print(f"按出现顺序的文献索引: {cited_indices[:10]}...")  # 只显示前10个
        
        if not cited_indices:
            print("未找到有效的引用索引，保持原样")
            return article_content
        
        print(f"发现 {len(cited_indices)} 个被引用的文献，按出现顺序重新编号")
        
        # 3. 创建旧索引到新索引的映射
        old_to_new = {}
        for new_idx, old_idx in enumerate(cited_indices):
            old_to_new[old_idx + 1] = new_idx + 1  # 转回1基索引
        
        print(f"索引映射示例: {dict(list(old_to_new.items())[:5])}")  # 显示前5个映射
        
        # 4. 替换文章中的引用标记（支持多文献引用）
        def replace_multi_citation(match):
            citation_content = match.group(1)
            numbers = [num.strip() for num in citation_content.split(',')]
            new_numbers = []
            
            for num_str in numbers:
                if num_str.isdigit():
                    old_num = int(num_str)
                    new_num = old_to_new.get(old_num)
                    if new_num:
                        new_numbers.append(str(new_num))
                    # 如果引用的文献不在映射中，跳过（不包含在新引用中）
                    # 这样可以自动过滤掉超出文献列表范围的无效引用
            
            # 重新组合多个引用，按数字大小排序
            if not new_numbers:
                # 如果所有引用都无效，保留原始引用而不是删除
                print(f"警告: 引用 [{citation_content}] 无效，保留原样")
                return f"[{citation_content}]"
            elif len(new_numbers) == 1:
                return f"[{new_numbers[0]}]"
            else:
                # 按数字大小排序，确保小序号在前
                sorted_numbers = sorted(new_numbers, key=int)
                return f"[{', '.join(sorted_numbers)}]"
        
        # 保存替换前的内容片段用于调试
        test_section = article_content[2000:3000] if len(article_content) > 3000 else article_content[:1000]
        print(f"替换前内容片段: {test_section[:100]}...")
        
        updated_content = re.sub(citation_pattern, replace_multi_citation, article_content)
        
        # 检查替换后的内容长度
        updated_length = len(updated_content)
        print(f"重新编号后内容长度: {updated_length} 字符 (变化: {updated_length - original_length})")
        
        # 如果内容长度显著减少，输出警告
        if updated_length < original_length * 0.8:
            print(f"警告: 内容长度显著减少 {original_length} -> {updated_length}，可能存在问题")
            # 保存替换后的内容片段用于调试
            test_section_after = updated_content[2000:3000] if len(updated_content) > 3000 else updated_content[:1000]
            print(f"替换后内容片段: {test_section_after[:100]}...")
        
        # 5. 生成重新排序的参考文献列表（只包含被引用的）
        cited_literature = [literature[idx] for idx in cited_indices]
        new_references = self.generate_references(cited_literature)
        
        # 6. 替换或添加参考文献部分
        reference_section_pattern = r'##\s*参考文献\s*\n.*$'
        if re.search(reference_section_pattern, updated_content, re.MULTILINE | re.DOTALL):
            # 替换现有的参考文献部分
            updated_content = re.sub(
                reference_section_pattern, 
                f"## 参考文献\n\n{new_references}", 
                updated_content, 
                flags=re.MULTILINE | re.DOTALL
            )
            print("替换了现有的参考文献部分")
        else:
            # 添加新的参考文献部分
            updated_content += f"\n\n## 参考文献\n\n{new_references}"
            print("添加了新的参考文献部分")
        
        print(f"引用重新编号完成: {len(literature)} → {len(cited_literature)} 篇文献")
        
        return updated_content
    
    def generate_references(self, literature: List[Literature]) -> str:
        """
        生成AMA格式的参考文献列表
        
        Args:
            literature: 文献列表
            
        Returns:
            str: 格式化的参考文献
        """
        references = []
        for i, lit in enumerate(literature, 1):
            ref = f"{i}. {lit.get_ama_citation()}"
            if lit.url:
                ref += f" Available from: {lit.url}"
            references.append(ref)
        
        return '\n'.join(references)
    
    def _save_raw_output(self, raw_content: str, title: str):
        """
        保存AI的原始输出到md文件
        
        Args:
            raw_content: AI的原始输出内容
            title: 文章标题
        """
        try:
            # 获取项目根目录
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            raw_docs_dir = os.path.join(project_root, "综述AI返回原始数据（用于核对）")
            
            # 确保原始文档目录存在
            os.makedirs(raw_docs_dir, exist_ok=True)
            
            # 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # 清理标题，移除特殊字符
            clean_title = re.sub(r'[^\w\u4e00-\u9fff\s-]', '', title)
            clean_title = clean_title.strip()[:30]  # 限制长度
            clean_title = re.sub(r'\s+', '_', clean_title)  # 替换空格为下划线
            
            filename = f"原始输出-{clean_title}-{timestamp}.md"
            filepath = os.path.join(raw_docs_dir, filename)
            
            # 构建完整的原始文档内容
            raw_document = f"""# AI原始输出文档

**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**文章标题**: {title}  
**模型**: {self.model_id}  
**输出长度**: {len(raw_content)} 字符

---

{raw_content}
"""
            
            # 保存原始输出
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(raw_document)
            
            print(f"原始AI输出已保存: {filepath}")
            
        except Exception as e:
            print(f"保存原始输出失败: {e}")
    
    def _clean_ai_intro(self, content: str) -> str:
        """清理AI生成内容前面的引导语，只保留文章标题开始的内容"""
        if not content:
            return content
        
        lines = content.split('\n')
        
        # 查找第一个以#开头的标题行
        title_start_index = -1
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if line_stripped.startswith('#'):
                title_start_index = i
                break
        
        # 如果找到标题，从标题开始保留所有内容
        if title_start_index >= 0:
            cleaned_content = '\n'.join(lines[title_start_index:]).strip()
            if cleaned_content and len(cleaned_content) > 50:
                return cleaned_content
        
        # 如果没找到标题或内容过短，返回原始内容
        print("警告: 未找到标题行或内容过短，返回原始内容")
        return content
    
    def save_article(self, content: str, filename: str = None, user_input: str = None, 
                     export_docx: bool = False) -> tuple:
        """
        保存文章到文件，支持可选的DOCX导出
        
        Args:
            content: 文章内容
            filename: 文件名（可选）
            user_input: 用户输入内容（可选）
            export_docx: 是否同时导出DOCX格式
            
        Returns:
            tuple: (md_file_path, docx_file_path) 如果不导出docx，第二个值为None
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if user_input:
                # 清理用户输入，移除特殊字符，限制长度
                clean_input = re.sub(r'[^\w\u4e00-\u9fff\s-]', '', user_input)
                clean_input = clean_input.strip()[:30]  # 限制为30个字符
                # 替换空格为下划线，确保文件名格式统一
                clean_input = re.sub(r'\s+', '_', clean_input)
                filename = f"综述-{clean_input}-{timestamp}.md"
            else:
                filename = f"综述-{timestamp}.md"
        
        filepath = os.path.join(self.output_dir, filename)
        
        try:
            # 确保输出目录存在（在实际保存时创建）
            os.makedirs(self.output_dir, exist_ok=True)
            
            # 1. 保存Markdown文件
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"文章已保存到: {filepath}")
            
            # 2. 可选导出DOCX格式
            docx_path = None
            if export_docx and self.pandoc_exporter.is_available():
                try:
                    docx_path = self.pandoc_exporter.convert_to_docx(
                        filepath, 
                        style="academic"
                    )
                    print(f"DOCX版本已导出: {docx_path}")
                except Exception as docx_error:
                    print(f"DOCX导出失败: {docx_error}")
                    # 即使DOCX导出失败，MD文件仍然成功保存
            elif export_docx and not self.pandoc_exporter.is_available():
                print("Pandoc不可用，跳过DOCX导出")
            
            return filepath, docx_path
            
        except Exception as e:
            print(f"保存文章失败: {e}")
            return "", None
    
    def generate_from_files(self, outline_file: str, literature_file: str, 
                          title: str = None, output_filename: str = None, user_input: str = None, 
                          export_docx: bool = False) -> tuple:
        """
        从文件生成综述文章
        
        Args:
            outline_file: 大纲文件路径
            literature_file: 文献文件路径
            title: 文章标题
            output_filename: 输出文件名
            user_input: 用户输入内容
            export_docx: 是否导出DOCX格式
            
        Returns:
            tuple: (md_file_path, docx_file_path) 如果不导出docx，第二个值为None
        """
        # 生成文章
        article_content = self.generate_complete_review_article(outline_file, literature_file, title)
        
        if not article_content:
            print("文章生成失败")
            return "", None
        
        # 保存文章（支持DOCX导出）
        md_path, docx_path = self.save_article(article_content, output_filename, user_input, export_docx)
        
        # 显示统计信息
        word_count = len(article_content.replace(' ', '').replace('\n', ''))
        print(f"\n文章统计:")
        print(f"   总字数: {word_count:,}")
        print(f"   文件大小: {len(article_content.encode('utf-8')):,} 字节")
        
        return md_path, docx_path


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="医学综述文章生成器")
    parser.add_argument("--outline", "-o", required=True, help="综述大纲文件路径")
    parser.add_argument("--literature", "-l", required=True, help="文献检索结果文件路径")
    parser.add_argument("--title", "-t", help="文章标题")
    parser.add_argument("--output", help="输出文件名")
    parser.add_argument("--config", "-c", help="AI配置名称")
    parser.add_argument("--output-dir", "-d", default="综述文章", help="输出目录")
    parser.add_argument("--user-input", "-u", help="用户输入信息，用于生成文件名")
    
    args = parser.parse_args()
    
    try:
        # 创建生成器
        generator = MedicalReviewGenerator(
            config_name=args.config,
            output_dir=args.output_dir
        )
        
        # 生成文章
        output_path = generator.generate_from_files(
            outline_file=args.outline,
            literature_file=args.literature,
            title=args.title,
            output_filename=args.output,
            user_input=args.user_input
        )
        
        if output_path:
            print(f"\n医学综述文章生成成功!")
            print(f"文件路径: {output_path}")
        else:
            print("\n文章生成失败")
            exit(1)
            
    except Exception as e:
        print(f"程序执行失败: {e}")
        exit(1)


if __name__ == "__main__":
    main()