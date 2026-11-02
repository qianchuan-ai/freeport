# FreePort

把 OpenCode 免费模型摆渡成 OpenAI 兼容端点，接入 dsh / WorkBuddy 等客户端。零付费 key。

原创最小实现，MIT 许可。

## 架构

```
客户端 ──OpenAI格式──> 127.0.0.1:41980 (freeport_proxy.py) ──> opencode serve (4096) ──> 免费模型
```

## 快速开始

```bash
# 1. 安装 opencode（代理会 spawn 它）
npm i -g opencode

# 2. 启动代理（保持窗口常驻）
py freeport_proxy.py          # 或 Windows: start_freeport.bat

# 3. 读 api-key，填进客户端的 FREE_PORT_KEY
cat api-key
```

接 dsh：把 `cordis.patch.freeport.example.yml` 的 `freeport:` 段合并进
`~/.dsh/profiles/desktop/cordis.patch.yml` 的 `id: llm-pi-ai` → `config.providers`，
在 `~/.dsh/.env` 写 `FREE_PORT_KEY=<api-key 内容>`，重启 dsh。

## 文件

| 文件 | 作用 |
|---|---|
| `freeport_proxy.py` | 本地网关（OpenAI 兼容 + OpenCode 翻译 + SSE） |
| `start_freeport.bat` | Windows 启动脚本（py launcher，CRLF + 纯 ASCII） |
| `cordis.patch.freeport.example.yml` | dsh 桌面端 patch 模板 |
| `SKILL.md` | 完整接法 / 排查 / 边界 |

## 配置（环境变量，均可覆盖）

| 变量 | 默认 | 说明 |
|---|---|---|
| `FREE_PORT_PORT` | `41980` | 网关监听端口 |
| `FREE_PORT_OC_PORT` | `4096` | opencode serve 端口 |
| `FREE_PORT_DATA` | 脚本目录 | api-key 等状态文件目录 |
| `FREE_PORT_OPENCODE_BIN` | 自动探测 | opencode 二进制路径 |

模型显示前缀由 `freeport_proxy.py` 里的 `MODEL_PREFIX`（默认 `Free · `）控制。

## 安全

- 本机口拒绝带 `Origin` 的请求（不给浏览器用）。
- 鉴权 `Bearer <api-key>`，key 首次运行自动生成写入 `api-key`（已 gitignore）。
- 提交前确认 `api-key` / `.env` / `*.log` / `tools/` 未被纳入版本库。

## License

MIT — 见 [LICENSE](LICENSE)。OpenCode 与上游免费模型由各自提供方授权。

---
作者 / 反馈：微信 **sheshouzuo3366**
