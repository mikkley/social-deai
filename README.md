# social-deai

批量写像真人发的社交平台帖子和评论区：去掉 AI 味，几十上百篇彼此也不像。

维护人：周逸帆（飞书联系）

## 它解决什么

让 AI 一次性写几十篇社媒内容，常见的两个毛病：

1. **一眼 AI 腔。** 句长均匀、「不是…而是」「总而言之」、段尾升华。
2. **篇篇雷同。** 同一批稿子用同一套词、同一种结构，读者翻两篇就看出来了。

这个 skill 的做法是从真人语料里学，而不是靠提示词叮嘱：

- **用真人内容当参考。** 语料库里存真实用户的帖子和评论，按「说话手法」写评论。手法是从真人评论里归纳出来的（给楼主封头衔、假装夸其实在损……），和具体句子解耦，组合空间大，不会抄成新的公式。
- **多个模型各写一版，挑最好的。** 去掉有 AI 套路的，剩下的按 AI 味分排序取第一。
- **去味改写，但改坏了退回原文。** 改完复查：出现红线句式、和原文相似度低于下限、AI 味分反而更高，一律用原文。
- **跨篇查重。** 同批稿子互相查，太像的拦下重写。

## 三层用法，按需取

| 要做什么 | 用什么 | 要准备语料吗 |
|---|---|---|
| 查一段文字有没有 AI 味 | `scripts/detect.py` | 不用 |
| 把一篇稿子改得更像真人 | `scripts/generate.py` 的 `devibe()` | 不用 |
| 批量写帖子 + 评论区 | 完整流程 | 要，见「第一次使用」 |

检测不调模型，只用标准库：

```bash
python3 scripts/detect.py 稿子.txt
echo "总而言之，别试了" | python3 scripts/detect.py
python3 scripts/detect.py --lines < 评论.txt
```

输出 `status` 为 `red` 表示命中红线句式（必须改），`ok` 表示没有。`score.total` 越低越像人，只能比大小。

## 安装

作为 Claude Code skill 使用时，把整个目录放进 `~/.claude/skills/`（或项目的 `.claude/skills/`）即可，`SKILL.md` 会被自动识别。

只调脚本也可以：

```bash
cd social-deai
python3 -m pytest tests -q        # 59 个测试，全用假模型，不联网
```

## 配置模型

OpenAI 兼容接口，环境变量配置，**密钥不要写进仓库**：

```bash
export SOCIAL_DEAI_API_BASE=https://你的网关/v1/chat/completions
export SOCIAL_DEAI_API_KEY=密钥
export SOCIAL_DEAI_MODEL_STRONG=强模型      # 归纳手法、复核立场
export SOCIAL_DEAI_MODEL_CHEAP=便宜模型     # 批量打标、归类
export SOCIAL_DEAI_MODELS=模型1,模型2,模型3   # 写稿用，至少 2 个
```

## 第一次使用（准备阶段）

完整流程需要一份语料库和一份说话手法清单。这一步要人做，因为要判断什么能当范例。详细步骤见 `SKILL.md` 的「第一次使用」，这里只列命令：

```bash
cd social-deai
python3 scripts/prepare.py 项目目录 add 原始数据.csv      # 预筛 → 打标 → 立场复核 → 入库
python3 scripts/prepare.py 项目目录 review                 # 导出 review.csv，人工把状态改成 生效/停用
python3 scripts/prepare.py 项目目录 apply 项目目录/review.csv
python3 scripts/prepare.py 项目目录 moves                  # 提炼说话手法
python3 scripts/prepare.py 项目目录 status                 # 看现状、提醒要不要补语料
```

配置写在项目目录的 `config.json`，照 `templates/config.example.json` 改。

## 定期维护语料库

**语料不是一次建好就完事的。** 不维护，稿子会越来越像、越来越旧。每 1–3 个月补一批新语料，补完重新审一遍、重新提炼手法。`status` 会在「有例子被用了 50 次以上」或「超过 90 天没补充」时提醒。

为什么必须有人看：在一个项目里，自动筛选后复查发现语料库仍有约 11% 的评论立场不对，最严重的一条被当例子用了 91 次。

## 什么时候不适合用

- 改一篇自己写的稿子、要保住作者口气：用 `ra-人话` 这类改写型工具。
- 技术文章、长文、正式发布：这套是给素人口吻的社媒内容和评论区用的。
- 手里没有真实语料：准备阶段做不了，只能用检测和去味改写。

## 已知局限

- 规则档位和百分比是在抖音、小红书若干话题的真实内容上测出来的（见 `references/真人对照.md`），换话题要重测。
- 少于两三百条生效评论时，手法可能分不够：实测 51 条只跑出 7 种（不够用），528 条跑出 36–37 种。
- 立场复核会漏（实测能抓到 73%），所以人工审不能省。
- 去味用字面相似度判断有没有动事实，对换词敏感、对语序不敏感；600 字以上的长稿可能需要换指标。
- 模型调用只用标准库，没做限流和重试。

## 目录

- `SKILL.md`：给 agent 看的完整说明
- `scripts/`：`detect.py` 检测、`patterns.py` 规则、`prepare.py` 准备阶段入口、`corpus.py` 打标、`moves.py` 提炼手法、`store.py` 本地存储、`generate.py` 生成、`llm.py` 模型调用
- `references/真人对照.md`：每条规则的档位依据
- `templates/config.example.json`：配置模板
- `tests/`：测试

## 许可

MIT，见 `LICENSE`。