# social-deai · 维护人：周逸帆（飞书联系） · MIT 许可，见仓库根的 LICENSE
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import detect


def ids(text, tier=None):
    return [h["id"] for h in detect.find(text) if tier in (None, h["tier"])]


class DetectTest(unittest.TestCase):
    def test_red_lines_found(self):
        cases = {
            "AI04": "与其到处折腾，不如直接找客服问",
            "AI15": "总而言之，这事别再试了",
            "RH01": "别急着退款，先看看规则",
            "RH02": "原因很简单：规则是事先写好的",
            "RH03": "看完这条，我彻底清醒了",
            "RH05": "这个方案更适合。",
        }
        for rid, text in cases.items():
            self.assertIn(rid, ids(text, "red"), text)

    def test_soft_patterns_are_not_red(self):
        for text in ("这不是退款，而是被骗", "不是我不想办，是真没时间", "从早上到晚上都在等回复", "电话打了三次——都没用"):
            self.assertEqual(ids(text, "red"), [], text)
            self.assertTrue(ids(text, "soft"), text)

    def test_plain_human_text_is_clean(self):
        for text in ("打了三次电话，客服说退不了。", "我其实早就知道了，就是不死心", "真正让我崩溃的是半夜来的短信",
                     "看完这条视频我就去申请了"):
            self.assertEqual(ids(text, "red"), [], text)

    def test_hits_carry_matched_text_and_hint(self):
        h = detect.find("总而言之，别试了")[0]
        self.assertEqual((h["id"], h["text"]), ("AI15", "总而言之"))
        self.assertTrue(h["hint"])


class ScoreTest(unittest.TestCase):
    def test_score_orders_ai_above_human(self):
        ai = "此外，我们进行了沟通。因此结果如下。总而言之，这很重要。" * 3
        human = "打了三次电话。客服说退不了，我挂了。后来想想，算了，下个月老实还。"
        self.assertGreater(detect.score(ai)["total"], detect.score(human)["total"])

    def test_even_sentence_length_adds_score(self):
        even = "今天我去了门店办事。今天我去了门店办事。今天我去了门店办事。今天我去了门店办事。"
        uneven = "去了门店。人特别多，排了快一个小时才轮到我，前台小姐姐说要带身份证。没带。"
        self.assertGreater(detect.score(even)["句长太匀"], detect.score(uneven)["句长太匀"])

    def test_insight_words_only_count_when_dense(self):
        one = "我其实早就知道了" + "，打了电话。" * 10
        many = "其实真正的问题，说白了，本质上其实就是这样。" * 4
        self.assertLess(detect.score(one)["伪洞察词"], detect.score(many)["伪洞察词"])

    def test_verdict(self):
        self.assertEqual(detect.verdict("打了三次电话，客服说退不了。")["status"], "ok")
        v = detect.verdict("别急着退款，先看规则")
        self.assertEqual(v["status"], "red")
        self.assertIn("RH01", [h["id"] for h in v["red"]])


class CliTest(unittest.TestCase):
    def test_batch_cli_reads_lines(self):
        import subprocess, json
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "detect.py")
        out = subprocess.run([sys.executable, script, "--lines"], input="正常的一句\n总而言之别试了\n",
                             capture_output=True, text=True, check=True).stdout
        rows = json.loads(out)
        self.assertEqual([r["status"] for r in rows], ["ok", "red"])


if __name__ == "__main__":
    unittest.main()
