# social-deai · 维护人：周逸帆（飞书联系） · MIT 许可，见仓库根的 LICENSE
import json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import config, corpus, moves, store


def project(cfg=None):
    d = tempfile.mkdtemp()
    base = {"projects": {"主题甲": {"stance": "退款退不了，别信攻略"}, "主题乙": {"stance": "拖着不处理最吃亏，要走正常流程"}},
            "comment_slots": {"主题甲": [["骂教人走捷径的代办", "sharp", 3], ["很短的情绪反应", "short", 2]]}}
    base.update(cfg or {})
    json.dump(base, open(os.path.join(d, "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return d


class ConfigTest(unittest.TestCase):
    def test_missing_stance_is_an_error(self):
        d = project({"projects": {"主题甲": {}}})
        with self.assertRaises(config.ConfigError) as cm:
            config.load(d)
        self.assertIn("stance", str(cm.exception))

    def test_themes_listed(self):
        self.assertEqual(config.load(project())["themes"], ["主题甲", "主题乙"])


class ImportTest(unittest.TestCase):
    def test_csv_import_keeps_text_and_parent(self):
        d = project()
        p = os.path.join(d, "raw.csv")
        open(p, "w", encoding="utf-8").write("内容,类型,所属帖子,点赞\n打了三次电话退不了,评论,帖子A,3\n"
                                              "我的退款经历很长很长" + "。" * 3 + ",笔记,,9\n")
        rows = corpus.read_raw(p)
        self.assertEqual([(r["text"], r["kind"]) for r in rows], [("打了三次电话退不了", "评论"),
                                                                   ("我的退款经历很长很长。。。", "笔记")])
        self.assertEqual(rows[0]["parent"], "帖子A")

    def test_dedup_and_length_filter(self):
        rows = [{"text": "同一句话说两遍", "kind": "评论"}, {"text": "同一句话说两遍", "kind": "评论"},
                {"text": "短", "kind": "评论"}, {"text": "正常的一条评论内容", "kind": "评论"}]
        kept = corpus.prefilter(rows)
        self.assertEqual([r["text"] for r in kept], ["同一句话说两遍", "正常的一条评论内容"])   # 重复的留一条，太短的丢

    def test_prefilter_drops_ads_and_ai_red_lines(self):
        rows = [{"text": "加我微信带你操作", "kind": "评论"}, {"text": "总而言之这个问题很重要", "kind": "评论"},
                {"text": "我就是被那些人坑了", "kind": "评论"}]
        self.assertEqual([r["text"] for r in corpus.prefilter(rows)], ["我就是被那些人坑了"])


class StanceTest(unittest.TestCase):
    def test_every_comment_is_judged_against_every_theme(self):
        d = project()
        asked = []

        def fake(model, prompt, *a, **k):
            for t in ("主题甲", "主题乙"):
                if f"主题：{t}" in prompt:
                    asked.append(t)
            return [{"编号": 1, "语气": "平实", "质量分": 4, "立场冲突": "无", "辱骂": "无"}]

        rows = [{"id": "a", "text": "一条评论内容在这里", "kind": "评论"}]
        with mock.patch.object(corpus.llm, "call_json", side_effect=fake):
            out = corpus.tag(rows, config.load(d))
        self.assertEqual(set(asked), {"主题甲", "主题乙"})
        self.assertIn("主题甲", out[0]["立场"])
        self.assertIn("主题乙", out[0]["立场"])

    def test_conflict_in_any_theme_blocks_use(self):
        row = {"id": "a", "text": "x", "质量分": 4, "立场": {"主题甲": False, "主题乙": True}}
        self.assertFalse(corpus.usable(row))
        row["立场"]["主题乙"] = False
        self.assertTrue(corpus.usable(row))

    def test_low_quality_not_usable(self):
        self.assertFalse(corpus.usable({"质量分": 2, "立场": {}}))


class RecheckTest(unittest.TestCase):
    def test_strong_model_recheck_stops_what_cheap_model_missed(self):
        d = project()
        rows = [{"id": "a", "text": "我上个月的会员费打电话要回来800", "状态": "待审核", "立场": {"主题甲": False, "主题乙": False}, "质量分": 4},
                {"id": "b", "text": "打了三次电话没用", "状态": "待审核", "立场": {"主题甲": False, "主题乙": False}, "质量分": 4}]
        reply = lambda *a, **k: [{"编号": 1, "为什么": "称退了800"}]
        with mock.patch.object(corpus.llm, "call_json", side_effect=reply):
            corpus.recheck(rows, config.load(d), model="strong")
        self.assertTrue(rows[0]["立场"]["主题甲"])
        self.assertFalse(rows[1]["立场"]["主题甲"])
        self.assertIn("称退了800", rows[0]["复核意见"])

    def test_recheck_runs_for_every_theme_and_every_row(self):
        d = project()
        rows = [{"id": str(i), "text": f"第{i}条评论的内容在这里", "状态": "待审核", "立场": {}} for i in range(25)]
        seen = []
        def fake(model, prompt, *a, **k):
            seen.append(("主题甲" if "主题：主题甲" in prompt else "主题乙"))
            return []
        with mock.patch.object(corpus.llm, "call_json", side_effect=fake):
            corpus.recheck(rows, config.load(d), model="strong")
        self.assertEqual(set(seen), {"主题甲", "主题乙"})
        self.assertEqual(len(seen), 2 * 3)   # 25 条每批 10 条 = 3 批，两个主题

    def test_failed_recheck_is_flagged_not_trusted(self):
        d = project()
        rows = [{"id": "a", "text": "一条评论内容在这里", "状态": "待审核", "立场": {"主题甲": False}}]
        with mock.patch.object(corpus.llm, "call_json", return_value=None):
            corpus.recheck(rows, config.load(d), model="strong")
        self.assertEqual(rows[0]["状态"], "待审核")
        self.assertTrue(rows[0].get("复核失败"))


class MovesTest(unittest.TestCase):
    def rows(self, n=40):
        return [{"id": f"c{i}", "text": f"评论内容第{i}条不一样", "语气": "毒舌" if i % 3 == 0 else "平实"} for i in range(n)]

    def test_build_drops_thin_and_question_moves(self):
        rows = self.rows()
        proposed = [{"名字": "封头衔", "怎么用": "起外号", "性质": "刻薄"},
                    {"名字": "只一条", "怎么用": "x", "性质": "温和"},
                    {"名字": "全是问句", "怎么用": "追问", "性质": "温和"}]
        assign = {f"c{i}": "封头衔" for i in range(0, 6)}
        assign["c7"] = "只一条"
        for i in range(10, 14):
            rows[i]["text"] = f"这是真的吗{i}？"
            assign[f"c{i}"] = "全是问句"
        with mock.patch.object(moves, "propose", return_value=proposed), \
                mock.patch.object(moves, "classify", return_value=assign):
            out = moves.build(rows)
        self.assertEqual([m["名字"] for m in out], ["封头衔"])
        self.assertEqual(len(out[0]["例子"]), 6)

    def test_bad_model_output_is_skipped(self):
        with mock.patch.object(moves.llm, "call_json", return_value=[{"名字": "好", "怎么用": "x", "性质": "刻薄"},
                                                                      {"名字": "坏", "怎么用": "x", "性质": "乱写"}, "字符串"]):
            got = moves.propose(self.rows(), moves.random.Random(1), "claude")
        self.assertEqual([m["名字"] for m in got], ["好"])

    def test_propose_uses_long_timeout(self):
        seen = {}
        def fake(model, prompt, open_ch="[", close_ch="]", tries=2, timeout=None):
            seen["timeout"] = timeout
            return []
        with mock.patch.object(moves.llm, "call_json", side_effect=fake):
            moves.propose(self.rows(), moves.random.Random(1), "strong")
        self.assertGreaterEqual(seen["timeout"], 900)   # 强模型归纳 200 条实测 392 秒

    def test_classify_runs_batches_concurrently(self):
        import threading, time
        rows = self.rows(60)   # 4 批
        live, peak, lock = [0], [0], threading.Lock()
        def fake(model, prompt, *a, **k):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.05)
            with lock:
                live[0] -= 1
            return []
        with mock.patch.object(moves.llm, "call_json", side_effect=fake):
            moves.classify(rows, [{"名字": "封头衔", "怎么用": "x", "性质": "刻薄"}], "cheap")
        self.assertGreater(peak[0], 1)

    def test_classify_only_accepts_listed_names(self):
        rows = self.rows(3)
        reply = [{"编号": 1, "手法": "封头衔"}, {"编号": 2, "手法": "瞎编的名字"}, {"编号": 3, "手法": "无"}]
        with mock.patch.object(moves.llm, "call_json", return_value=reply):
            got = moves.classify(rows, [{"名字": "封头衔", "怎么用": "x", "性质": "刻薄"}], "cheap")
        self.assertEqual(got, {"c0": "封头衔"})


class StoreTest(unittest.TestCase):
    def test_corpus_roundtrip_and_status_change(self):
        d = project()
        store.save_corpus(d, [{"id": "a", "text": "一条", "状态": "生效"}, {"id": "b", "text": "二条", "状态": "生效"}])
        store.set_status(d, ["b"], "停用")
        got = {r["id"]: r["状态"] for r in store.load_corpus(d)}
        self.assertEqual(got, {"a": "生效", "b": "停用"})

    def test_usage_counts_persist(self):
        d = project()
        store.bump_usage(d, ["a", "a", "b"])
        store.bump_usage(d, ["a"])
        self.assertEqual(store.load_usage(d), {"a": 3, "b": 1})

    def test_new_raw_rows_are_not_retagged(self):
        d = project()
        store.save_corpus(d, [{"id": store.row_id("已有的评论内容"), "text": "已有的评论内容", "状态": "生效"}])
        fresh = store.drop_known(d, [{"text": "已有的评论内容"}, {"text": "新来的一条评论"}])
        self.assertEqual([r["text"] for r in fresh], ["新来的一条评论"])


if __name__ == "__main__":
    unittest.main()
