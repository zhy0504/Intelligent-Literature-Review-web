#!/bin/bash

# 智能文献综述系统 - 数据初始化脚本
# 老王出品，必属精品！

set -e

echo "🔥 老王的数据初始化脚本启动了！"

# 定义数据目录
DATA_DIR="/app/data"
PROMPTS_DIR="/app/prompts"
BACKUP_DIR="/app/backup_data"

# 1. 创建备份目录
echo "📁 创建备份目录..."
mkdir -p "$BACKUP_DIR"

# 2. 如果本地data目录为空，从备份恢复数据
if [ ! -f "$DATA_DIR/jcr.csv" ] && [ -d "$BACKUP_DIR" ] && [ -f "$BACKUP_DIR/jcr.csv" ]; then
    echo "🔄 检测到本地data目录为空，从备份恢复数据..."
    cp -r "$BACKUP_DIR"/* "$DATA_DIR/"
    echo "✅ 数据恢复完成！"
fi

# 3. 如果本地data目录仍然为空，尝试从镜像原始数据复制
if [ ! -f "$DATA_DIR/jcr.csv" ]; then
    echo "🔍 检查镜像原始数据..."

    # 检查是否有备份数据（从Dockerfile复制的数据）
    if [ -d "/app/original_data" ]; then
        echo "📦 发现镜像原始数据，正在复制..."
        cp -r /app/original_data/* "$DATA_DIR/"
        # 同时备份到持久化目录
        cp -r /app/original_data/* "$BACKUP_DIR/"
        echo "✅ 镜像数据复制完成！"
    else
        echo "⚠️  没有找到原始数据，创建空目录结构..."
        mkdir -p "$DATA_DIR"
        # 创建必要的空文件
        touch "$DATA_DIR/.gitkeep"
        echo "📝 创建了空的数据目录结构"
    fi
fi

# 4. 处理prompts配置文件
if [ ! -f "$PROMPTS_DIR/prompts_config.yaml" ]; then
    echo "🔧 处理prompts配置文件..."

    if [ -f "/app/original_prompts/prompts_config.yaml" ]; then
        echo "📋 复制原始prompts配置..."
        cp /app/original_prompts/prompts_config.yaml "$PROMPTS_DIR/"
    else
        echo "⚠️  没有找到prompts配置文件，创建默认配置..."
        mkdir -p "$PROMPTS_DIR"
        cat > "$PROMPTS_DIR/prompts_config.yaml" << 'EOF'
# 智能文献综述系统 - 默认prompts配置
# 老王的默认配置，别乱改！

system_prompts:
  literature_analysis: |
    你是一个专业的学术文献分析专家。请详细分析以下文献，包括：
    1. 研究目的和方法
    2. 主要发现和贡献
    3. 研究局限性
    4. 未来研究方向

  summary_generation: |
    请为以下文献生成一个简洁准确的学术摘要，要求：
    1. 200-300字
    2. 突出研究重点
    3. 保持学术严谨性

workflow_prompts:
  initial_search: "请基于用户需求进行初步文献搜索"
  detailed_analysis: "请对搜索到的文献进行详细分析"
  final_summary: "请生成最终的研究综述"
EOF
    fi
    echo "✅ Prompts配置处理完成！"
fi

# 5. 设置正确的权限
echo "🔐 设置文件权限..."
chown -R app:app "$DATA_DIR" "$PROMPTS_DIR" "$BACKUP_DIR" 2>/dev/null || true
chmod -R 755 "$DATA_DIR" "$PROMPTS_DIR" "$BACKUP_DIR"

# 6. 验证数据完整性
echo "🔍 验证数据完整性..."
if [ -f "$DATA_DIR/jcr.csv" ]; then
    echo "✅ JCR数据文件存在"
    file_size=$(wc -l < "$DATA_DIR/jcr.csv")
    echo "📊 JCR数据行数: $file_size"
else
    echo "⚠️  JCR数据文件不存在"
fi

if [ -f "$DATA_DIR/zky.csv" ]; then
    echo "✅ 中科院数据文件存在"
    file_size=$(wc -l < "$DATA_DIR/zky.csv")
    echo "📊 中科院数据行数: $file_size"
else
    echo "⚠️  中科院数据文件不存在"
fi

if [ -f "$PROMPTS_DIR/prompts_config.yaml" ]; then
    echo "✅ Prompts配置文件存在"
else
    echo "⚠️  Prompts配置文件不存在"
fi

echo "🎉 数据初始化完成！老王我干得漂亮！"
echo "📍 数据目录: $DATA_DIR"
echo "📍 Prompts目录: $PROMPTS_DIR"
echo "📍 备份目录: $BACKUP_DIR"