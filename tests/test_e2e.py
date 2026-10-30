# social-deai · 维护人：周逸帆（飞书联系） · MIT 许可，见仓库根的 LICENSE
"""端到端冒烟：假模型走完 add → review → apply → moves → 写评论，确认各步骤的文件能接上"""
import csv, json, os, random, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import config, corpus, generate, llm, moves, prepare, store

WORDS = ["唉早该早点问的", "退款下来能松口气", "别信那些收钱办事的人", "拖着越拖越麻烦", "想开点吧", "客服其实愿意处理",
         "我当时也是干等", "越躲越麻烦", "先把订单号找出来", "我同事也这样过来的", "心疼你", "早点打客服电话",
         "那种教程别信", "慢慢磨总能退回来", "现在明白还不晚", "工资到账先别再下单", "别再重复充值了",
         "家里人都不知道这事", "按流程走最稳", "该处理的终归要处理", "看着真揪心", "撑住啊姐妹", "别被攻略带偏",
         "处理完踏实多了", "攒一点退一点", "谁碰上都慌", "先稳住别乱投诉", "半夜睡不着翻订单", "我也被那些人坑过", "扣费真的吓人"]


def fake_call_json(model, prompt, open_ch="[", close_ch="]", tries=2, timeout=None):
    if "逐条打标签" in prompt:
        n = prompt.count("\n") and len([l for l in prompt.split("\n") if l[:2].strip().rstrip(".").isdigit()])
        return [{"编号": i + 1, "语气": "毒舌" if i % 3 == 0 else "平实", "质量分": 4,
                 "立场冲突": "有" if "不还了" in prompt.split("\n")[i + 7:i + 8].__str__() else "无", "辱骂": "无"} for i in range(n)]
    if "归纳出这些评论用到的" in prompt:
        return [{"名字": f"手法{i}", "怎么用": "怎么说", "性质": ["刻薄", "温和", "情绪"][i % 3]} for i in range(18)]
    if "逐条判断每条评论主要用的是哪种手法" in prompt:
        names = [l[2:].split("：")[0] for l in prompt.split("\n") if l.startswith("- 手法")]
        idx = [l for l in prompt.split("\n") if l[:3].strip().rstrip(".").isdigit()]
        return [{"编号": i + 1, "手法": names[(int(l.split(".")[0]) - 1) % len(names)]} for i, l in enumerate(idx)]
    return None


class E2E(unittest.TestCase):
    def test_full_prepare_then_write(self):
        d = tempfile.mkdtemp()
        json.dump({"projects": {"主题甲": {"stance": "讲自己操作退款成功了"}},
                   "comment_slots": {"主题甲": [["骂代办", "sharp", 3], ["接住情绪", "mild", 4], ["很短的情绪反应", "short", 2]]}},
                  open(os.path.join(d, "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
        raw = os.path.join(d, "raw.csv")
        with open(raw, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["内容", "类型"])
            for i in range(180):
                w.writerow([f"{WORDS[i % 30]}第{i}号网友说的", "评论"])
            w.writerow(["加我微信带你主题甲", "评论"])
            w.writerow(["总而言之这个问题很重要啊", "评论"])
        with mock.patch.object(llm, "call_json", side_effect=fake_call_json):
            prepare.add(d, raw)
            self.assertEqual(len(store.load_corpus(d)), 180)          # 广告和红线句式在预筛就丢了
            path = prepare.review(d)
            rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
            for r in rows:
                r["状态"] = "生效"
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            prepare.apply(d, path)
            self.assertTrue(all(r["状态"] == "生效" for r in store.load_corpus(d)))
            prepare.add(d, raw)                                          # 重复补充：不重复打标
            self.assertEqual(len(store.load_corpus(d)), 180)
            prepare.build_moves(d)
        self.assertGreaterEqual(len(store.load_moves(d)), 15)
        cfg = config.load(d)
        with mock.patch.object(generate.llm, "call",
                               return_value={"ok": True, "content": "\n".join(f"{i + 1}. {WORDS[i % 30]}" for i in range(30))}):
            got = generate.write_comments(cfg, "主题甲", "一篇关于自动续费退款的帖子", ["a", "b"], random.Random(1))
        self.assertEqual(len(got["comments"]), 9)
        prepare.status(d)


if __name__ == "__main__":
    unittest.main()
