# -*- coding: utf-8 -*-
"""把书稿 TXT 排成 PDF：默认小红书版式（--preset xhs）。

依赖 reportlab / pymupdf / fonttools；中文字体需要系统里有宋体、黑体、楷体、仿宋。
用法：
    python build_book.py --source book_source.txt --title "书名" --author "作者" -o out.pdf
    python build_book.py --source book_source.txt --title "书名" --author "作者" --preset modern
"""
import argparse
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 排版引擎按顺序查找：环境变量 → 本仓库 vendor → 已安装的 ebook-pdf-maker 技能
CANDIDATES = [
    os.environ.get("XHS_BOOK_ENGINE"),
    os.path.join(ROOT, "vendor", "book_pdf.py"),
    os.path.expanduser("~/.workbuddy/skills/ebook-pdf-maker/scripts/book_pdf.py"),
]


def find_engine():
    for c in CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


ENGINE = find_engine()


def check_env():
    missing = []
    for mod in ("reportlab", "pymupdf"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if not ENGINE:
        sys.exit("[FATAL] 找不到排版引擎。三种解决办法：\n"
                 "        1) 安装 ebook-pdf-maker 技能（含 --preset xhs 的版本）；\n"
                 "        2) 把 book_pdf.py 放到本仓库 vendor/；\n"
                 "        3) 设环境变量 XHS_BOOK_ENGINE 指向 book_pdf.py。")
    body = io.open(ENGINE, encoding="utf-8", errors="ignore").read()
    if '"xhs"' not in body:
        sys.exit("[FATAL] 引擎版本过旧（不支持 --preset xhs）：%s\n"
                 "        请更新 ebook-pdf-maker 到含小红书版式的版本。" % ENGINE)
    if missing:
        sys.exit("[FATAL] 缺少依赖：%s\n"
                 "        安装：%s -m pip install reportlab pymupdf fonttools"
                 % ("、".join(missing), sys.executable))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="书稿 TXT（含 @@ 标记）")
    ap.add_argument("--title", required=True)
    ap.add_argument("--author", default="佚名")
    ap.add_argument("--intro", default="", help="封底/出版说明用的内容简介")
    ap.add_argument("--preset", default="xhs", choices=["xhs", "modern", "classic"])
    ap.add_argument("--size", type=float, default=None, help="正文字号，留空随版式")
    ap.add_argument("--lead", type=float, default=None, help="行距，留空随版式")
    ap.add_argument("--page", default="A5", choices=["A5", "A4"])
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    check_env()
    # 插图路径按书稿所在目录解析（引擎约定：相对运行目录）
    src_abs = os.path.abspath(a.source)
    os.chdir(os.path.dirname(src_abs))
    cmd = [sys.executable, ENGINE, "--txt", src_abs, "--title", a.title,
           "--author", a.author, "--preset", a.preset, "--page", a.page,
           "-o", os.path.abspath(a.out)]
    if a.intro:
        cmd += ["--intro", a.intro]
    if a.size:
        cmd += ["--size", str(a.size)]
    if a.lead:
        cmd += ["--lead", str(a.lead)]
    r = subprocess.run(cmd)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
