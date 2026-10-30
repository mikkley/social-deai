# social-deai · 维护人：周逸帆（飞书联系） · MIT 许可，见仓库根的 LICENSE
"""项目配置：一个项目目录里放 config.json，写清楚有哪些主题、各主题的立场、评论区要说哪些意思。
立场是必填的：不写，就没法判断语料里哪些评论的立场和你们要传达的相反。"""
import json, os


class ConfigError(Exception):
    pass


def load(project_dir):
    path = os.path.join(project_dir, "config.json")
    if not os.path.exists(path):
        raise ConfigError(f"项目目录里没有 config.json：{path}（照 templates/config.example.json 写一份）")
    c = json.load(open(path, encoding="utf-8"))
    projects = c.get("projects") or {}
    if not projects:
        raise ConfigError("config.json 里 projects 是空的：至少写一个主题")
    for name, p in projects.items():
        if not (p.get("stance") or "").strip():
            raise ConfigError(f"主题「{name}」没写 stance（立场）：写一句话，说明这个主题的内容里什么说法是和你们相反的，"
                              "比如「说自己按教程操作成功了、鼓励大家去试」。不写没法筛语料")
    return {**c, "themes": list(projects), "dir": project_dir}
