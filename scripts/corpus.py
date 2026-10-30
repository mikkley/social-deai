# social-deai · 维护人：周逸帆（飞书联系） · MIT 许可，见仓库根的 LICENSE
"""语料处理：读原始数据 → 规则预筛 → 模型打标（质量、语气、每个主题的立场）→ 入库。
立场要对每个主题都判一遍：评论例子在不同主题之间会混用，只按自己主题判会漏
（一个项目里「他们不办就算了」放在主题甲下没事，借到主题乙就是劝人放弃）。"""
import csv, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detect, llm, store

TONES = ["平实", "劝导", "吐槽", "毒舌", "阴阳怪气", "情绪"]
PASS_SCORE = 3
BATCH = 10
LEN = {"评论": (6, 80), "笔记": (80, 800)}
# 引流话术：命中就不是「普通人说话」。可以在项目 config.json 里用 ad_words 追加
AD = re.compile(r"微信|vx|VX|v信|\+v|加我|私信我|私我|扫码|二维码|律所|代办|代理|包过|咨询我|主页|\d{6,}")

TAG_PROMPT = """下面是社交平台上的真实评论，我们要拿它们当「真人怎么说话」的范例。逐条打标签，只输出 JSON 数组，条数和编号跟输入一致，不要解释。

主题：{theme}
这个主题里，和我们要传达的相反的说法是：{stance}

{numbered}

[{{"编号": 1, "语气": "{tones}", "质量分": 1到5的整数, "立场冲突": "有|无", "辱骂": "有|无"}}, ...]

判断口径：
- 质量分：5=像真人随手发的，有个人口吻；3=一般；1=像广告、套话、说教、AI 腔
- 立场冲突：内容属于上面「相反的说法」，填「有」。骂代办、劝人正常走流程、自嘲、只描述自己处境，不算冲突
- 辱骂：对人身攻击、脏话，填「有」
直接输出 JSON，不要写思考过程。"""

NOTE_PROMPT = """下面是社交平台上的一篇真实帖子，我们要拿它当「真人怎么写」的范例。只输出 JSON，不要解释：

主题：{theme}
这个主题里，和我们要传达的相反的说法是：{stance}

帖子：「{content}」

{{"语气": "{tones}", "质量分": 1到5的整数, "营销味": "有|无", "立场冲突": "有|无", "形态": "长叙事|精简短帖"}}

判断口径：质量分 5=像真人随手发的、有具体经过；1=像广告、套话、AI 腔。营销味=在推销服务、引流。
立场冲突=内容属于上面「相反的说法」。形态：有完整经过算长叙事，几句话算精简短帖。"""


def read_raw(path):
    """读 CSV（表头至少有「内容」；可选「类型」评论|笔记、「所属帖子」、「点赞」）或 xlsx 的第一个 sheet"""
    if path.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        it = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True)
        head = [str(h or "").strip() for h in next(it)]
        raw = (dict(zip(head, row)) for row in it)
    else:
        raw = csv.DictReader(open(path, encoding="utf-8-sig"))
    out = []
    for r in raw:
        text = str(r.get("内容") or "").strip()
        if not text:
            continue
        out.append({"text": text, "kind": str(r.get("类型") or "评论").strip() or "评论",
                    "parent": str(r.get("所属帖子") or "").strip(), "likes": int(float(r.get("点赞") or 0))})
    return out


def prefilter(rows, extra_ad=None):
    """规则预筛：长度、去重、引流话术、红线句式（AI 腔的不能当真人范例）。不花钱"""
    ad = re.compile(AD.pattern + ("|" + "|".join(map(re.escape, extra_ad)) if extra_ad else ""))
    seen, out = set(), []
    for r in rows:
        t = r["text"].strip()
        lo, hi = LEN.get(r.get("kind", "评论"), LEN["评论"])
        if not (lo <= len(t) <= hi) or t in seen or ad.search(t) or detect.verdict(t)["status"] == "red":
            continue
        seen.add(t)
        out.append({**r, "text": t})
    return out


def _numbered(batch):
    return "\n".join(f"{i + 1}. {r['text']}" for i, r in enumerate(batch))


def tag(rows, cfg, model=None):
    """打标。评论：10 条一批，每批对每个主题各判一遍立场。笔记：一篇一次，对每个主题各判一遍。"""
    model = model or llm.cfg("MODEL_CHEAP")
    themes = cfg["themes"]
    out = []
    for r in rows:
        r = {**r, "id": store.row_id(r["text"]), "立场": {}, "状态": "待审核"}
        out.append(r)
    by_kind = {k: [r for r in out if r.get("kind", "评论") == k] for k in ("评论", "笔记")}
    for k in range(0, len(by_kind["评论"]), BATCH):
        batch = by_kind["评论"][k:k + BATCH]
        for theme in themes:
            got = llm.call_json(model, TAG_PROMPT.format(theme=theme, stance=cfg["projects"][theme]["stance"],
                                                         tones="|".join(TONES), numbered=_numbered(batch))) or []
            for x in got:
                try:
                    r = batch[int(x["编号"]) - 1]
                except (KeyError, ValueError, TypeError, IndexError):
                    continue
                if theme == themes[0]:
                    r["语气"] = x.get("语气") if x.get("语气") in TONES else ""
                    r["质量分"] = int(x.get("质量分") or 0)
                    r["辱骂"] = x.get("辱骂") == "有"
                r["立场"][theme] = x.get("立场冲突") == "有"
    for r in by_kind["笔记"]:
        for theme in themes:
            x = llm.call_json(model, NOTE_PROMPT.format(theme=theme, stance=cfg["projects"][theme]["stance"],
                                                        content=r["text"][:1200], tones="|".join(TONES)), "{", "}") or {}
            if theme == themes[0]:
                r.update({"语气": x.get("语气") or "", "质量分": int(x.get("质量分") or 0),
                          "营销味": x.get("营销味") == "有", "形态": x.get("形态") or ""})
            r["立场"][theme] = x.get("立场冲突") == "有"
    return out


RECHECK_PROMPT = """下面是社交平台上的一批真实评论，我们要拿它们当「真人怎么说话」的范例给写稿模型学。
我们的内容要传达的是：{stance_ok}
挑出立场和我们要传达的相反的评论，也就是：{stance}
只看它本身表达的立场。这些不算：骂代办、骂卖教程的；劝人正常走流程的；自嘲、吐槽自己的；只是描述自己处境、没有表态的。

主题：{theme}

{numbered}

只输出 JSON 数组：[{{"编号": 3, "为什么": "十五个字以内"}}]；一条都没有就输出 []。"""


def recheck(rows, cfg, model=None):
    """强模型复核立场。便宜模型打标会漏（我们的项目里 12 条已知立场不对的，便宜模型只抓到 4 条），
    所以每条评论、每个主题再让强模型单独判一遍，只挑出有问题的。挑出的写进「立场」和「复核意见」。
    调用失败的整批标「复核失败」，不当作没问题。"""
    model = model or llm.cfg("MODEL_STRONG")
    comments = [r for r in rows if r.get("kind", "评论") == "评论"]
    for theme in cfg["themes"]:
        stance = cfg["projects"][theme]["stance"]
        for k in range(0, len(comments), BATCH):
            batch = comments[k:k + BATCH]
            got = llm.call_json(model, RECHECK_PROMPT.format(theme=theme, stance=stance, stance_ok=cfg["projects"][theme].get("goal", "与上面相反的就是不能用的"),
                                                             numbered=_numbered(batch)))
            if got is None:
                for r in batch:
                    r["复核失败"] = True
                continue
            for x in got:
                try:
                    r = batch[int(x["编号"]) - 1]
                except (KeyError, ValueError, TypeError, IndexError):
                    continue
                r.setdefault("立场", {})[theme] = True
                r["复核意见"] = (r.get("复核意见", "") + f"[{theme}] {x.get('为什么', '')} ").strip()
    return rows


def usable(row):
    """能进库：质量够、不辱骂、不营销，并且在每个主题下立场都不冲突"""
    return ((row.get("质量分") or 0) >= PASS_SCORE and not row.get("辱骂") and not row.get("营销味")
            and not any(row.get("立场", {}).values()))
