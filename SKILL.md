# FreePort · 本地免费模型网关接入 dsh（开源原创版）

> 把 OpenCode 的免费模型包装成 OpenAI 兼容端点（`http://127.0.0.1:41980/v1`），让 dsh / WorkBuddy 等客户端直接当自定义模型用。零付费 key，吃上游免费池。
> 原创最小实现，MIT 许可。配套文件：`freeport_proxy.py` / `start_freeport.bat` / `cordis.patch.freeport.example.yml`。

## 一句话原理

```
dsh 聊天框 ──OpenAI格式──> 127.0.0.1:41980 (freeport_proxy.py) ──OpenCode会话──> opencode serve (4096) ──> 免费模型
```
代理自管一个隔离的 `opencode serve` 进程，把 OpenAI 的 chat/completions 请求翻译成 OpenCode 会话消息，再原样回 OpenAI 格式（含 SSE 流）。鉴权用本地自动生成的 `api-key`，带浏览器 `Origin` 的请求一律 403（防外部调用）。

## 适用场景

- 想给 dsh 加一批**免费**模型，不烧 Agnes / 百炼等付费 key。
- 本地常驻一台小机器当“免费模型网关”，多个客户端共用。
- 作为“翻译层”范本：协议适配 + 本机安全围栏。

## 部署（3 步）

**① 准备 OpenCode 运行时**
```bash
npm i -g opencode        # 或下载官方 opencode 二进制
# 也可把二进制放 tools/node_modules/opencode-windows-x64/bin/opencode.exe
# 或设环境变量 FREE_PORT_OPENCODE_BIN=/path/to/opencode
```

**② 启动代理**（保持窗口常驻）
```bash
start_freeport.bat        # Windows，用 py launcher
# 或： py freeport_proxy.py
```
启动后读 `api-key` 文件内容（首次自动生成），这就是 dsh 要填的 `FREE_PORT_KEY`。

**③ 接入 dsh（桌面端）**
1. 把 `cordis.patch.freeport.example.yml` 里的 `freeport:` 段合并进
   `~/.dsh/profiles/desktop/cordis.patch.yml` 的 `id: llm-pi-ai` → `config.providers` 下。
2. 在 `~/.dsh/.env` 加一行：`FREE_PORT_KEY=<api-key 文件内容>`（明文不要入库）。
3. **重启 dsh 桌面端**（前端 SPA 不热加载 provider 列表）。

## 验证（必做）

```bash
# 代理健康
curl http://127.0.0.1:41980/health
# => {"status":"ok","opencode_connected":true,"models":["Free · ..."]}

# 直接推理（拿 api-key 文件当 token）
curl -s http://127.0.0.1:41980/v1/chat/completions \
  -H "Authorization: Bearer $(cat api-key)" -H "Content-Type: application/json" \
  -d '{"model":"Free · deepseek-v4.1-flash-free","messages":[{"role":"user","content":"你好"}]}'
```
dsh 里：聊天框模型选择器找 **"FreePort (OpenCode free)"** 分组，三个免费模型（`Free · ` 前缀）。

## 踩坑实录（照抄可省 2 小时）

1. **patch 的 id 必须是 `llm-pi-ai`**，不是 `llm`。写 `llm` 会 name-mismatch，整段 patch 被跳过，provider 全不生效。
2. **桌面端读 `profiles/desktop/`，网页端读 `profiles/web/`**。改错 profile = 没改。看不清就两个都加。
3. **改完必须重启 dsh 进程**。强刷页面没用，SPA 不重拉 provider 列表。
4. **代理必须常驻**：进程挂了，dsh 里 FreePort 模型发不出话。重启用 `start_freeport.bat`。
5. **Agnes 节点会轮换**（`apihub.agnes-ai.cn` 与 `api.agnes-ai.cn` 哪个通哪个挂，实测为准），别把节点写死当真理。
6. **推理模型空回复**：上游若是推理模型且 dsh 给的 `max_tokens` 太小，token 全被 reasoning 吃掉 → 回空。给 provider 加 `defaultMaxTokens: 8192`。

## 边界（诚实交代）

- 免费模型池由上游决定，随时上下线/限额；`WORKING_MODELS` 里的 id 哪天失效不奇怪，按本地实测更新。
- 本代理**多轮只回放 user 历史、无真函数调用**：当免费纯对话/翻译层最稳，别指望它跑复杂 tool 链。
- 不消耗你的付费 key——这正是接它的目的。

## 开源说明

- 代码原创、MIT 许可，可自由 fork / 商用。
- **密钥与本地状态已在 `.gitignore` 屏蔽**（`api-key`、`.env`、`*.log`、`tools/`）。发布前确认这些没被 `git add -f` 强加。
- 不打包 OpenCode 二进制与上游模型；使用者自装、自遵守其服务条款。
- 若你本地早期用过 `OC ·` 前缀的旧版：把 `freeport_proxy.py` 里的 `MODEL_PREFIX` 与 dsh patch 里的模型 id 前缀统一即可（旧名仅历史遗留，本版已去 OC 化）。

---
作者 / 反馈：微信 **sheshouzuo3366**
