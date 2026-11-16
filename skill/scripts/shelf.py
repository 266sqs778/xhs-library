# -*- coding: utf-8 -*-
"""书架管理：归档、索引、查重。

书库根目录（默认）：
    C:/Users/无相道一/WorkBuddy/xhs-library/
    ├── INDEX.md      总目录（每本书一行）
    ├── skill/        本技能包
    └── books/        每本书一个文件夹（日期_书名_作者），全套归档

用法：
    python shelf.py init
    python shelf.py archive <成书工作目录> --title "书名" --author "原作者" \
        --note-id 6af30b9e... [--tags "宇宙,脑洞"] [--brief "一句话简介"] \
        [--pdf 成品.pdf] [--source 书稿.txt] [--data note_data.json] \
        [--verify 验收日志] [--render 抽样页目录] [--v2]
    python shelf.py list
    python shelf.py check <笔记ID 或 笔记链接>

说明：
    - 同一 noteId 再次 archive 会提示已归档位置；加 --v2 生成 _v2 新版本（旧版保留）
    - INDEX.md 与 books/ 不进 git（见仓库 .gitignore），只在本地
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

DEFAULT_ROOT = r"C:\Users\无相道一\WorkBuddy\xhs-library"
INDEX_HEADER = """# 小红书书架 · 总目录

> 每本书一行；详细卡片见各书文件夹内的 `note.meta.md`。
> 本文件与 books/ 只在本地，不随 git 公开。

| # | 成书日期 | 书名 | 原作者 | 标签 | 笔记ID | 一句话简介 | 位置 |
|---|----------|------|--------|------|--------|------------|------|
"""

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\uFE0F\u200D]+")


def safe_name(s):
    """清理 Windows 非法字符与 emoji，压缩空白，限长。"""
    s = EMOJI_RE.sub("", s or "")
    s = re.sub(r'[\\/:*?"<>|·\s]+', "_", s).strip("_")
    return (s or "未命名")[:40]


SHORT_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def norm_id(v):
    """链接或裸 ID → 笔记 ID；xhslink 短链先跟随第一跳（GET，HEAD 可能 404）。"""
    v = v or ""
    m = re.search(r"([0-9a-fA-F]{20,32})", v)
    if m:
        return m.group(1).lower()
    if "xhslink." in v:
        try:
            r = subprocess.run(
                ["curl", "-s", "-D", "-", "-o", os.devnull, "--max-time", "25",
                 "-A", SHORT_UA, v.strip()], capture_output=True, text=True)
            for line in (r.stdout or "").splitlines():
                if line.lower().startswith("location:"):
                    m = re.search(r"([0-9a-fA-F]{20,32})", line.split(":", 1)[1])
                    if m:
                        return m.group(1).lower()
        except OSError:
            pass
    return ""


class Shelf:
    def __init__(self, root):
        self.root = root
        self.index = os.path.join(root, "INDEX.md")
        self.books = os.path.join(root, "books")

    def init(self):
        os.makedirs(self.books, exist_ok=True)
        if not os.path.exists(self.index):
            io.open(self.index, "w", encoding="utf-8", newline="").write(INDEX_HEADER)
            print("[OK] 已初始化书架：%s" % self.root)
        else:
            print("[OK] 书架已存在：%s" % self.root)

    # ---------- INDEX 读写 ----------
    def entries(self):
        """返回 [{no,date,title,author,tags,noteid,brief,path}]。"""
        rows = []
        if not os.path.exists(self.index):
            return rows
        for line in io.open(self.index, encoding="utf-8").read().splitlines():
            m = re.match(r"^\|\s*(\d+)\s*\|(.*?)\|(.*?)\|(.*?)\|(.*?)\|(.*?)\|(.*?)\|(.*?)\|\s*$", line)
            if not m:
                continue
            g = [x.strip() for x in m.groups()]
            rows.append({"no": int(g[0]), "date": g[1], "title": g[2], "author": g[3],
                         "tags": g[4], "noteid": g[5], "brief": g[6], "path": g[7]})
        return rows

    def find(self, noteid):
        for e in self.entries():
            if e["noteid"] == noteid:
                return e
        return None

    def append(self, e):
        rows = self.entries()
        e["no"] = (rows[-1]["no"] + 1) if rows else 1
        line = "| %d | %s | %s | %s | %s | %s | %s | %s |\n" % (
            e["no"], e["date"], e["title"], e["author"], e["tags"],
            e["noteid"], e["brief"], e["path"])
        with io.open(self.index, "a", encoding="utf-8", newline="") as f:
            f.write(line)
        return e["no"]

    # ---------- 子命令 ----------
    def cmd_archive(self, a):
        self.init()
        noteid = norm_id(a.note_id or "")
        if not noteid:
            sys.exit("[FATAL] --note-id 需要 20-32 位十六进制笔记 ID（可传完整链接）")
        date = a.date or datetime.date.today().strftime("%Y-%m-%d")
        old = self.find(noteid)

        # 版本号
        suffix = ""
        if old and a.v2:
            # 版本号按同一笔记的全局归档次数递增，不随本次书名变化而回退到 v2
            n = len([e for e in self.entries() if e["noteid"] == noteid]) + 1
            existing = {os.path.basename(e["path"].rstrip("/\\")) for e in self.entries()}
            while True:
                cand = safe_name("%s_%s_%s_v%d" % (date, a.title, a.author, n))
                if cand not in existing:
                    break
                n += 1
            suffix = "_v%d" % n
        elif old:
            sys.exit("[已归档] 该笔记已有一本书：\n  %s（%s，%s）\n"
                     "  - 直接调旧档即可；要重制新版本请加 --v2（旧版保留）"
                     % (old["title"], old["date"], old["path"]))

        folder = safe_name("%s_%s_%s%s" % (date, a.title, a.author, suffix))
        dst = os.path.join(self.books, folder)
        if os.path.exists(dst):
            sys.exit("[FATAL] 目录已存在：%s" % dst)
        os.makedirs(os.path.join(dst, "样张"), exist_ok=True)

        work = a.workdir
        copied = []

        def cp(src, relname, required=True, rename=None):
            if not src:
                if required:
                    sys.exit("[FATAL] 缺少必归档文件参数：%s" % relname)
                return
            src = os.path.join(work, src) if not os.path.isabs(src) else src
            if src and os.path.exists(src):
                target = os.path.join(dst, rename or relname)
                shutil.copy2(src, target)
                copied.append(os.path.relpath(target, self.root))
            elif required:
                sys.exit("[FATAL] 找不到必归档文件：%s" % src)

        cp(a.pdf, "", required=True, rename=os.path.basename(a.pdf) if a.pdf.endswith(".pdf") else "书名.pdf")
        cp(a.source, "book_source.txt", required=True)
        cp(a.data, "note_data.json", required=True)
        cp("comments.md", "comments.md", required=False)
        cp(a.verify, "verify_report.txt", required=False)
        if a.render and os.path.isdir(os.path.join(work, a.render) if not os.path.isabs(a.render) else a.render):
            rd = os.path.join(work, a.render) if not os.path.isabs(a.render) else a.render
            for fn in os.listdir(rd):
                if fn.lower().endswith((".png", ".jpg")):
                    shutil.copy2(os.path.join(rd, fn), os.path.join(dst, "样张", fn))
                    copied.append(os.path.join("books", folder, "样张", fn).replace("\\", "/"))
        img_src = os.path.join(work, "images")
        if os.path.isdir(img_src):
            shutil.copytree(img_src, os.path.join(dst, "images"))
            copied.append("books/%s/images/" % folder)

        # 原帖标准地址（分享链接带临时 token，会过期，不存）
        url = "https://www.xiaohongshu.com/explore/%s" % noteid
        meta = (
            "# 归档卡片\n\n"
            "- **书名**：%s\n"
            "- **原作者**：%s\n"
            "- **笔记ID**：%s\n"
            "- **原帖地址**：%s\n"
            "- **成书日期**：%s\n"
            "- **标签**：%s\n"
            "- **一句话简介**：%s\n"
            "- **版本**：%s\n"
            "- **归档内容**：%s\n\n"
            "> 著作权归原作者及各位评论作者所有，本档仅供个人阅读存档，请勿传播或商用。\n"
            % (a.title, a.author, noteid, url, date, a.tags or "-", a.brief or "-",
               (("%s 重制（此前版本见 INDEX 旧行）" % suffix.lstrip("_"))
                if suffix else "v1"),
               "、".join(copied)))
        io.open(os.path.join(dst, "note.meta.md"), "w", encoding="utf-8", newline="").write(meta)

        no = self.append({"date": date, "title": a.title + (suffix or ""), "author": a.author,
                          "tags": a.tags or "-", "noteid": noteid,
                          "brief": a.brief or "-", "path": ("books/%s/" % folder)})
        print("[OK] 已归档为第 %d 本：%s" % (no, dst))
        for c in copied:
            print("   +", c)
        print("    INDEX.md 已更新")

    def cmd_list(self):
        rows = self.entries()
        if not rows:
            print("（书架还是空的）")
            return
        print("共 %d 本：" % len(rows))
        for e in rows:
            print("  %2d. [%s] %s — %s  (%s)" % (e["no"], e["date"], e["title"], e["author"], e["tags"]))
            print("      %s" % e["path"])

    def cmd_check(self, v):
        noteid = norm_id(v)
        if not noteid:
            sys.exit("[FATAL] 无法从输入里解析出笔记 ID：%s" % v)
        e = self.find(noteid)
        if e:
            print("[已归档] 第 %d 本：%s（%s，%s）" % (e["no"], e["title"], e["date"], e["path"]))
            print("        位置：%s" % os.path.join(self.root, e["path"]))
            print("        重制新版本：archive 加 --v2（旧版保留）")
        else:
            print("[未归档] 笔记 %s 还没做过书，可以直接走采集→成书→归档流程" % noteid)


def main():
    ap = argparse.ArgumentParser(description="小红书书架管理")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="书库根目录")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="初始化书架")

    p_a = sub.add_parser("archive", help="归档一本书")
    p_a.add_argument("workdir", help="成书工作目录（PDF/书稿/数据所在）")
    p_a.add_argument("--title", required=True)
    p_a.add_argument("--author", required=True)
    p_a.add_argument("--note-id", required=True, help="笔记 ID 或完整链接")
    p_a.add_argument("--tags", default="", help="标签，逗号分隔")
    p_a.add_argument("--brief", default="", help="一句话简介")
    p_a.add_argument("--pdf", default=None, help="成品 PDF 相对路径（默认自动找 *.pdf 最大者）")
    p_a.add_argument("--source", default="book_source.txt")
    p_a.add_argument("--data", default="note_data.json")
    p_a.add_argument("--verify", default=None, help="验收日志文件")
    p_a.add_argument("--render", default=None, help="抽样页/样张目录")
    p_a.add_argument("--date", default=None, help="成书日期 YYYY-MM-DD，默认今天")
    p_a.add_argument("--v2", action="store_true", help="同笔记重制新版本（旧版保留）")

    sub.add_parser("list", help="列出书架")
    p_c = sub.add_parser("check", help="按笔记 ID/链接查重")
    p_c.add_argument("value", help="笔记 ID 或链接")

    a = ap.parse_args()
    shelf = Shelf(a.root)
    if a.cmd == "init":
        shelf.init()
    elif a.cmd == "archive":
        if not a.pdf:
            pdfs = sorted(
                (os.path.join(a.workdir, f) for f in os.listdir(a.workdir) if f.endswith(".pdf")),
                key=os.path.getsize, reverse=True)
            if not pdfs:
                sys.exit("[FATAL] 工作目录里没有 PDF，请用 --pdf 指定")
            a.pdf = pdfs[0]
        shelf.cmd_archive(a)
    elif a.cmd == "list":
        shelf.cmd_list()
    elif a.cmd == "check":
        shelf.cmd_check(a.value)


if __name__ == "__main__":
    main()
