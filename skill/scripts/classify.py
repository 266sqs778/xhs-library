# -*- coding: utf-8 -*-
"""把书架里的书按 taxonomy.json 归类，生成分类总览与机器索引。

设计要点：
- 按笔记 ID 去重：同一帖子有多个重制版本时，取最新版本（INDEX 中行号最大）为代表。
- 归类优先级：taxonomy.overrides 人工指定 > 关键词自动打分。
- 每次运行都把结果版本与分类体系版本写进索引，可追踪、可迭代。

用法：
    python scripts/classify.py                       # 默认读书架根目录
    python scripts/classify.py --root <书架目录>
    python scripts/classify.py --explain             # 打印每篇的归类依据
    python scripts/classify.py --taxonomy <路径>

产物（都在书架根目录，本地私有，不进 git）：
    CATEGORIES.md      人读的分类总览（每类收了哪几篇、依据、迭代说明）
    categories.json    机器读的索引（build_collection.py 用）
"""
import argparse
import collections
import datetime
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_ROOT = os.path.dirname(ROOT)
DEFAULT_TAXONOMY = os.path.join(ROOT, "assets", "taxonomy", "taxonomy.json")


def load_index(root):
    """复用 shelf.py 的 INDEX 解析：返回 [{no,date,title,...}]。"""
    path = os.path.join(root, "INDEX.md")
    rows = []
    if not os.path.exists(path):
        return rows
    for line in io.open(path, encoding="utf-8").read().splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|(.*?)\|(.*?)\|(.*?)\|(.*?)\|(.*?)\|(.*?)\|(.*?)\|\s*$", line)
        if not m:
            continue
        g = [x.strip() for x in m.groups()]
        rows.append({"no": int(g[0]), "date": g[1], "title": g[2], "author": g[3],
                     "tags": g[4], "noteid": g[5], "brief": g[6], "path": g[7]})
    return rows


def latest_per_note(rows):
    """同一笔记取最新一行（no 最大）为代表，旧版本记进 past。"""
    grouped = collections.OrderedDict()
    for e in sorted(rows, key=lambda x: x["no"]):
        grouped.setdefault(e["noteid"], []).append(e)
    out = []
    for nid, versions in grouped.items():
        cur = dict(versions[-1])
        cur["versions"] = len(versions)
        cur["past"] = [v["title"] for v in versions[:-1]]
        out.append(cur)
    return out


def norm(s):
    return re.sub(r"\s+", "", (s or "")).lower()


def load_meta(root, entry):
    """尽量从归档卡片补字段（标签/简介更全）。"""
    meta = {}
    p = os.path.join(root, entry.get("path", ""), "note.meta.md")
    if os.path.isfile(p):
        for line in io.open(p, encoding="utf-8").read().splitlines():
            m = re.match(r"^-\s+\*\*(.+?)\*\*：(.+)$", line.strip())
            if m:
                meta[m.group(1).strip()] = m.group(2).strip()
    return meta


def auto_score(entry, meta, cfg, cat):
    fields = cfg.get("match", {}).get("fields", ["title", "tags", "brief", "author"])
    text = norm(" ".join([entry.get(f, "") or "" for f in fields] +
                         [meta.get("标签", ""), meta.get("一句话简介", "")]))
    hits = []
    for kw in cat.get("keywords", []):
        k = norm(kw)
        if k and k in text:
            hits.append(kw)
    return len(hits), hits


def classify(books, cfg, explain=False):
    cats = cfg.get("categories", [])
    by_id = {c["id"]: c for c in cats}
    max_labels = int(cfg.get("match", {}).get("max_labels", 2))
    min_score = int(cfg.get("match", {}).get("min_score", 1))
    overrides = cfg.get("overrides", {})
    result = []
    for b in books:
        meta = load_meta(DEFAULT_ROOT_HOLDER[0], b)
        ov = overrides.get(b["noteid"])
        if ov is not None:
            ids = [ov] if isinstance(ov, str) else list(ov)
            ids = [i for i in ids if i in by_id][:max_labels or None]
            reasons = {i: ["人工覆盖"] for i in ids}
        else:
            scored = []
            for c in cats:
                score, hits = auto_score(b, meta, cfg, c)
                if score >= min_score:
                    scored.append((score, c["id"], hits))
            scored.sort(key=lambda x: -x[0])
            ids = [i for _, i, _ in scored[:max_labels]]
            reasons = {i: h for _, i, h in scored[:max_labels]}
        rec = dict(b)
        rec["categories"] = ids
        rec["reasons"] = reasons
        rec["category_names"] = [by_id[i]["name"] for i in ids if i in by_id]
        result.append(rec)
        if explain:
            print("  %s → %s" % (b["title"], " / ".join(rec["category_names"]) or "（未归类）"))
            for i in ids:
                print("      %s: %s" % (i, "、".join(reasons.get(i, [])) or "-"))
    return result


DEFAULT_ROOT_HOLDER = [DEFAULT_ROOT]


def build_markdown(result, cfg, root):
    cats = cfg.get("categories", [])
    lines = [
        "# 小红书书架 · 分类总览",
        "",
        "> 本文件由 `scripts/classify.py` 自动生成，请勿手改。",
        "> 改分类请编辑 `assets/taxonomy/taxonomy.json`（关键词 / overrides / 类别），然后重跑 classify.py。",
        "",
        "- 分类体系版本：**%s**（%s）" % (cfg.get("version", "-"), cfg.get("updated", "-")),
        "- 归类生成时间：%s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "- 收录帖子：**%d 篇**（同一帖子的重制版本只取最新一篇为代表）" % len(result),
        "- 类别数：**%d**" % len(cats),
        "",
        "## 迭代说明",
        "",
        "分类不是一次定死的：新帖子进来、或发现某类边界不清时，改 `taxonomy.json` 的关键词 / `overrides`，",
        "重跑 `classify.py` 即可重新归类；每次改动在 taxonomy.json 的 changelog 追加一行并递增 version。",
        "收录范围以「帖子」为单位，重制版本保留在 `INDEX.md` 与各书 `note.meta.md` 里，不重复计入分类。",
        "",
        "## 分类索引",
        "",
    ]
    unc = [r for r in result if not r["categories"]]
    for c in cats:
        members = [r for r in result if c["id"] in r["categories"]]
        lines += ["### %s（%d 篇）" % (c["name"], len(members)), "", c.get("desc", ""), ""]
        if not members:
            lines += ["_（暂无收录）_", ""]
            continue
        lines += ["| 帖子 | 作者 | 归类依据 | 最新版本 | 位置 |",
                  "|---|---|---|---|---|"]
        for r in members:
            reason = "；".join("、".join(r["reasons"].get(i, [])) for i in r["categories"]
                              if i in r["reasons"])
            reason = re.sub(r"\|", "/", reason)[:60]
            lines.append("| %s | %s | %s | %s | %s |" % (
                r["title"], r["author"], reason or "-",
                ("v%d（共 %d 版）" % (r["versions"], r["versions"])) if r["versions"] > 1 else "v1",
                r["path"]))
        lines.append("")
    if unc:
        lines += ["### 未归类（%d 篇）" % len(unc), "",
                  "这些帖子没命中任何类别关键词，可给 taxonomy.json 加词或写 overrides。", ""]
        for r in unc:
            lines.append("- %s — %s（%s）" % (r["title"], r["author"], r["path"]))
        lines.append("")
    lines += ["## 完整清单（按笔记 ID）", "",
              "| 笔记 ID | 帖子 | 作者 | 类别 | 版本数 |",
              "|---|---|---|---|---|"]
    for r in result:
        lines.append("| %s | %s | %s | %s | %d |" % (
            r["noteid"], r["title"], r["author"],
            "、".join(r["category_names"]) or "-", r["versions"]))
    lines.append("")
    io.open(os.path.join(root, "CATEGORIES.md"), "w", encoding="utf-8", newline="").write("\n".join(lines))


def build_json(result, cfg, root):
    data = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "taxonomy_version": cfg.get("version", ""),
        "taxonomy_updated": cfg.get("updated", ""),
        "changelog": cfg.get("changelog", [])[-8:],
        "categories": [{"id": c["id"], "name": c["name"], "desc": c.get("desc", ""),
                        "title_extra": c.get("title_extra", "")} for c in cfg.get("categories", [])],
        "books": [{k: r[k] for k in ("noteid", "title", "author", "date", "tags", "brief",
                                     "path", "versions", "past", "categories", "category_names", "reasons")}
                  for r in result],
    }
    io.open(os.path.join(root, "categories.json"), "w", encoding="utf-8", newline="").write(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return data


def main():
    ap = argparse.ArgumentParser(description="书架按分类体系归类")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="书架根目录")
    ap.add_argument("--taxonomy", default=DEFAULT_TAXONOMY, help="分类体系配置 JSON")
    ap.add_argument("--explain", action="store_true", help="打印归类依据")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    DEFAULT_ROOT_HOLDER[0] = root
    if not os.path.isfile(a.taxonomy):
        sys.exit("[FATAL] 分类体系配置不存在：%s" % a.taxonomy)
    cfg = json.load(io.open(a.taxonomy, encoding="utf-8"))
    rows = load_index(root)
    if not rows:
        sys.exit("[FATAL] 书架索引为空：%s/INDEX.md" % root)
    books = latest_per_note(rows)
    result = classify(books, cfg, a.explain)
    build_markdown(result, cfg, root)
    data = build_json(result, cfg, root)
    print("\n[OK] 已归类 %d 篇 / %d 类（体系 v%s）" %
          (len(result), len(data["categories"]), cfg.get("version", "-")))
    for c in data["categories"]:
        n = len([r for r in result if c["id"] in r["categories"]])
        print("   %-16s %d 篇" % (c["name"], n))
    print("   → %s/CATEGORIES.md" % root)
    print("   → %s/categories.json" % root)


if __name__ == "__main__":
    main()
