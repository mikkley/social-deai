# social-deai · 维护人：周逸帆（飞书联系） · MIT 许可，见仓库根的 LICENSE
"""准备阶段入口（第一次使用 + 以后定期补充语料）。项目目录里要有 config.json。
  python3 prepare.py 项目目录 add 原始数据.csv|xlsx   # 预筛 → 打标 → 入库（已有的不重复打标）
  python3 prepare.py 项目目录 review                  # 导出 review.csv：看哪些待审核，改「状态」列
  python3 prepare.py 项目目录 apply review.csv        # 把 review.csv 里改过的状态写回
  python3 prepare.py 项目目录 moves                   # 用生效的评论提炼说话手法
  python3 prepare.py 项目目录 status                  # 语料库现状、手法数、多久没补充了
"""
import csv, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, corpus, moves, store

STALE_DAYS = 90


def add(d, path):
    cfg = config.load(d)
    raw = corpus.read_raw(path)
    pre = corpus.prefilter(raw, cfg.get("ad_words"))
    fresh = store.drop_known(d, pre)
    print(f"原始 {len(raw)} 条 → 规则预筛后 {len(pre)} 条 → 其中新的 {len(fresh)} 条（要调模型打标）")
    tagged = corpus.recheck(corpus.tag(fresh, cfg), cfg)
    for r in tagged:
        r["入库时间"] = int(time.time())
        r["状态"] = "待审核" if corpus.usable(r) and not r.get("复核失败") else "停用"
        if r["状态"] == "停用" and r.get("复核失败"):
            r["停用原因"] = "立场复核调用失败，重新 add 一次会重试（先从 corpus.json 删掉这条）"
        elif r["状态"] == "停用":
            r["停用原因"] = ("立场冲突：" + "、".join(t for t, c in r.get("立场", {}).items() if c)) if any(r.get("立场", {}).values()) \
                else "质量分低或营销/辱骂"
    store.save_corpus(d, store.load_corpus(d) + tagged)
    ok = sum(r["状态"] == "待审核" for r in tagged)
    print(f"打标完：过关 {ok} 条（状态=待审核），没过 {len(tagged) - ok} 条（状态=停用，原因在「停用原因」）")
    print("下一步：python3 prepare.py", d, "review  → 看一遍过关的，把不要的状态改成停用，再 apply")


def review(d):
    rows = store.load_corpus(d)
    path = os.path.join(d, "review.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "状态", "类型", "语气", "质量分", "冲突的主题", "内容", "停用原因"])
        for r in sorted(rows, key=lambda r: (r["状态"] != "待审核", r["状态"])):
            w.writerow([r["id"], r["状态"], r.get("kind", ""), r.get("语气", ""), r.get("质量分", ""),
                        "、".join(t for t, c in r.get("立场", {}).items() if c), r["text"], r.get("停用原因", "")])
    print(f"导出 {len(rows)} 条 → {path}。状态可以改成：生效 / 停用 / 待审核。改完用 apply 写回")
    return path


def apply(d, path):
    want = {r["id"]: r["状态"] for r in csv.DictReader(open(path, encoding="utf-8-sig")) if r.get("状态")}
    bad = {v for v in want.values() if v not in ("生效", "停用", "待审核")}
    if bad:
        sys.exit(f"状态只能是 生效/停用/待审核，发现：{bad}")
    rows = store.load_corpus(d)
    n = 0
    for r in rows:
        if r["id"] in want and r["状态"] != want[r["id"]]:
            r["状态"] = want[r["id"]]
            n += 1
    store.save_corpus(d, rows)
    print(f"改了 {n} 条的状态")


def build_moves(d):
    cfg = config.load(d)
    rows = [r for r in store.load_corpus(d) if r["状态"] == "生效" and r.get("kind", "评论") == "评论"]
    if len(rows) < 100:
        print(f"提醒：生效的评论只有 {len(rows)} 条，少于 100 条手法可能分不够（我们的项目是 528 条跑出 36 种）")
    out = moves.build(rows, extra_ban=cfg.get("moves_ban", ""))
    store.save_moves(d, out)
    print(f"提炼出 {len(out)} 种手法 → {os.path.join(d, 'moves.json')}。写评论至少需要 {15} 种。"
          "打开 moves.json 看一遍，不要的手法加 \"停用\": true")


def status(d):
    rows = store.load_corpus(d)
    by = {}
    for r in rows:
        by[(r.get("kind", "评论"), r["状态"])] = by.get((r.get("kind", "评论"), r["状态"]), 0) + 1
    print("语料库：", {f"{k}·{s}": n for (k, s), n in sorted(by.items())})
    print("手法：", len(store.load_moves(d)), "种（可用的要至少 15 种）")
    latest = max((r.get("入库时间", 0) for r in rows), default=0)
    if latest:
        days = (time.time() - latest) / 86400
        print(f"最近一次补充语料：{days:.0f} 天前" + (f"。超过 {STALE_DAYS} 天了，建议补充一批新语料" if days > STALE_DAYS else ""))
    usage = store.load_usage(d)
    hot = [r for r in rows if r["状态"] == "生效" and usage.get(r["id"], 0) >= 50]
    if hot:
        print(f"有 {len(hot)} 条例子被用了 50 次以上，写出来的稿子会越来越像，建议补充新语料")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    d, cmd, *rest = sys.argv[1:]
    {"add": lambda: add(d, rest[0]), "review": lambda: review(d), "apply": lambda: apply(d, rest[0]),
     "moves": lambda: build_moves(d), "status": lambda: status(d)}[cmd]()
