# social-deai · 维护人：周逸帆（飞书联系） · MIT 许可，见仓库根的 LICENSE
"""本地存储：语料库、使用次数、手法清单，都是项目目录下的 JSON 文件。
多人一起审要在表格里看的话，把 corpus.json 导成 CSV 放进在线表格，改完状态再导回来（见 SKILL.md）。"""
import hashlib, json, os


def row_id(text):
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()[:12]


def _path(d, name):
    return os.path.join(d, name)


def _load(d, name, default):
    try:
        return json.load(open(_path(d, name), encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(d, name, obj):
    tmp = _path(d, name + ".tmp")
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, _path(d, name))


def load_corpus(d):
    return _load(d, "corpus.json", [])


def save_corpus(d, rows):
    _save(d, "corpus.json", rows)


def set_status(d, ids, status):
    ids = set(ids)
    rows = load_corpus(d)
    for r in rows:
        if r["id"] in ids:
            r["状态"] = status
    save_corpus(d, rows)


def drop_known(d, raw_rows):
    """已经在语料库里的不重复打标（定期补充语料时，旧的不用重新花钱）"""
    known = {r["id"] for r in load_corpus(d)}
    return [r for r in raw_rows if row_id(r["text"]) not in known]


def load_usage(d):
    return _load(d, "usage.json", {})


def bump_usage(d, ids):
    u = load_usage(d)
    for i in ids:
        u[i] = u.get(i, 0) + 1
    _save(d, "usage.json", u)


def load_moves(d):
    return _load(d, "moves.json", [])


def save_moves(d, moves):
    _save(d, "moves.json", moves)
