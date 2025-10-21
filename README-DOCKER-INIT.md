# Docker 数据初始化方案 - 老王出品

## 问题背景

Docker volume挂载会覆盖容器内的原始数据，导致打包进镜像的数据文件丢失。

## 解决方案

### 方案1：Docker Entrypoint脚本（推荐）

```bash
# 1. 重新构建镜像（包含初始化脚本）
docker build -t intelligent-literature-review:latest .

# 2. 启动容器
docker-compose up -d
```

**特点：**
- 容器启动时自动执行初始化脚本
- 智能检测缺失文件并自动恢复
- 支持备份和多重恢复机制

### 方案2：应用启动时检查

主程序启动时会自动检查数据文件，如果缺失会从镜像原始数据恢复。

**特点：**
- 无需额外配置
- 每次启动都检查数据完整性
- Python原生实现，易于调试

### 方案3：手动数据恢复

```bash
# 1. 从容器复制数据到主机
docker cp <container_id>:/app/data/. ./data/

# 2. 复制prompts配置
docker cp <container_id>:/app/prompts/. ./prompts/

# 3. 重启容器
docker-compose restart
```

## 文件说明

- `init-data.sh` - Docker入口初始化脚本
- `Dockerfile` - 修改后支持数据备份
- `src/start.py` - 添加了启动时数据检查
- `docker-compose.yml` - volume挂载配置

## 数据流程

1. **构建阶段**：原始数据 → `/app/original_data`（备份）
2. **启动阶段**：检查 `/app/data` → 如果为空 → 从 `/app/original_data` 恢复
3. **运行阶段**：Volume挂载 → 数据持久化到主机

## 老王的建议

- **推荐使用方案1**：自动化程度最高
- **测试环境**：可以用方案2，方便调试
- **生产环境**：建议三重保障（初始化脚本 + 应用检查 + 手动备份）

## 故障排查

```bash
# 检查容器内数据
docker exec -it <container> ls -la /app/data/
docker exec -it <container> ls -la /app/original_data/

# 检查主机数据
ls -la ./data/

# 查看初始化日志
docker logs <container>
```

**老王我保证，这套方案绝对靠谱！**