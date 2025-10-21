# Web TTY 使用说明 - 老王出品

## 概述

这个Web TTY功能让你可以通过浏览器直接连接到容器的终端，不需要复杂的Flask Web界面，简单粗暴好用！

## 特性

- 🌐 **浏览器访问**: 直接在浏览器中使用终端
- 🖥️ **完整Shell功能**: 支持bash命令、文件操作等
- 🔄 **实时通信**: 基于WebSocket的低延迟通信
- 📱 **响应式设计**: 适配不同屏幕尺寸
- 🔐 **用户认证**: 内置用户名密码认证系统
- 🛡️ **会话管理**: 支持会话超时和自动清理
- 🔒 **安全可靠**: 支持禁用认证的选项（仅限开发环境）

## 启动方式

### 方式1: 使用TTY专用Docker Compose文件（推荐）

```bash
# 修改认证密码（非常重要！）
# 编辑 docker-compose-tty.yml，将 WEB_TTY_PASSWORD 改为安全密码

# 启动Web TTY模式
docker-compose -f docker-compose-tty.yml up -d

# 查看日志
docker-compose -f docker-compose-tty.yml logs -f

# 停止服务
docker-compose -f docker-compose-tty.yml down
```

### 方式2: 修改现有docker-compose.yml

在 `docker-compose.yml` 中添加环境变量：

```yaml
environment:
  - WEB_TTY=true  # 启用Web TTY模式
  - WEB_TTY_USERNAME=admin  # 用户名
  - WEB_TTY_PASSWORD=your_secure_password  # 密码，请修改！
```

然后正常启动：

```bash
docker-compose up -d
```

### 方式3: 直接运行Web TTY服务器

```bash
# 进入容器
docker exec -it Intelligent-Literature-Review bash

# 启动Web TTY服务器（使用默认认证）
python src/web_tty_server.py --serve-html --host 0.0.0.0 --port 8888

# 或指定用户名密码
python src/web_tty_server.py --serve-html --host 0.0.0.0 --port 8888 --username admin --password your_password

# 或禁用认证（仅限开发环境！）
python src/web_tty_server.py --serve-html --host 0.0.0.0 --port 8888 --disable-auth
```

## 使用方法

1. **启动服务后，在浏览器中访问**:
   ```
   http://localhost:8888
   ```

2. **认证登录**:
   - 🔐 **输入凭据**: 输入用户名和密码（默认: admin/password）
   - ⚠️ **修改密码**: 首次使用请务必修改默认密码！
   - 🔑 **会话管理**: 登录后会话持续1小时，超时需重新登录

3. **终端功能**:
   - 🟢 **启动Shell**: 点击按钮启动bash shell
   - ⌨️ **输入命令**: 在输入框中输入命令，按Enter执行
   - 🧹 **清屏**: 清空终端显示
   - 🔌 **断开连接**: 断开WebSocket连接
   - 🚪 **退出登录**: 安全退出当前会话

4. **支持的Shell**:
   - Linux: `/bin/bash` (默认)
   - Windows: `cmd.exe`

5. **安全特性**:
   - 🔒 **密码哈希**: 密码使用SHA-256加密存储
   - ⏰ **会话超时**: 1小时自动超时，需重新登录
   - 🧹 **自动清理**: 定期清理过期会话
   - 🚫 **访问控制**: 未认证用户无法访问终端功能

## 技术架构

### 后端架构
- **语言**: Python 3.10+
- **WebSocket库**: websockets
- **进程管理**: asyncio subprocess
- **HTTP服务**: aiohttp (可选HTML页面)
- **认证系统**: 自定义认证管理器
- **会话管理**: 基于token的会话机制

### 前端架构
- **WebSocket客户端**: 原生JavaScript WebSocket API
- **终端界面**: HTML + CSS + JavaScript
- **认证界面**: 独立的登录页面
- **样式**: 黑客风格绿色终端主题

### 核心功能
1. **WebSocket连接管理**: 支持多客户端连接
2. **用户认证**: 用户名密码验证
3. **会话管理**: 会话创建、验证、超时处理
4. **Shell进程管理**: 每个连接独立的shell进程
5. **实时数据传输**: 输入输出实时同步
6. **资源清理**: 连接断开时自动清理进程和会话
7. **安全防护**: 密码哈希、会话超时、访问控制

## 配置选项

### 服务器参数
```bash
python src/web_tty_server.py --help
```

- `--host`: 服务器地址 (默认: 0.0.0.0)
- `--port`: 服务器端口 (默认: 8888)
- `--serve-html`: 同时提供HTML页面
- `--disable-auth`: 禁用认证 (仅限开发环境!)
- `--username`: 认证用户名 (默认从环境变量读取)
- `--password`: 认证密码 (默认从环境变量读取)

### 环境变量配置
- `WEB_TTY_USERNAME`: Web TTY用户名 (默认: admin)
- `WEB_TTY_PASSWORD`: Web TTY密码 (默认: password，请修改!)

### Docker配置
- **端口映射**: 8888:8888
- **环境变量**:
  - `WEB_TTY=true`: 启用Web TTY模式
  - `WEB_TTY_USERNAME=admin`: 用户名
  - `WEB_TTY_PASSWORD=your_secure_password`: 密码，请修改！
- **TTY模式**: 必须启用 `stdin_open: true` 和 `tty: true`

## 安全注意事项

⚠️ **重要安全提醒**:

1. **修改默认密码**: 首次使用必须修改默认密码！
2. **生产环境**: 不要在公网暴露Web TTY端口
3. **访问控制**: 建议通过防火墙限制访问IP
4. **数据保护**: 避免在Web TTY中输入敏感信息
5. **权限管理**: 容器内权限不要太高
6. **会话安全**: 会话超时后需要重新认证
7. **日志监控**: 定期检查认证日志和连接日志
8. **HTTPS部署**: 生产环境建议使用HTTPS/WSS

## 故障排除

### 常见问题

**Q: 无法连接到Web TTY**
A: 检查端口映射和防火墙设置

**Q: Shell启动失败**
A: 检查容器是否有/bin/bash，尝试切换到/bin/sh

**Q: 输入没有响应**
A: 检查Shell进程是否正常运行，查看容器日志

**Q: 页面显示异常**
A: 清除浏览器缓存，尝试刷新页面

**Q: 认证失败**
A: 检查用户名和密码是否正确，查看环境变量配置

**Q: 会话频繁过期**
A: 检查会话超时设置，确保网络连接稳定

**Q: 忘记密码**
A: 通过环境变量重新设置密码并重启容器

### 调试命令

```bash
# 查看容器日志
docker logs Intelligent-Literature-Review

# 进入容器检查
docker exec -it Intelligent-Literature-Review bash

# 测试WebSocket连接
wscat -c ws://localhost:8888/ws
```

## 高级用法

### 自定义Shell类型

修改HTML页面中的shell启动命令：
```javascript
ws.send(JSON.stringify({
    type: 'start_shell',
    shell: '/bin/zsh'  // 使用zsh
}));
```

### 集成到现有项目

可以作为独立的终端服务集成到任何Python项目中：

```python
from web_tty_server import WebTTYServer

# 创建服务器
server = WebTTYServer(host='0.0.0.0', port=8888)

# 启动服务器
await server.start_server()
```

## 与原Flask方案对比

| 特性 | Flask方案 | Web TTY方案 |
|------|-----------|-------------|
| 复杂度 | 高 (Flask+SocketIO) | 低 (纯WebSocket) |
| 依赖 | 多 (Flask等) | 少 (仅websockets) |
| 功能 | 完整Web应用 | 专注终端 |
| 性能 | 较好 | 极好 |
| 维护 | 复杂 | 简单 |
| **认证** | 基础Flask-Login | **内置安全认证** |
| **会话** | 基础session | **安全token会话** |

## 老王的建议

- **开发环境**: 使用Web TTY，简单高效
- **生产环境**: 禁用Web TTY，使用SSH
- **调试工具**: Web TTY是很好的容器调试工具
- **教学演示**: 适合演示和教学场景

## 🎯 总结

✅ **已完成的功能**:
- 🔐 用户认证系统（用户名+密码）
- 🛡️ 会话管理（1小时超时）
- 🧹 自动清理过期会话
- 🔒 密码SHA-256加密
- 📱 美观的登录界面
- ⚠️ 安全警告和提示

✅ **安全特性**:
- 访问控制：未认证用户无法使用终端
- 会话安全：自动超时和清理
- 密码保护：哈希存储，不传输明文
- 可配置：支持环境变量和命令行参数

**老王我保证，这套Web TTY认证方案绝对安全可靠！既简单又好用，还比你那些SB Flask方案安全多了！** 🚀