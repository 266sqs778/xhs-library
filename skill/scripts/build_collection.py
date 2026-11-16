# -*- coding: utf-8 -*-
"""按分类把书架里的多篇书稿合成一本主题合集。

输入：classify.py 产出的 categories.json（含每篇的归档路径与类别）。
输出（书架根目录 collections/，本地私有，不进 git）：
    collections/日期_类名/
        ├─ <类名>·主题合集.pdf
        ├─ collection_source.txt   合集书稿（可回溯/可改后重排）
        ├─ merged_note_data.json   合并语料（供 verify 逐字比对）
        ├─ verify_report.txt
        └─ images/                 各卷图片（按笔记 ID 前缀重命名，避免重名）

结构：一卷 = 一篇帖子；原书各章降为 @@H2 小节；每卷前加 @@CAP 来源行；
末尾统一「本集说明与出处」+ 一个 @@CONTACT 联系页。

用法：
    python scripts/build_collection.py --category attention-energy
    python scripts/build_collection.py --all              # 每个类别各出一本
    python scripts/build_collection.py --mega             # 全类别聚合为一本「精华全集」
    python scripts/build_collection.py --category relationship --dry-run   # 只看会收哪些卷

依赖 classify.py 先跑过；排版调用 build_book.py（自带 dense 与联系页兜底）。
"""
import argparse
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_ROOT = os.path.dirname(ROOT)


def safe(s):
    return re.sub(r'[\\/:*?"<>|·\s]+', "_", (s or "")).strip("_")[:40] or "未命名"


def load_collection_index(root):
    p = os.path.join(root, "categories.json")
    if not os.path.isfile(p):
        sys.exit("[FATAL] 找不到 %s，请先运行 classify.py" % p)
    return json.load(io.open(p, encoding="utf-8"))


def pick_books(data, cat_id):
    cats = {c["id"]: c for c in data.get("categories", [])}
    if cat_id not in cats:
        sys.exit("[FATAL] 类别不存在：%s（可选：%s）" %
                 (cat_id, "、".join(cats)))
    members = [b for b in data.get("books", []) if cat_id in b.get("categories", [])]
    if not members:
        sys.exit("[FATAL] 类别「%s」下没有书；先补帖子或改 taxonomy.json 的 overrides" % cats[cat_id]["name"])
    return cats[cat_id], members


CN = "一二三四五六七八九十百千"


def cn_num(n):
    if n <= 10:
        return CN[n - 1]
    if n < 20:
        return "十" + CN[n - 11]
    return CN[n // 10 - 1] + "十" + (CN[n % 10 - 1] if n % 10 else "")


HEAD_RE = re.compile(r"^第[一二三四五六七八九十百千零〇\d]+[章节篇卷回部]\s*(.*)$")
IMG_RE = re.compile(r"^(@@IMG\s+)(images/)?([^\s|]+)(\s*\|.*)?$")


def volume_source(book, root, work_img, prefix, idx):
    """把一本书的归档书稿转成合集里的一卷。返回处理后的正文行。"""
    src = os.path.join(root, book.get("path", ""), "book_source.txt")
    if not os.path.isfile(src):
        sys.exit("[FATAL] 卷 %d 缺书稿：%s" % (idx, src))
    raw = io.open(src, encoding="utf-8").read().splitlines()
    out, imgs = [], []
    for line in raw:
        t = line.strip()
        if t == "@@CONTACT":
            continue                       # 联系页全集合并，只留末尾一个
        m = HEAD_RE.match(t)
        if m:
            head = m.group(1).strip()
            if head:
                out.append("@@H2 " + head)  # 原章降为小节
            continue
        im = IMG_RE.match(t)
        if im:
            name = im.group(3)
            base = os.path.basename(name)
            new = prefix + "_" + base
            src_img = os.path.join(root, book.get("path", ""), "images", base)
            if os.path.isfile(src_img):
                shutil.copy2(src_img, os.path.join(work_img, new))
                imgs.append(new)
                out.append("%simages/%s%s" % (im.group(1), new, im.group(4) or ""))
            else:
                out.append(t)              # 图片缺失：保留原行，验收会报图版文字缺
            continue
        out.append(line)
    return out, imgs


def merged_data(data, members, root, out_path):
    comments, descs = [], []
    for b in members:
        p = os.path.join(root, b.get("path", ""), "note_data.json")
        if not os.path.isfile(p):
            continue
        d = json.load(io.open(p, encoding="utf-8"))
        comments.extend((d.get("commentData") or {}).get("comments") or [])
        desc = (d.get("note") or {}).get("desc") or ""
        if desc:
            descs.append(desc)
    merged = {"note": {"desc": "\n".join(descs)},
              "commentData": {"comments": comments}}
    io.open(out_path, "w", encoding="utf-8", newline="").write(
        json.dumps(merged, ensure_ascii=False, indent=1) + "\n")
    return len(comments)


def build(root, cat, members, out_dir, dry=False, mega=False):
    title = "精华全集 · 分类合集" if mega else "%s · 主题合集" % cat["name"]
    date = datetime.date.today().strftime("%Y-%m-%d")
    print("=== %s（%d 卷）===" % (title, len(members)))
    for i, b in enumerate(members):
        print("  卷%s %s — %s（%s）" % (cn_num(i + 1), b["title"], b["author"], b["path"]))
    if dry:
        print("   [dry-run] 仅预览，不生成文件")
        return 0

    # 图片与书稿都直接落在 out_dir：build_book.py 会把工作目录切到书稿所在目录，
    # 引擎按 images/xxx 相对路径找图，故图片必须在同一 out_dir 下。
    img = os.path.join(out_dir, "images")
    if os.path.isdir(img):
        shutil.rmtree(img)
    os.makedirs(img, exist_ok=True)
    parts = []
    for i, b in enumerate(members):
        prefix = (b.get("noteid") or "n%d" % i)[:8]
        body, _ = volume_source(b, root, img, prefix, i + 1)
        parts.append("第%s章 卷%s · %s" % (cn_num(i + 1), cn_num(i + 1),
                                          re.sub(r"_v\d+$", "", b["title"])))
        tags = "、".join(b.get("category_names", []))
        parts.append("@@CAP 原作者：%s · 笔记：%s · 标签：%s · 归档于 %s" %
                     (b["author"], b.get("noteid", "-"), tags or "-", b.get("date", "-")))
        parts.append("")
        parts.extend(body)
        parts.append("")

    parts.append("第%s章 本集说明与出处" % cn_num(len(members) + 1))
    parts.append("@@CAP 分类体系 v%s · 生成于 %s · 仅供个人阅读存档" %
                 (DATA_VERSION[0], date))
    parts.append("本集合把同一类别下的帖子按「一卷一篇」汇编：每卷保留原帖原文、图版文字、"
                 "对话气泡与署名金句的照录，原书章标题降为本卷小节，来源与版权信息见各卷末。")
    parts.append("")
    for i, b in enumerate(members):
        nid = b.get("noteid", "")
        parts.append("@@POINT 卷%s《%s》· %s · https://www.xiaohongshu.com/explore/%s" %
                     (cn_num(i + 1), re.sub(r"_v\d+$", "", b["title"]), b["author"], nid))
    parts.append("")
    parts.append("分类规则见 assets/taxonomy/taxonomy.json，可随时增补类别与关键词，"
                 "重跑 classify.py 与 build_collection.py 即可迭代更新本集。")
    parts.append("著作权归原帖作者及评论作者所有，仅供个人阅读存档，请勿传播或商用。"
                 "扫码联系的是整理者，非原帖作者。")
    parts.append("")
    parts.append("@@CONTACT")

    src_path = os.path.join(out_dir, "collection_source.txt")
    io.open(src_path, "w", encoding="utf-8", newline="").write("\n".join(parts) + "\n")

    mdata = os.path.join(out_dir, "merged_note_data.json")
    ncmt = merged_data(DATA_RAW[0], members, root, mdata)

    build = os.path.join(HERE, "build_book.py")
    verify = os.path.join(HERE, "verify_book.py")
    pdf = os.path.join(out_dir, safe(title) + ".pdf")
    cmd = [sys.executable, build, "--source", src_path, "--title", title,
           "--author", "多维整理", "--intro", "按分类体系汇编的同主题帖子合集，仅供个人阅读存档。",
           "--preset", "xhs", "--density", "dense", "-o", pdf]
    print("   排版中…")
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode:
        sys.exit("[FATAL] 排版失败（exit %d）" % r.returncode)

    vlog = os.path.join(out_dir, "verify_report.txt")
    with io.open(vlog, "w", encoding="utf-8", newline="") as f:
        vcmd = [sys.executable, verify, "--pdf", pdf, "--source", src_path,
                "--data", mdata, "--render", os.path.join(out_dir, "样张")]
        if mega:
            vcmd.append("--collection")   # 合集一卷跨多页属正常，放宽单章跨度上限
        rv = subprocess.run(vcmd, cwd=HERE, stdout=f, stderr=subprocess.STDOUT)
    print("   验收：%s（exit %d）｜合并语料 %d 条评论" %
          ("PASS" if rv.returncode == 0 else "FAIL", rv.returncode, ncmt))
    if rv.returncode:
        print(io.open(vlog, encoding="utf-8").read()[-1600:])
    print("   [OK] %s" % pdf)
    return rv.returncode


DATA_RAW = [None]
DATA_VERSION = ["-"]


def main():
    ap = argparse.ArgumentParser(description="按分类生成主题合集")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="书架根目录")
    ap.add_argument("--category", help="类别 id（见 categories.json）")
    ap.add_argument("--all", action="store_true", help="每个类别各出一本合集")
    ap.add_argument("--mega", action="store_true", help="全类别聚合为一本精华全集")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    data = load_collection_index(root)
    DATA_RAW[0] = data
    DATA_VERSION[0] = data.get("taxonomy_version", "-")
    out_root = os.path.join(root, "collections")
    os.makedirs(out_root, exist_ok=True)
    cats = data.get("categories", [])
    if a.mega:
        # 全部帖子按类别顺序去重排列，聚合为一本
        ordered, seen = [], set()
        for c in cats:
            for b in data.get("books", []):
                if c["id"] in b.get("categories", []) and b["noteid"] not in seen:
                    seen.add(b["noteid"])
                    rec = dict(b)
                    rec["category_names"] = b.get("category_names", [])
                    ordered.append(rec)
        mega_cat = {"id": "mega", "name": "精华全集", "desc": "全类别聚合"}
        targets = [(mega_cat, ordered)]
    elif a.all:
        targets = [(c, [b for b in data.get("books", []) if c["id"] in b.get("categories", [])])
                   for c in cats]
        targets = [(c, bs) for c, bs in targets if bs]
    elif a.category:
        cat, members = pick_books(data, a.category)
        targets = [(cat, members)]
    else:
        sys.exit("[FATAL] 指定 --category <id> / --all / --mega；可用类别：%s" %
                 "、".join(c["id"] for c in cats))
    rc = 0
    for cat, members in targets:
        out_dir = os.path.join(out_root, "%s_%s" % (
            datetime.date.today().strftime("%Y-%m-%d"), safe(cat["name"])))
        if not a.dry_run:
            os.makedirs(out_dir, exist_ok=True)
        rc |= build(root, cat, members, out_dir, a.dry_run, mega=a.mega)
    sys.exit(rc)


if __name__ == "__main__":
    main()
