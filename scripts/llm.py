# social-deai · 维护人：周逸帆（飞书联系） · MIT 许可，见仓库根的 LICENSE
"""调模型：OpenAI 兼容的 /chat/completions 接口，只用标准库。
配置从环境变量读（也可以放在项目的 social-deai.json 里，见 config.py）：
  SOCIAL_DEAI_API_BASE   例如 https://api.openai.com/v1/chat/completions
  SOCIAL_DEAI_API_KEY    密钥（不要写进仓库）
  SOCIAL_DEAI_MODEL_STRONG   归纳手法用的强模型（要懂中文网络语境）
  SOCIAL_DEAI_MODEL_CHEAP    打标、归类用的便宜模型
  SOCIAL_DEAI_MODELS         写稿用的模型，逗号分隔，至少 2 个（多模型各写一版再挑）
"""
import json, os, urllib.error, urllib.request

MAX_TOKENS = 32000   # 推理模型先想后写，额度小了正文写不出来


def cfg(name, default=""):
    return os.environ.get("SOCIAL_DEAI_" + name) or default


def call(model, prompt, timeout=360, temperature=1.0):
    base, key = cfg("API_BASE"), cfg("API_KEY")
    if not (base and key and model):
        return {"ok": False, "error": "没配好模型：需要 SOCIAL_DEAI_API_BASE、SOCIAL_DEAI_API_KEY 和模型名（见 SKILL.md 的「配置」）"}
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": MAX_TOKENS, "temperature": temperature}
    req = urllib.request.Request(base, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        msg, finish = d["choices"][0]["message"], d["choices"][0].get("finish_reason", "")
        content = msg.get("content") or ""
        if not content and finish == "length":
            return {"ok": False, "error": "思考把输出额度用完了，正文没写出来"}
        if not content and msg.get("reasoning_content"):
            content = msg["reasoning_content"]
        return {"ok": True, "model": model, "content": content}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def call_json(model, prompt, open_ch="[", close_ch="]", tries=2, timeout=360):
    """模型偶尔格式不对（约六分之一批次），重试一次再放弃。返回解析后的对象或 None"""
    for _ in range(tries):
        r = call(model, prompt, timeout=timeout)
        if not r["ok"]:
            continue
        t = r["content"]
        try:
            return json.loads(t[t.find(open_ch):t.rfind(close_ch) + 1])
        except (ValueError, json.JSONDecodeError):
            continue
    return None
