# social-deai · 维护人：周逸帆（飞书联系） · MIT 许可，见仓库根的 LICENSE
"""说话手法：从真人评论里提炼几十种说话手法（复述原话反着说、给楼主封头衔、假装夸其实损……），
写评论时按「手法 × 意思 × 长短」组合，取代一条真评论对一条仿写。

为什么：一条对一条仿写，样本就那么多条，连写几百篇每条会被抄几十次，抄多了就是新的公式。
手法和话题无关，组合空间大得多。风险是手法比具体句子抽象，模型容易写回泛泛的说教腔，
所以每种手法都带真评论当例子，写的时候要抓住帖子里一个具体的东西，例子只学说法、不许借它的梗。"""
import collections, concurrent.futures, contextvars, os, random, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm

KINDS = ["刻薄", "温和", "情绪"]
PROPOSE_SAMPLE = 200
CLASSIFY_BATCH = 15
MIN_EXAMPLES = 2
# 强模型一次读 200 条评论再归纳，实测 392 秒，默认 360 秒的超时会让它每次都失败
PROPOSE_TIMEOUT = 900
WORKERS = 8
QUESTION = re.compile(r"[?？]|吗$|呢$|么$")

PROPOSE_PROMPT = """下面是社交平台上的真实网友评论。请归纳出这些评论用到的「说话手法」。

手法指的是评论怎么说话，不是说了什么。比如：
- 「复述楼主的话再反着说」：「是的 都是h6的错」
- 「给楼主封个头衔」：「哈佛H6的形象大使」
- 「假装夸，其实在损」：「这才是行长，人民的好行长」
- 「一句话情绪」：「服了 真的服」

{focus}要求：
- 归纳 {n} 种，彼此要分得开，别把一种手法拆成好几种近义的
- 每种手法写：名字（10 字以内）、怎么用（一句话，说清动作，别举例）、性质（刻薄=挖苦讽刺调侃；温和=平实地说、劝、共情、讲经历；情绪=只表达一下情绪，很短）
- 只归纳真的有好几条评论在用的手法，别编
- 这几类不要归纳：提问、反问、追问；讲道理、说教、评判对错{extra_ban}

评论：
{numbered}

只输出 JSON 数组，不要解释：
[{{"名字": "...", "怎么用": "...", "性质": "刻薄|温和|情绪"}}, ...]"""

CLASSIFY_PROMPT = """下面是一份「说话手法」清单和一组评论。逐条判断每条评论主要用的是哪种手法，只能从清单里原样抄名字，
一条都对不上就填「无」。只输出 JSON 数组，不要解释，条数和编号跟评论一致。

手法清单：
{moves}

评论：
{numbered}

[{{"编号": 1, "手法": "..."}}, ...]"""

GENTLE_FOCUS = ("这一批都是语气平和的评论。平和的说法要分得细一点：共情的、讲自己经历的、过来人提醒的、"
                "轻轻劝一句的……各是什么说法，拆开归纳。\n\n")


def propose(rows, rng, model, gentle=False, extra_ban=""):
    """抽一批样本让强模型归纳手法。第一轮全体（刻薄的优先多放，它们少）；第二轮只给平和的评论，把温和说法拆细"""
    if gentle:
        pool = [r for r in rows if r.get("语气") in ("平实", "劝导")]
        pick, focus, n = rng.sample(pool, min(len(pool), PROPOSE_SAMPLE)), GENTLE_FOCUS, "12~20"
    else:
        sharp = [r for r in rows if r.get("语气") in ("阴阳怪气", "毒舌")]
        rest = [r for r in rows if r not in sharp]
        pick = list({r["id"]: r for r in sharp + rng.sample(rest, min(len(rest), PROPOSE_SAMPLE))}.values())[:PROPOSE_SAMPLE]
        focus, n = "", "25~40"
    rng.shuffle(pick)
    numbered = "\n".join(f"{i + 1}. {r['text']}" for i, r in enumerate(pick))
    got = llm.call_json(model, PROPOSE_PROMPT.format(numbered=numbered, focus=focus, n=n,
                                                     extra_ban=("；" + extra_ban) if extra_ban else ""),
                        timeout=PROPOSE_TIMEOUT)
    return [m for m in got or [] if isinstance(m, dict) and m.get("名字") and m.get("性质") in KINDS]


def classify(rows, moves, model):
    """把每条评论归到一种手法。返回 {评论 id: 手法名}；归不上的不返回"""
    names = {m["名字"] for m in moves}
    listing = "\n".join(f"- {m['名字']}：{m['怎么用']}" for m in moves)
    batches = [rows[i:i + CLASSIFY_BATCH] for i in range(0, len(rows), CLASSIFY_BATCH)]

    def one(batch):
        numbered = "\n".join(f"{j + 1}. {r['text']}" for j, r in enumerate(batch))
        out = {}
        for x in llm.call_json(model, CLASSIFY_PROMPT.format(moves=listing, numbered=numbered)) or []:
            try:
                j = int(x.get("编号")) - 1
            except (AttributeError, TypeError, ValueError):
                continue
            if 0 <= j < len(batch) and x.get("手法") in names:
                out[batch[j]["id"]] = x["手法"]
        return out

    got = {}
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
        for part in ex.map(lambda b: contextvars.copy_context().run(one, b), batches):
            got.update(part)
    return got


def build(rows, strong=None, cheap=None, seed=7, extra_ban=""):
    """提炼 + 归类 + 去掉例子不足、问句过半的手法。rows 是已入库、状态生效的评论。返回手法清单"""
    strong, cheap = strong or llm.cfg("MODEL_STRONG"), cheap or llm.cfg("MODEL_CHEAP")
    rng = random.Random(seed)
    moves = propose(rows, rng, strong, extra_ban=extra_ban)
    names = {m["名字"] for m in moves}
    moves += [m for m in propose(rows, rng, strong, gentle=True, extra_ban=extra_ban) if m["名字"] not in names]
    text = {r["id"]: r["text"] for r in rows}
    by = collections.defaultdict(list)
    for cid, name in classify(rows, moves, cheap).items():
        by[name].append(cid)
    out = []
    for m in moves:
        ex = by[m["名字"]]
        if len(ex) < MIN_EXAMPLES or sum(bool(QUESTION.search(text[i].strip())) for i in ex) * 2 > len(ex):
            continue
        out.append({**m, "例子": ex})
    return out
