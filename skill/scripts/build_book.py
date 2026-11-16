# -*- coding: utf-8 -*-
"""把书稿 TXT 排成 PDF：默认小红书版式（--preset xhs）。

每本书自动带一页「联系与合作」二维码矩阵：引擎读 assets/brand/brand.json，
书稿里没写 @@CONTACT 时本脚本会补上，保证不会漏。

依赖 reportlab / pymupdf / fonttools；中文字体需要系统里有宋体、黑体、楷体、仿宋。
用法：
    python build_book.py --source book_source.txt --title "书名" --author "作者" -o out.pdf
    python build_book.py --source book_source.txt --title "书名" --author "作者" --preset modern
    python build_book.py --source book_source.txt --title "书名" --author "作者" --density normal

默认 --density dense：字号 9.0pt / 行距 13.4pt，出版说明与目录合并一页，
章间留白与卡片内边距整体收紧，二维码矩阵独占尾页；页数比 normal 少约三分之一。
"""
import argparse
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BRAND_DIR = os.path.join(ROOT, "assets", "brand")

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


def check_env(brand_dir):
    missing = []
    for mod in ("reportlab", "pymupdf"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if not ENGINE:
        sys.exit("[FATAL] 找不到排版引擎。三种解决办法：\n"
                 "        1) 使用本技能自带的 vendor/book_pdf.py；\n"
                 "        2) 安装 ebook-pdf-maker 技能（含 --preset xhs 的版本）；\n"
                 "        3) 设环境变量 XHS_BOOK_ENGINE 指向 book_pdf.py。")
    body = io.open(ENGINE, encoding="utf-8", errors="ignore").read()
    if '"xhs"' not in body:
        sys.exit("[FATAL] 引擎版本过旧（不支持 --preset xhs）：%s" % ENGINE)
    if "@@CONTACT" not in body:
        sys.exit("[FATAL] 引擎不含 @@CONTACT 二维码矩阵板块，成书会缺联系页：%s\n"
                 "        请改用本技能 vendor/book_pdf.py 或更新引擎。" % ENGINE)
    if "DENSE" not in body:
        sys.exit("[FATAL] 引擎不含 --density dense 紧凑排版模式：%s\n"
                 "        请改用本技能 vendor/book_pdf.py 或更新引擎。" % ENGINE)
    if not os.path.exists(os.path.join(brand_dir, "brand.json")):
        sys.exit("[FATAL] 品牌资源缺失：%s/brand.json\n"
                 "        assets/brand/ 需含 brand.json 与三张二维码图片。" % brand_dir)
    if missing:
        sys.exit("[FATAL] 缺少依赖：%s\n"
                 "        安装：%s -m pip install reportlab pymupdf fonttools"
                 % ("、".join(missing), sys.executable))


def ensure_contact(src_abs):
    """书稿未写 @@CONTACT 时，生成同目录临时副本并补上标记。

    放同目录是为了让 @@IMG 的相对路径仍能正确解析；排版结束后删除。
    """
    raw = io.open(src_abs, encoding="utf-8").read()
    if "@@CONTACT" in raw:
        return src_abs, None
    tmp = os.path.join(os.path.dirname(src_abs),
                       ".with_contact_" + os.path.basename(src_abs))
    io.open(tmp, "w", encoding="utf-8").write(raw.rstrip() + "\n\n@@CONTACT\n")
    print("[INFO] 书稿未写 @@CONTACT，已自动补上联系页")
    return tmp, tmp


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
    ap.add_argument("--density", default="dense", choices=["dense", "normal"],
                    help="dense=紧凑密度版（默认）：字号行距收紧、出版说明与目录合并、"
                         "二维码矩阵独占尾页；normal=还原旧版宽松版式")
    ap.add_argument("--brand-dir", default=BRAND_DIR,
                    help="品牌资源目录（含 brand.json 与二维码），默认 assets/brand")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    brand_dir = os.path.abspath(a.brand_dir)
    check_env(brand_dir)
    # 插图路径按书稿所在目录解析（引擎约定：相对运行目录）
    src_abs, tmp = ensure_contact(os.path.abspath(a.source))
    os.chdir(os.path.dirname(src_abs))
    cmd = [sys.executable, ENGINE, "--txt", src_abs, "--title", a.title,
           "--author", a.author, "--preset", a.preset, "--page", a.page,
           "--density", a.density,
           "--assets", brand_dir, "-o", os.path.abspath(a.out)]
    if a.intro:
        cmd += ["--intro", a.intro]
    if a.size:
        cmd += ["--size", str(a.size)]
    if a.lead:
        cmd += ["--lead", str(a.lead)]
    try:
        r = subprocess.run(cmd)
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
