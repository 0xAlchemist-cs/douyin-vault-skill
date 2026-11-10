"""把 videos.json + analysis/*.md + transcripts/*.txt 组装成 Obsidian vault。

用法: python build_vault.py D:/xxx -o D:/xxx/vault [--themes themes.json]
输出: MOC 首页 / 视频笔记(摘要+观点+问题+相关笔记) / 主题页 / 总问题库 / 逐字稿
亮点: 字符二元组余弦相似度自动互联(相关笔记), graph.json 配色预置。

analysis 文件模板(文件名任意 *_<id>.md, 按 id 匹配):
  ## 一句话摘要 / ## 核心观点(- 条) / ## 提炼的问题(- 条) / ## 主题(- 固定清单选)
"""
import argparse
import json
import re
import shutil
import time
from pathlib import Path

ID_RE = re.compile(r"^\d{8,25}$")


def load_answers(base):
    """answers/*_{id}.md -> {vid: {问题原文: 答案}}。格式: Q: xx / A: xx 成对。"""
    ans_dir = base / "answers"
    mapping = {}
    if not ans_dir.exists():
        return mapping
    for f in sorted(ans_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        m = re.search(r'id:\s*"(\d{8,25})"', text)
        if not m:
            continue
        pairs, cur_q = {}, None
        for line in text.splitlines():
            t = line.strip()
            if t.startswith("Q: "):
                cur_q = t[3:].strip()
            elif t.startswith("A: ") and cur_q:
                pairs[cur_q] = t[3:].strip()
                cur_q = None
        mapping[m.group(1)] = pairs
    return mapping
STOP_CHARS = set("的了和与及或在是对也就都很还更被把这那有为不没同上下中入出大多少要会能可等到们你我他她它")


def safe_title(s, maxlen=50):
    s = re.sub(r'[\\/:*?"<>|#^\[\]]', " ", s).strip()
    return s[:maxlen].rstrip() or "无标题"


def parse_analysis(md_text):
    out = {"summary": "", "points": [], "questions": [], "themes": []}
    sec = None
    for line in md_text.splitlines():
        t = line.strip()
        if t.lower().startswith("## "):
            sec = t[3:].strip()
            continue
        if not t:
            continue
        if sec and "摘要" in sec and not t.startswith(("-", "*", ">")):
            out["summary"] = (out["summary"] + " " + t).strip()
        elif sec and "观点" in sec and t.startswith(("-", "*")):
            out["points"].append(t.lstrip("-* ").strip())
        elif sec and "问题" in sec and (t.startswith(("-", "*")) or t.startswith("- [ ]")):
            out["questions"].append(re.sub(r"^- \[ \] ?", "", t.lstrip("-* ").strip()).strip())
        elif sec and "主题" in sec and t.startswith(("-", "*")):
            out["themes"].append(t.lstrip("-* ").strip())
    return out


def bigrams(text):
    freq = {}
    clean = re.sub(r"[\s，。：；、？！,.:;?!#\-—…（）()\[\]「」]", "", text)
    for i in range(len(clean) - 1):
        g = clean[i : i + 2]
        if g[0] in STOP_CHARS or g[1] in STOP_CHARS:
            continue
        freq[g] = freq.get(g, 0) + 1
    return freq


def cosine(a, b):
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def related_map(items, top_n=3):
    """按分析文本相似度算最相关邻居, 同主题加分 -> 图谱的横向连线。"""
    vecs, themes = {}, {}
    for seq, title, ana in items:
        text = ana["summary"] + " " + " ".join(ana["points"]) + " ".join(ana["questions"]) + " " + title
        vecs[seq] = bigrams(text)
        themes[seq] = set(ana["themes"])
    out = {}
    for seq in vecs:
        scores = []
        for other in vecs:
            if other == seq:
                continue
            s = cosine(vecs[seq], vecs[other])
            if themes[seq] & themes[other]:
                s += 0.05
            scores.append((s, other))
        scores.sort(reverse=True)
        out[seq] = [s2 for s, s2 in scores[:top_n] if s > 0.03]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="数据根目录(含 videos.json/analysis/transcripts)")
    ap.add_argument("-o", "--out", required=True, help="vault 输出目录")
    ap.add_argument("--themes", default=None, help="themes.json 路径")
    args = ap.parse_args()
    base = Path(args.base)
    vault = Path(args.out)
    analysis_dir = base / "analysis"
    transcripts = base / "transcripts"
    videos = json.loads((base / "videos.json").read_text(encoding="utf-8"))
    themes = json.loads(Path(args.themes).read_text(encoding="utf-8")) if args.themes and Path(args.themes).exists() else {}

    if vault.exists():
        shutil.rmtree(vault)
    notes_dir, theme_dir, script_dir, quest_dir = vault / "视频笔记", vault / "主题", vault / "逐字稿", vault / "问题清单"
    for d in (notes_dir, theme_dir, script_dir, quest_dir):
        d.mkdir(parents=True, exist_ok=True)

    prepass = []
    for i, v in enumerate(videos, 1):
        seq = f"{i:03d}"
        title0 = safe_title(v.get("desc") or str(v.get("id")))
        m = sorted(analysis_dir.glob(f"*_{v['id']}.md"))
        ana0 = parse_analysis(m[0].read_text(encoding="utf-8")) if m else {"summary": "", "points": [], "questions": [], "themes": []}
        prepass.append((seq, title0, ana0))
    related = related_map(prepass)
    name_by_seq = {s: f"{s} {t}" for s, t, _ in prepass}

    all_notes, all_questions = [], []
    for i, v in enumerate(videos, 1):
        seq = f"{i:03d}"
        vid = str(v["id"])
        if not ID_RE.fullmatch(vid):
            continue
        title = safe_title(v.get("desc") or vid)
        note_name = f"{seq} {title}"
        m = sorted(analysis_dir.glob(f"*_{vid}.md"))
        ana = parse_analysis(m[0].read_text(encoding="utf-8")) if m else {"summary": "（待分析）", "points": [], "questions": [], "themes": []}
        date = time.strftime("%Y-%m-%d", time.localtime(v.get("create") or 0))
        dur = round((v.get("dur_ms") or 0) / 1000)
        digg = v.get("digg")
        link = f"https://www.douyin.com/video/{vid}"

        tr = transcripts / f"{vid}.txt"
        tr_body = tr.read_text(encoding="utf-8") if tr.exists() else "（无逐字稿）"
        (script_dir / f"{note_name}.md").write_text(
            f"---\nid: \"{vid}\"\n---\n# {seq} 逐字稿\n\n" + "\n".join(f"> {ln}" for ln in tr_body.splitlines() or ["（空）"]) + "\n",
            encoding="utf-8",
        )

        q_lines = "\n".join(f"- [ ] {q}" for q in ana["questions"]) or "- （无）"
        p_lines = "\n".join(f"- {p}" for p in ana["points"]) or "- （无）"
        theme_links = " · ".join(f"[[{t}]]" for t in ana["themes"]) or "（未分类）"
        rel_links = " · ".join(f"[[{name_by_seq[r]}]]" for r in related.get(seq, []) if r in name_by_seq) or "（暂无）"
        (notes_dir / f"{note_name}.md").write_text(
            f"""---
id: "{vid}"
seq: {seq}
date: {date}
duration_sec: {dur}
digg: {digg}
tags:
  - 视频笔记
---

# {seq} · {title}

> [!info] 元信息
> 发布 {date} · 时长 {dur // 60}分{dur % 60:02d}秒 · 点赞 {digg} · [抖音原片]({link})

## 一句话摘要
{ana['summary'] or '（待分析）'}

## 核心观点
{p_lines}

## 提炼的问题
{q_lines}

## 主题
{theme_links}

## 逐字稿
[[{note_name} 逐字稿|查看全文]]

## 相关笔记
{rel_links}
""",
            encoding="utf-8",
        )
        all_notes.append((seq, note_name, title, date, dur, digg, ana))
        all_questions.extend(ana["questions"])

    for theme_name, info in themes.items():
        member = [n for n in all_notes if theme_name in n[6]["themes"]]
        rows = "\n".join(f"- [[{n[1]}|{n[2]}]]（{n[3]}）" for n in member) or "（无）"
        (theme_dir / f"{safe_title(theme_name, 30)}.md").write_text(
            f"---\ntags:\n  - 主题\n---\n\n# {theme_name}\n\n## 主题概述\n{info.get('desc', '')}\n\n## 关键问题\n"
            + "\n".join(f"- [ ] {q}" for q in info.get("questions", []))
            + f"\n\n## 覆盖视频（{len(member)}）\n{rows}\n",
            encoding="utf-8",
        )

    # 问题总库（有答案 -> 折叠 callout 点击展开，无答案 -> 勾选框）
    answers = load_answers(base)
    seq2vid = {f"{i:03d}": str(v["id"]) for i, v in enumerate(videos, 1)}
    grouped = {}
    for seq, note_name, title, date, dur, digg, ana in all_notes:
        for q in ana["questions"]:
            grouped.setdefault(seq, []).append(q)
    qbuf = ["---\ntags:\n  - 问题库\n---\n\n# 总问题库\n", "", "> [!tip] 用法", "> 点击问题行展开答案（答案取自对应视频逐字稿）。未配答案的为勾选框。", ""]
    answered = 0
    for seq in sorted(grouped):
        title = next(n[2] for n in all_notes if n[0] == seq)
        qbuf.append(f"\n## {seq} · {title}\n")
        ans_map = answers.get(seq2vid.get(seq, ""), {})
        for q in grouped[seq]:
            a = ans_map.get(q)
            if a:
                answered += 1
                qbuf.append(f"> [!question]- {q}\n> {a}\n")
            else:
                qbuf.append(f"- [ ] {q}")
    (quest_dir / "总问题库.md").write_text("\n".join(qbuf) + "\n", encoding="utf-8")

    total_min = sum(n[4] for n in all_notes) // 60
    moc = f"""---
tags:
  - MOC
---

# 知识库

> [!info] 档案
> 视频总数 {len(all_notes)} · 总时长 {total_min} 分钟 · 提炼问题 {len(all_questions)} 个

## 入口
- [[问题清单/总问题库|🧩 总问题库]]（{len(all_questions)} 个问题）
- [[主题/]] · [[视频笔记/]] · [[逐字稿/]]

## 主题索引
"""
    for theme_name, info in themes.items():
        moc += f"- [[主题/{safe_title(theme_name, 30)}|{theme_name}]] — {info.get('desc', '')[:60]}\n"
    moc += "\n## 全部视频\n"
    for seq, note_name, title, date, dur, digg, _ in all_notes:
        moc += f"- {date} · [[{note_name}|{title}]]（{dur // 60}分 / 赞{digg}）\n"
    (vault / "知识库.md").write_text(moc, encoding="utf-8")

    # graph.json 预置: 按路径配色 + 隐藏逐字稿杂线
    obs = vault / ".obsidian"
    obs.mkdir(exist_ok=True)

    def rgb(r, g, b):
        return r * 65536 + g * 256 + b

    (obs / "core-plugins.json").write_text(json.dumps({
        "file-explorer": True, "global-search": True, "switcher": True, "graph": True,
        "backlink": True, "canvas": True, "outgoing-link": True, "tag-pane": True,
        "properties": True, "page-preview": True, "command-palette": True,
        "bookmarks": True, "outline": True, "word-count": True, "file-recovery": True,
    }, indent=2), encoding="utf-8")
    (obs / "graph.json").write_text(json.dumps({
        "collapse-filter": True, "search": '-path:"逐字稿"', "showTags": False,
        "showAttachments": False, "hideUnresolved": True, "showOrphans": True,
        "collapse-color-groups": False,
        "colorGroups": [
            {"query": 'path:"主题"', "color": {"a": 1, "rgb": rgb(255, 136, 0)}},
            {"query": 'path:"视频笔记"', "color": {"a": 1, "rgb": rgb(86, 156, 214)}},
            {"query": 'path:"问题清单"', "color": {"a": 1, "rgb": rgb(80, 200, 120)}},
        ],
        "collapse-display": True, "showArrow": False, "textFadeMultiplier": 0,
        "nodeSizeMultiplier": 1.1, "lineSizeMultiplier": 0.7, "collapse-forces": True,
        "centerStrength": 0.5, "repelStrength": 12, "linkStrength": 1, "linkDistance": 250,
        "scale": 0.8, "close": False,
    }, indent=2), encoding="utf-8")

    print(f"vault built: {len(all_notes)} notes, {len(all_questions)} questions, {len(themes)} themes -> {vault}")


if __name__ == "__main__":
    main()
