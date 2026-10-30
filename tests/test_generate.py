# social-deai · 维护人：周逸帆（飞书联系） · MIT 许可，见仓库根的 LICENSE
import json, os, random, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import config, generate, store

MOVES = [{"名字": f"手法{i}", "怎么用": "怎么说", "性质": k, "例子": [f"c{i}a", f"c{i}b", f"c{i}c"]}
         for i, k in enumerate(["刻薄"] * 6 + ["温和"] * 6 + ["情绪"] * 4)]
CORPUS = [{"id": f"c{i}{s}", "text": f"这是手法{i}的例子{s}号评论", "状态": "生效", "语气": "平实"}
          for i in range(16) for s in "abc"]
SLOTS = [["骂代办", "sharp", 3], ["接住情绪再劝", "mild", 4], ["很短的情绪反应", "short", 2]]


def setup(corpus=None, moves=None):
    d = tempfile.mkdtemp()
    json.dump({"projects": {"主题甲": {"stance": "x"}}, "comment_slots": {"主题甲": SLOTS}},
              open(os.path.join(d, "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    store.save_corpus(d, corpus if corpus is not None else CORPUS)
    store.save_moves(d, moves if moves is not None else MOVES)
    return d, config.load(d)


class PlanTest(unittest.TestCase):
    def test_plan_has_one_row_per_slot_count(self):
        d, cfg = setup()
        plan = generate.plan_moves(cfg, "主题甲", random.Random(1))
        self.assertEqual(len(plan), 9)

    def test_sharp_slots_get_sharp_moves_and_gentle_never_borrow_sharp(self):
        d, cfg = setup()
        for seed in range(20):
            for intent, m, size, ex in generate.plan_moves(cfg, "主题甲", random.Random(seed)):
                kind = next(k for i, k, _ in SLOTS if i == intent)
                if kind == "sharp":
                    self.assertEqual(m["性质"], "刻薄")
                else:
                    self.assertNotEqual(m["性质"], "刻薄")

    def test_same_move_capped_per_post(self):
        d, cfg = setup()
        for seed in range(20):
            plan = generate.plan_moves(cfg, "主题甲", random.Random(seed))
            from collections import Counter
            self.assertLessEqual(max(Counter(m["名字"] for _, m, _, _ in plan if m["性质"] == "刻薄").values()), 2)

    def test_less_used_examples_come_first(self):
        d, cfg = setup()
        store.bump_usage(d, [f"c{i}a" for i in range(16)] * 30)
        firsts = [generate.plan_moves(cfg, "主题甲", random.Random(s))[0][3][0]["id"] for s in range(30)]
        self.assertGreater(sum(not f.endswith("a") for f in firsts), 24)

    def test_stopped_examples_are_never_shown(self):
        corpus = [{**r, "状态": "停用"} if r["id"].endswith("a") else r for r in CORPUS]
        d, cfg = setup(corpus)
        for seed in range(10):
            for _, _, _, ex in generate.plan_moves(cfg, "主题甲", random.Random(seed)):
                self.assertTrue(all(not x["id"].endswith("a") for x in ex))

    def test_too_few_moves_is_an_error(self):
        d, cfg = setup(moves=MOVES[:3])
        with self.assertRaises(generate.NotReady) as cm:
            generate.plan_moves(cfg, "主题甲", random.Random(1))
        self.assertIn("手法", str(cm.exception))


class CommentsTest(unittest.TestCase):
    WORDS = ["唉早该早点问的", "退款下来能松口气", "别信那些收钱办事的人", "拖着越拖越麻烦", "想开点吧", "客服其实愿意处理",
         "我当时也是干等", "越躲越麻烦", "先把订单号找出来", "我同事也这样过来的", "心疼你", "早点打客服电话",
         "那种教程别信", "慢慢磨总能退回来", "现在明白还不晚", "工资到账先别再下单", "别再重复充值了",
         "家里人都不知道这事", "按流程走最稳", "该处理的终归要处理", "看着真揪心", "撑住啊姐妹", "别被攻略带偏",
         "处理完踏实多了", "攒一点退一点", "谁碰上都慌", "先稳住别乱投诉", "半夜睡不着翻订单", "我也被那些人坑过", "扣费真的吓人"]

    def reply(self, n):
        return "\n".join(f"{i + 1}. {self.WORDS[i % 30]}" for i in range(n))

    def test_two_models_write_then_program_picks(self):
        d, cfg = setup()
        calls = []

        def fake(model, prompt, *a, **k):
            calls.append(model)
            return {"ok": True, "content": self.reply(30)}

        with mock.patch.object(generate.llm, "call", side_effect=fake):
            got = generate.write_comments(cfg, "主题甲", "帖子正文在这里", ["a", "b", "c"], random.Random(1), need=9)
        self.assertEqual(sorted(set(calls)), ["a", "b"])
        self.assertEqual(len(got["comments"]), 9)
        self.assertEqual(got["models"], ["a", "b"])

    def test_examples_copied_verbatim_are_dropped(self):
        d, cfg = setup()

        def fake(model, prompt, *a, **k):
            import re
            first = re.search(r"真人这样用过：「(.+?)」", prompt).group(1)
            return {"ok": True, "content": "1. " + first + "\n" + self.reply(30)}

        with mock.patch.object(generate.llm, "call", side_effect=fake):
            got = generate.write_comments(cfg, "主题甲", "帖子", ["a", "b"], random.Random(1), need=9)
        self.assertGreaterEqual(got["dropped_copies"], 1)

    def test_usage_recorded_after_write(self):
        d, cfg = setup()
        with mock.patch.object(generate.llm, "call", return_value={"ok": True, "content": self.reply(30)}):
            got = generate.write_comments(cfg, "主题甲", "帖子", ["a", "b"], random.Random(1), need=9)
        self.assertTrue(got["used_ids"])
        self.assertEqual(sum(store.load_usage(d).values()), len(got["used_ids"]))

    def test_red_line_comments_are_not_picked(self):
        d, cfg = setup()
        reply = "\n".join(["1. 总而言之这事别试了", "2. 别急着退款，先看规则"] + [f"{i}. 评论{i}号说法各不一样啊{i * 3}" for i in range(3, 30)])
        with mock.patch.object(generate.llm, "call", return_value={"ok": True, "content": reply}):
            got = generate.write_comments(cfg, "主题甲", "帖子", ["a", "b"], random.Random(1), need=9)
        self.assertFalse(any("总而言之" in c or "别急着" in c for c in got["comments"]))


class PostTest(unittest.TestCase):
    def test_pick_lowest_score_among_models_without_red_lines(self):
        d, cfg = setup()
        drafts = {"a": "此外，我们进行了沟通。因此结果如下。然而没有用。", "b": "打了三次电话。客服说退不了，我挂了，后来想想，算了，下个月老实还。真没办法。",
                  "c": "总而言之，别试了"}
        with mock.patch.object(generate.llm, "call", side_effect=lambda m, p, *a, **k: {"ok": True, "content": drafts[m]}):
            got = generate.write_post(cfg, "主题甲", "写一篇关于自动续费退款的帖子", ["a", "b", "c"])
        self.assertEqual(got["model"], "b")
        self.assertNotIn("c", [x["model"] for x in got["kept"]])

    def test_all_models_failing_is_reported(self):
        d, cfg = setup()
        with mock.patch.object(generate.llm, "call", return_value={"ok": False, "error": "502"}):
            got = generate.write_post(cfg, "主题甲", "写一篇", ["a", "b"])
        self.assertIsNone(got["text"])
        self.assertIn("502", got["errors"][0])


class DevibeTest(unittest.TestCase):
    ORIG = "此外，我们进行了沟通，因此结果如下。客服说退不了，我就没再打了，该处理的还是要处理。"

    def test_accepts_better_version(self):
        new = "我们沟通了，结果如下。客服说退不了，我就没再打了，该处理的还是要处理。"
        with mock.patch.object(generate.llm, "call", return_value={"ok": True, "content": new}):
            text, note = generate.devibe(self.ORIG, "m")
        self.assertEqual((text, note), (new, "已去味"))

    def test_rejects_when_it_adds_red_lines(self):
        bad = "总而言之，客服说退不了，我就没再打了，该处理的还是要处理。"
        with mock.patch.object(generate.llm, "call", return_value={"ok": True, "content": bad}):
            text, note = generate.devibe(self.ORIG, "m")
        self.assertEqual(text, self.ORIG)
        self.assertIn("用原文", note)

    def test_rejects_when_rewritten_too_much(self):
        other = "天气晴朗我们去公园散步吃了冰淇淋，心情特别好，一路上看到很多花。"
        with mock.patch.object(generate.llm, "call", return_value={"ok": True, "content": other}):
            text, note = generate.devibe(self.ORIG, "m")
        self.assertEqual(text, self.ORIG)
        self.assertIn("改动太大", note)

    def test_rejects_when_score_gets_worse(self):
        orig = "打了电话，客服说退不了，我就没再打了。该还的还是要还。"
        worse = "此外，打了电话，因此客服说退不了，然而我就没再打了。该还的还是要还。"
        with mock.patch.object(generate.llm, "call", return_value={"ok": True, "content": worse}):
            text, note = generate.devibe(orig, "m")
        self.assertEqual(text, orig)

    def test_call_failure_keeps_original(self):
        with mock.patch.object(generate.llm, "call", return_value={"ok": False, "error": "x"}):
            text, note = generate.devibe(self.ORIG, "m")
        self.assertEqual(text, self.ORIG)


class AutoMinSimTest(unittest.TestCase):
    def test_short_keeps_old_guard_long_relaxes(self):
        self.assertEqual(generate.auto_min_sim("字" * 80), 0.6)
        self.assertEqual(generate.auto_min_sim("字" * 100), 0.6)
        self.assertEqual(generate.auto_min_sim("字" * 200), 0.45)
        self.assertEqual(generate.auto_min_sim("字" * 600), 0.45)

    def test_linear_between_100_and_200(self):
        self.assertAlmostEqual(generate.auto_min_sim("字" * 150), 0.525)
        self.assertAlmostEqual(generate.auto_min_sim("字" * 196), 0.456)

    def test_punctuation_not_counted(self):
        self.assertEqual(generate.auto_min_sim("字，" * 100), 0.6)

    # 长稿（200 字以上）去味后相似度 0.5：旧的固定 0.6 会退回原文，按字数自适应的下限 0.45 放行
    LONG = "我上个月照着网上流传的退款攻略给平台客服打了三次电话，每次都说按规则收退不了，让我去翻用户协议。我又换了个时间段打过去，接线的人换了，答复还是一样，说系统里只能按原规则处理，让我别再重复提交。后来在社区里翻到好多人说同样的话，才知道这种事不是打电话次数多就能办成。" * 3

    def _devibe_with_sim(self, sim_value, **kw):
        with mock.patch.object(generate.llm, "call", return_value={"ok": True, "content": "改后的稿子"}), \
                mock.patch.object(generate, "sim", return_value=sim_value):
            return generate.devibe(self.LONG, "m", **kw)

    def test_long_post_rewrite_passes_with_auto_floor(self):
        self.assertEqual(generate.auto_min_sim(self.LONG), 0.45)
        text, note = self._devibe_with_sim(0.5)
        self.assertEqual((text, note), ("改后的稿子", "已去味"))

    def test_long_post_still_guarded_below_floor(self):
        text, note = self._devibe_with_sim(0.4)
        self.assertEqual(text, self.LONG)
        self.assertIn("相似度 0.400，下限 0.45", note)

    def test_explicit_min_sim_wins(self):
        text, note = self._devibe_with_sim(0.5, min_sim=0.6)
        self.assertEqual(text, self.LONG)
        self.assertIn("下限 0.6", note)


class SimilarityTest(unittest.TestCase):
    def test_batch_check_flags_near_duplicates(self):
        posts = ["打了三次电话客服说退不了我就算了", "打了三次电话客服说退不了我就算了吧", "完全不同的另一件事情说的是别的内容"]
        flagged = generate.batch_check(posts, threshold=0.8)
        self.assertEqual(flagged, [(0, 1)])


if __name__ == "__main__":
    unittest.main()
