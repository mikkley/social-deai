# social-deai · 维护人：周逸帆（飞书联系） · MIT 许可，见仓库根的 LICENSE
"""生成：评论按说话手法写、正文多个模型各写一版挑最好的、去味改写（改坏了退回原文）。
只做「去 AI 味」这一层：事实、品牌用词、格式由调用方的提示词管，这里不替你决定写什么。"""
import collections, concurrent.futures, contextvars, os, random, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detect, llm, store

MOVES_MIN = 15
MOVE_KIND = {"sharp": ("刻薄",), "mild": ("温和", "情绪"), "short": ("情绪",)}
# 同一篇里同一种手法最多用几次：刻薄的辨识度高，用多了一眼就是套路
MOVE_CAP = {"刻薄": 2, "温和": 4, "情绪": 4}
MOVE_EXAMPLES = 2
SHORT, MID = 15, 35
LENGTH_WORDS = {"短": "十几个字以内", "中": "二三十个字", "长": "四五十个字，可以说一小段"}
LENGTH_MIX = {"短": 0.4, "中": 0.4, "长": 0.2}   # 可在 config.json 的 length_mix 里改成你们真评论的比例
PHRASE_CAP = 2   # 同一个四字说法，一篇最多出现几条评论里
COPY_SIM = 0.5   # 和给出的例子字面相似超过这个，算借了例子的梗


class NotReady(Exception):
    pass


def sim(a, b):
    ca, cb = set(a), set(b)
    return len(ca & cb) / max(1, len(ca | cb))


def _norm(s):
    return re.sub(r"[^\w一-鿿]", "", s)


def bucket(text):
    n = len(text)
    return "短" if n <= SHORT else ("中" if n <= MID else "长")


def usage_order(items, rng, usage, used=()):
    """用得少的优先：按 1/(1+使用次数) 加权随机排序；本批已经用过的排到最后"""
    def key(x):
        w = 1.0 / (1 + usage.get(x["id"], 0))
        return (x["id"] in used, -(rng.random() ** (1 / w)))
    return sorted(items, key=key)


def load_moves(cfg):
    """手法清单 + 例子原文。例子要是「生效」状态的评论；少于 2 个例子的手法不要"""
    d = cfg["dir"]
    by_id = {r["id"]: r for r in store.load_corpus(d) if r.get("状态") == "生效"}
    out = []
    for m in store.load_moves(d):
        if m.get("停用"):
            continue
        ex = [by_id[i] for i in m.get("例子", []) if i in by_id]
        if len(ex) >= 2:
            out.append({**m, "examples": ex})
    return out


def plan_moves(cfg, theme, rng, used=()):
    """给每个意思配手法 + 长短 + 例子。刻薄的位置配刻薄手法，温和的位置绝不借刻薄手法。
    返回 [(意思, 手法, 长短, [例子])]"""
    moves = load_moves(cfg)
    if len(moves) < MOVES_MIN:
        raise NotReady(f"可用手法只有 {len(moves)} 种，至少要 {MOVES_MIN} 种：先跑准备阶段（SKILL.md 的「第一次使用」），"
                       "或者语料太少、停用太多，补充语料后重新提炼")
    slots = cfg["comment_slots"][theme]
    usage = store.load_usage(cfg["dir"])
    count = collections.Counter()
    total = sum(n for _, _, n in slots)
    mix = cfg.get("length_mix") or LENGTH_MIX
    quota = {b: round(total * p) for b, p in mix.items()}
    quota["短"] -= sum(n for _, kind, n in slots if kind == "short")
    weight = lambda m: 1.0 / (1 + sum(usage.get(x["id"], 0) for x in m["examples"]) / len(m["examples"]))
    plan = []
    for intent, kind, n in slots:
        for _ in range(n):
            ok = [m for m in moves if count[m["名字"]] < MOVE_CAP.get(m["性质"], 2)]
            fit = [m for m in ok if m["性质"] in MOVE_KIND[kind]]
            if not fit:
                # 退路不对称：刻薄的位置可以借温和手法；温和的位置宁可让同一种手法超次，也不借刻薄手法
                fit = ([m for m in ok if kind == "sharp"] or [m for m in moves if m["性质"] in MOVE_KIND[kind]] or moves)
            m = max(fit, key=lambda m: rng.random() ** (1 / weight(m)))
            count[m["名字"]] += 1
            if kind == "short":
                size = "短"
            else:
                left = [b for b, q in quota.items() if q > 0] or list(quota)
                size = rng.choices(left, weights=[max(quota[b], 1) for b in left])[0]
                quota[size] -= 1
            ex = usage_order(m["examples"], rng, usage, used)
            same = [x for x in ex if bucket(x["text"]) == size]
            plan.append((intent, m, size, (same + [x for x in ex if x not in same])[:MOVE_EXAMPLES]))
    rng.shuffle(plan)
    return plan


def comment_prompt(post, plan, rules=""):
    rows = "\n".join(
        f"{i + 1}. 【{m['名字']}】{m['怎么用']}。真人这样用过：{'、'.join('「' + x['text'] + '」' for x in exs)}"
        f"\n   → 这条要写：{intent}；{LENGTH_WORDS[size]}"
        for i, (intent, m, size, exs) in enumerate(plan))
    return f"""帮我给下面这篇帖子写评论区，要像真实网友随手回的。

【帖子】
{post}

（评论里说到楼主的事，只能是上面帖子里写了的：帖子没写的人、事、数字都别编）

【怎么写】
下面每一行给了一种真人评论常用的说话手法，带着真人用过的例子，后面是这一条要写的意思和长短。逐条写：
- 每条都抓住帖子里一个具体的东西来说：楼主说过的一句话、做过的一件事、提到的一个人。只发情绪的那几条可以不抓
- 例子只看它是怎么说的。它的词、它的梗、它说的事一个都不许借
- 不讲道理、不总结、不列一二三。真人回帖就是随口一句态度，不负责教育楼主
- 箭头后面写的意思用你自己的话说，别照抄那几个字；各条之间别有同一句话反复出现
- 表情跟真人差不多，三四条带就够
- 真人评论有错别字、不完整的句子、没头没尾，都正常，别修得太整齐
- 不带问号

{rules}

【逐条写】
{rows}

【输出格式】
编号 1~{len(plan)}，一行一条，只输出评论本身，不要写手法名，不要解释。"""


def parse_numbered(text):
    out = []
    for line in text.split("\n"):
        m = re.match(r"\s*\d{1,2}(?:\s*[.、．)）:：]|\s+)\s*(.+)", line)
        if m:
            c = re.sub(r"\s*#[^\s#]+", "", m.group(1)).strip().strip("「」\"“”*")
            if c:
                out.append(c)
    return out


def _one_batch(model, prompt, srcs):
    r = llm.call(model, prompt)
    if not r["ok"]:
        return r, []
    return r, [c for c in parse_numbered(r["content"]) if not any(sim(_norm(c), s) >= COPY_SIM for s in srcs)]


def pick(cands, need, rng, avoid=()):
    """程序挑：过红线、剔掉和历史/已选太像的，再每次取与已选最不像的一条；同一个四字说法最多 PHRASE_CAP 条"""
    phrases = lambda t: {t[i:i + 4] for i in range(len(t) - 3)} if len(t) >= 4 else set()
    valid = []
    for c in cands:
        if detect.verdict(c)["status"] == "red" or "#" in c:
            continue
        n = _norm(c)
        if any(sim(n, _norm(a)) >= 0.85 for a in avoid) or any(sim(n, _norm(v)) >= 0.85 for v in valid):
            continue
        valid.append(c)
    pool, picked, seen = valid[:], [], collections.Counter()
    rng.shuffle(pool)
    while pool and len(picked) < need:
        pool = [c for c in pool if all(seen[p] < PHRASE_CAP for p in phrases(_norm(c)))]
        if not pool:
            break
        best = min(pool, key=lambda c: max((sim(_norm(c), _norm(p)) for p in picked), default=0))
        picked.append(best)
        pool.remove(best)
        seen.update(phrases(_norm(best)))
    rng.shuffle(picked)
    return picked


def write_comments(cfg, theme, post, models, rng, need=None, avoid=(), rules="", record_usage=True):
    """前两个模型同时写，挑不够 need 条再叫后面的。返回 {comments, used_ids, dropped_copies, models}"""
    need = need or sum(n for _, _, n in cfg["comment_slots"][theme])
    used_ids, cands, dropped, wrote = [], [], 0, []
    for group in (models[:2], models[2:]):
        jobs = []
        for m in group:
            plan = plan_moves(cfg, theme, rng, set(used_ids))
            exs = [x for _, _, _, xs in plan for x in xs]
            used_ids += [x["id"] for x in exs]
            jobs.append((m, comment_prompt(post, plan, rules), [_norm(x["text"]) for x in exs]))
        if not jobs:
            continue
        with concurrent.futures.ThreadPoolExecutor(len(jobs)) as ex:
            futs = [ex.submit(contextvars.copy_context().run, _one_batch, m, p, srcs) for m, p, srcs in jobs]
            for (m, _, _), f in zip(jobs, futs):
                r, kept = f.result()
                if r["ok"]:
                    wrote.append(m)
                    cands += kept
                    dropped += len(parse_numbered(r["content"])) - len(kept)
        picked = pick(cands, need, rng, avoid)
        if len(picked) >= need:
            break
    ids = list(dict.fromkeys(used_ids))
    if record_usage:
        store.bump_usage(cfg["dir"], ids)
    return {"comments": picked, "used_ids": ids, "dropped_copies": dropped, "models": wrote}


def write_post(cfg, theme, prompt, models):
    """多个模型同时各写一版，去掉有红线句式的，挑 AI 味分最低的。提示词由你写（事实、品牌用词、格式都在里面）"""
    with concurrent.futures.ThreadPoolExecutor(len(models)) as ex:
        futs = [ex.submit(contextvars.copy_context().run, llm.call, m, prompt) for m in models]
        results = [f.result() for f in futs]
    kept, errors = [], []
    for m, r in zip(models, results):
        if not r["ok"]:
            errors.append(f"{m}: {r['error']}")
            continue
        v = detect.verdict(r["content"])
        if v["status"] == "ok":
            kept.append({"model": m, "text": r["content"], "score": v["score"]["total"]})
        else:
            errors.append(f"{m}: 有红线句式 {[h['id'] for h in v['red']]}")
    if not kept:
        return {"text": None, "model": None, "kept": [], "errors": errors}
    best = min(kept, key=lambda k: k["score"])
    return {"text": best["text"], "model": best["model"], "kept": kept, "errors": errors}


DEVIBE_PROMPT = """下面是一篇社交平台帖子，已经写好了。帮我只做一件事：把读起来像 AI 写的地方改成真人随手发帖的样子。

【只准改表达】
- 句子长短要有起伏：长句后面跟个几个字的短句，别连着三句差不多长
- 删书面过渡词和总结腔：此外、因此、然而、总之、事实上、说到底
- 不升华不讲道理：段尾不复述主题，结尾不总结人生感悟
- 四字词、成语少用，换成大白话；「进行了沟通」这种欧化说法改成「聊了」
- 能一句话说完的不拆成分点罗列

【不准动】
- 事实、数字、人物、情节先后，一个都不改，不加新情节
- 标题、话题标签、品牌和规范用词原样保留
- 结构和格式不变

{rules}

直接输出改好的全文，格式跟原文一样，不要解释。

原文：
{text}"""


# 去味后和原文相似度的下限，按去标点后的字数定。短稿改几个词相似度就掉得多，保持 0.6；
# 长稿去味要动的地方多，196 字的稿子去味后相似度 0.527、事实没动，0.6 会把它退回原文
MIN_SIM_SHORT, MIN_SIM_LONG = 0.6, 0.45
SHORT_LEN, LONG_LEN = 100, 200


def auto_min_sim(text):
    n = len(_norm(text))
    if n <= SHORT_LEN:
        return MIN_SIM_SHORT
    if n >= LONG_LEN:
        return MIN_SIM_LONG
    return round(MIN_SIM_SHORT - (MIN_SIM_SHORT - MIN_SIM_LONG) * (n - SHORT_LEN) / (LONG_LEN - SHORT_LEN), 3)


def devibe(text, model, rules="", min_sim=None):
    """去味改写一遍。改完要重新过红线、不能被改得面目全非（字面相似 ≥ 下限，不传 min_sim 就按字数取 auto_min_sim）、
    AI 味分不能比原来高；任何一条不满足就用原文。返回 (文本, 说明)"""
    floor = auto_min_sim(text) if min_sim is None else min_sim
    r = llm.call(model, DEVIBE_PROMPT.format(rules=rules, text=text))
    if not r["ok"]:
        return text, "去味调用失败，用原文"
    new = r["content"].strip()
    v = detect.verdict(new)
    if v["status"] != "ok":
        return text, f"去味后出现红线句式 {[h['id'] for h in v['red']]}，用原文"
    s = sim(_norm(text), _norm(new))
    if s < floor:
        return text, f"去味改动太大（可能动了事实），用原文：相似度 {s:.3f}，下限 {floor}"
    if v["score"]["total"] > detect.score(text)["total"]:
        return text, "去味后 AI 味分反而更高，用原文"
    return new, "已去味"


def batch_check(posts, threshold=0.5):
    """一批帖子互相查重：返回字面相似度 ≥ threshold 的 (i, j) 对。正文建议 0.5，标题 0.8"""
    return [(i, j) for i in range(len(posts)) for j in range(i + 1, len(posts))
            if sim(_norm(posts[i]), _norm(posts[j])) >= threshold]
