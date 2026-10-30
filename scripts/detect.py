# social-deai · 维护人：周逸帆（飞书联系） · MIT 许可，见仓库根的 LICENSE
"""检测：命中哪些 AI 写法、AI 味打几分。只用标准库，不调模型。
用法：
  python3 detect.py 文件.txt            # 检测整个文件
  echo "一段话" | python3 detect.py     # 检测标准输入
  python3 detect.py --lines < 评论.txt  # 每行一条，输出 JSON 数组（批量查评论）
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patterns import BOOKISH_WORDS, INSIGHT_WORDS, PATTERNS

# 伪洞察词真人也常用：每百字出现几次以内不扣分
INSIGHT_FREE_PER_100 = 0.6


def find(text):
    hits = []
    for rid, name, pat, tier, hint in PATTERNS:
        for m in pat.finditer(text):
            hits.append({"id": rid, "name": name, "text": m.group(0), "tier": tier, "hint": hint})
    return hits


def _cv(xs):
    """变异系数：长短起伏。真人句长起伏大（约 0.6~1.2），AI 像节拍器（0.2~0.4）"""
    if len(xs) < 2:
        return 0.0
    mean = sum(xs) / len(xs)
    return (sum((x - mean) ** 2 for x in xs) / len(xs)) ** 0.5 / max(mean, 1e-9)


def score(text):
    """AI 味分（越低越像人）。只做相对排序，绝对值没有含义。"""
    plain = re.sub(r"#[^\s#]+", "", text)
    sentences = [s for s in re.split(r"[。！？!?\n]+", plain) if s.strip()]
    hits = find(text)
    n100 = max(len(plain) / 100, 1)
    insight = sum(plain.count(w) for w in INSIGHT_WORDS)
    parts = {
        "红线句式": 3 * sum(h["tier"] == "red" for h in hits),
        "常见句式": 1 * sum(h["tier"] == "soft" for h in hits),
        "书面词": sum(plain.count(w) for w in BOOKISH_WORDS),
        "伪洞察词": round(max(0.0, insight / n100 - INSIGHT_FREE_PER_100) * 2, 2),
        "句长太匀": round(max(0.0, 0.6 - _cv([len(s) for s in sentences])) * 10, 2) if len(sentences) >= 3 else 0.0,
    }
    return {"total": round(sum(parts.values()), 2), **parts}


def verdict(text):
    """red = 有红线句式，必须改；ok = 没有红线（soft 命中和分数仅供参考）"""
    hits = find(text)
    red = [h for h in hits if h["tier"] == "red"]
    return {"status": "red" if red else "ok", "red": red,
            "soft": [h for h in hits if h["tier"] == "soft"], "score": score(text)}


def main(argv):
    lines = "--lines" in argv
    args = [a for a in argv if not a.startswith("--")]
    text = open(args[0], encoding="utf-8").read() if args else sys.stdin.read()
    if lines:
        out = [{"text": t, **verdict(t)} for t in text.splitlines() if t.strip()]
    else:
        out = verdict(text)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
