# -*- coding: utf-8 -*-
"""
FreePort 本地免费模型网关（最小可用版 · 开源原创）
- 自管 OpenCode 隔离运行时（spawn `opencode serve`）
- 暴露 OpenAI 兼容端点：GET /health, GET /v1/models, POST /v1/chat/completions
- 把 OpenAI 格式请求翻译成 OpenCode 会话消息，回 OpenAI 格式（支持 SSE stream）
- 只声明 WORKING_MODELS 里经本地实测可用的免费模型

安全纪律：
- 本机口拒绝带 Origin 的请求（不给浏览器用）
- 鉴权：Authorization: Bearer <api-key>，key 由本机首次运行时自动生成写入 api-key 文件
- 模型只回 JSON 信封，执行权在被接管的客户端（dsh / WorkBuddy）
"""
import io
import json
import os
import subprocess
import threading
import time
import uuid
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from shutil import which

# ---------- 配置（全部可用环境变量覆盖，不硬编码机器路径） ----------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PREFIX = "Free · "  # dsh / WorkBuddy 里模型显示前缀，可改
PORT = int(os.environ.get("FREE_PORT_PORT", "41980"))
OC_PORT = int(os.environ.get("FREE_PORT_OC_PORT", "4096"))
DATA_DIR = os.environ.get("FREE_PORT_DATA", SCRIPT_DIR)
API_KEY_FILE = os.path.join(DATA_DIR, "api-key")
BASE = f"http://127.0.0.1:{OC_PORT}"

# 经本地 server 实测可用的免费模型（替换成你那边 opencode 免费池里验证过的 id）
WORKING_MODELS = ["glm-5.3-flash-free", "deepseek-v4.1-flash-free", "big-pickle"]


def find_opencode():
    """定位 opencode 二进制：环境变量 > 脚本同目录 tools > PATH"""
    if os.environ.get("FREE_PORT_OPENCODE_BIN"):
        return os.environ["FREE_PORT_OPENCODE_BIN"]
    candidates = [
        os.path.join(SCRIPT_DIR, "tools", "node_modules", "opencode-windows-x64", "bin", "opencode.exe"),
        os.path.join(SCRIPT_DIR, "tools", "node_modules", ".bin", "opencode"),
        os.path.join(SCRIPT_DIR, "opencode.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return which("opencode")


OC_BIN = find_opencode()

# ---------- 工具函数 ----------
def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def no_proxy():
    for k in list(os.environ):
        if k.upper().endswith("_PROXY"):
            os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def oc_req(method, path, body=None, timeout=180):
    no_proxy()
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as f:
            return f.status, f.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return "EXC", str(e)


def get_api_key():
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(API_KEY_FILE):
        return io.open(API_KEY_FILE, encoding="utf-8").read().strip()
    key = uuid.uuid4().hex + uuid.uuid4().hex[:16]
    io.open(API_KEY_FILE, "w", encoding="utf-8").write(key)
    try:
        os.chmod(API_KEY_FILE, 0o600)
    except Exception:
        pass
    return key


API_KEY = get_api_key()

# ---------- OpenCode 运行时管理 ----------
oc_proc = None
oc_lock = threading.Lock()


def start_opencode():
    global oc_proc
    if not OC_BIN:
        log("!! 找不到 opencode 二进制，请安装后设置 FREE_PORT_OPENCODE_BIN（见 README）")
        return False
    st, _ = oc_req("GET", "/doc", timeout=3)
    if st == 200:
        log("opencode 已在运行")
        return True
    log("启动 opencode serve ...")
    try:
        oc_proc = subprocess.Popen(
            [OC_BIN, "serve", "--port", str(OC_PORT), "--hostname", "127.0.0.1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except Exception as e:
        log("!! 启动失败:", e)
        return False
    for _ in range(30):
        time.sleep(1)
        st, _ = oc_req("GET", "/doc", timeout=3)
        if st == 200:
            log("opencode serve 就绪 (pid %s)" % oc_proc.pid)
            return True
    log("!! opencode 30s 内未就绪")
    return False


def stop_opencode():
    global oc_proc
    if oc_proc:
        try:
            oc_proc.terminate()
        except Exception:
            pass


# ---------- 核心：一次对话 ----------
def run_chat(model_id, system, history_user_texts, final_text, tools, stream):
    st, txt = oc_req("POST", "/session", {})
    if st != 200:
        return None, f"无法创建会话: HTTP {st}"
    try:
        sid = json.loads(txt).get("id")
    except Exception:
        return None, "会话响应解析失败"
    if not sid:
        return None, "会话 id 缺失"

    for ut in history_user_texts:
        oc_req("POST", f"/session/{sid}/message", {
            "model": {"providerID": "opencode", "modelID": model_id},
            "agent": "build", "tools": {},
            "parts": [{"type": "text", "text": ut}],
            "noReply": True,
        }, timeout=60)

    body = {
        "model": {"providerID": "opencode", "modelID": model_id},
        "agent": "build",
        "tools": {t["function"]["name"]: True for t in tools} if tools else {},
        "parts": [{"type": "text", "text": final_text}],
    }
    if system:
        body["system"] = system
    st, txt = oc_req("POST", f"/session/{sid}/message", body, timeout=480)
    if st != 200:
        return None, f"推理请求失败: HTTP {st} {txt[:200]}"
    try:
        obj = json.loads(txt)
    except Exception:
        return None, "推理响应解析失败"

    err = obj.get("info", {}).get("error")
    if err:
        return None, f"上游错误: {err.get('data', {}).get('message', str(err))[:240]}"

    parts = obj.get("parts", [])
    content = ""
    reasoning = ""
    tool_calls = []
    for p in parts:
        if p.get("type") == "text" and p.get("text"):
            content += p["text"]
        elif p.get("type") == "reasoning" and p.get("text"):
            reasoning += p["text"]
        elif p.get("type") == "tool":
            args = p.get("metadata", {})
            if isinstance(args, dict):
                args = args.get("input", args)
            tool_calls.append({
                "id": p.get("callID") or ("call_" + uuid.uuid4().hex[:8]),
                "type": "function",
                "function": {
                    "name": p.get("tool", "unknown"),
                    "arguments": json.dumps(args, ensure_ascii=False) if not isinstance(args, str) else args,
                },
            })
    usage = obj.get("info", {}).get("tokens", {})
    return {
        "content": content,
        "reasoning": reasoning,
        "tool_calls": tool_calls,
        "usage": usage,
    }, None


# ---------- HTTP 处理 ----------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj, headers=None):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _auth_ok(self):
        return self.headers.get("Authorization", "") == ("Bearer " + API_KEY)

    def do_GET(self):
        if self.path in ("/health", "/health/"):
            st, _ = oc_req("GET", "/doc", timeout=3)
            self._send(200, {
                "status": "ok" if st == 200 else "opencode_down",
                "opencode_connected": st == 200,
                "models": [(MODEL_PREFIX + m) for m in WORKING_MODELS],
                "port": PORT,
            })
        elif self.path in ("/v1/models", "/v1/models/"):
            self._send(200, {
                "object": "list",
                "data": [{"id": MODEL_PREFIX + m, "object": "model", "owned_by": "opencode-free"}
                         for m in WORKING_MODELS],
            })
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if "Origin" in self.headers:
            log(f"[blocked] Origin forbidden: {self.headers.get('Origin')!r}")
            self._send(403, {"error": "browser origin forbidden"})
            return
        if not self._auth_ok():
            self._send(401, {"error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            self._send(400, {"error": "bad json"})
            return

        if self.path == "/v1/chat/completions":
            self.handle_chat(body)
        elif self.path.startswith("/admin/"):
            self._send(200, {"ok": True, "note": "admin stub"})
        else:
            self._send(404, {"error": "not found"})

    def _send_sse(self, model, result):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        cid = "chatcmpl-" + uuid.uuid4().hex[:12]
        created = int(time.time())

        def emit(delta, finish=None):
            chunk = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                     "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            self.wfile.write(b"data: " + json.dumps(chunk, ensure_ascii=False).encode("utf-8") + b"\n\n")
            self.wfile.flush()

        emit({"role": "assistant"})
        if result["reasoning"]:
            emit({"reasoning_content": result["reasoning"]})
        if result["content"]:
            emit({"content": result["content"]})
        if result["tool_calls"]:
            for i, tc in enumerate(result["tool_calls"]):
                emit({"tool_calls": [{"index": i, "id": tc["id"], "type": "function",
                                      "function": {"name": tc["function"]["name"],
                                                   "arguments": tc["function"]["arguments"]}}]})
        u = result["usage"]
        finish = "tool_calls" if result["tool_calls"] else "stop"
        chunk = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                 "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                 "usage": {"prompt_tokens": u.get("input", 0), "completion_tokens": u.get("output", 0),
                           "total_tokens": u.get("input", 0) + u.get("output", 0)}}
        self.wfile.write(b"data: " + json.dumps(chunk, ensure_ascii=False).encode("utf-8") + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def handle_chat(self, body):
        model = body.get("model", "")
        raw_model = model
        if model.startswith(MODEL_PREFIX):
            model = model[len(MODEL_PREFIX):]
        log(f"[req] model={raw_model!r} stream={body.get('stream')}")
        if model not in WORKING_MODELS:
            self._send(400, {"error": f"未知/不可用模型: {model}。可用: {WORKING_MODELS}"})
            return

        messages = body.get("messages", [])
        system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        conv = [m for m in messages if m.get("role") != "system"]
        if not conv:
            self._send(400, {"error": "无消息"})
            return
        history_user = [m.get("content", "") for m in conv[:-1] if m.get("role") == "user"]
        final = conv[-1].get("content", "")
        tools = body.get("tools")

        result, err = run_chat(model, system, history_user, final, tools, body.get("stream"))
        if err:
            log(f"[err] model={model} -> {err}")
            self._send(502, {"error": err})
            return

        if body.get("stream"):
            self._send_sse(MODEL_PREFIX + model, result)
            return

        msg = {"role": "assistant", "content": result["content"] or None}
        if result["reasoning"]:
            msg["reasoning_content"] = result["reasoning"]
        if result["tool_calls"]:
            msg["tool_calls"] = result["tool_calls"]

        resp = {
            "id": "chatcmpl-" + uuid.uuid4().hex[:12],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_PREFIX + model,
            "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if result["tool_calls"] else "stop"}],
            "usage": {
                "prompt_tokens": result["usage"].get("input", 0),
                "completion_tokens": result["usage"].get("output", 0),
                "total_tokens": (result["usage"].get("input", 0) + result["usage"].get("output", 0)),
            },
        }
        self._send(200, resp)


def main():
    if not start_opencode():
        log("!! OpenCode 启动失败，代理仍将监听但聊天会返回 503")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log(f"FreePort 代理监听 http://127.0.0.1:{PORT}  (api-key: {API_KEY[:8]}...)")
    log("可用模型: " + ", ".join(MODEL_PREFIX + m for m in WORKING_MODELS))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_opencode()


if __name__ == "__main__":
    main()
