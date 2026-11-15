# -*- coding: utf-8 -*-
"""成书验收：标记残留、板块落地、引文逐字比对、行首标点、版权文案、目录书签、抽样页。

用法：
    python verify_book.py --pdf out.pdf --source book_source.txt [--data note_data.json] [--render 抽样目录]

退出码非 0 表示有不通过项。
"""
import argparse
import io
import json
import os
import re
import sys

try:
    import pymupdf
except ImportError:
    sys.exit("[FATAL] 需要 pymupdf：python -m pip install pymupdf")

BAD_LINE_START = "，。！？；：、）》」』】〕”’"
# 与书稿口径一致：略去平台表情代码与表情符号后再逐字比对
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\uFE0F\u200D]+")


def norm(s):
    s = re.sub(r"\[[^\]]+\]", "", s)          # [笑哭R] 等平台表情代码
    s = EMOJI_RE.sub("", s)                    # 🌿 ❤️ 😭 等表情符号
    return re.sub(r"[\s\"「」“”]", "", s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--data", help="采集产物 note_data.json，用于引文逐字比对")
    ap.add_argument("--render", help="抽样页输出目录")
    a = ap.parse_args()

    doc = pymupdf.open(a.pdf)
    pages = [p.get_text() for p in doc]
    text = "\n".join(pages)
    norm_text = norm(text)
    src = io.open(a.source, encoding="utf-8").read()
    fails, warns = [], []

    print("页数 %d｜目录书签 %d" % (len(doc), len(doc.get_toc())))
    for row in doc.get_toc():
        print("   ", row[1], "→ p%d" % row[2])
    if not doc.get_toc():
        fails.append("没有目录书签")

    print("\n[1] 标记残留")
    for kw in ("@@", "**", "==", "{{", "[[", "None", "插图缺失"):
        n = text.count(kw)
        print("   %-8s %d" % (kw, n))
        if n:
            fails.append("残留标记 %s × %d" % (kw, n))

    print("\n[2] 版权口径")
    if "国学经典" in text or "公版古籍" in text:
        fails.append("出现古籍版式文案，preset 用错")
    for m in re.finditer("公有领域", text):
        seg = text[max(0, m.start() - 12): m.start() + 4]
        if "不属于" not in seg:
            fails.append("出现未加否定的「公有领域」表述：…%s…" % seg.replace("\n", " "))
            break
    print("   古籍文案 %d｜公有领域保留 %d 处（应仅出现在否定句）"
          % (text.count("国学经典"), text.count("公有领域")))

    print("\n[3] 行首标点")
    bad = [l for l in text.split("\n") if l.strip() and l.strip()[0] in BAD_LINE_START]
    print("   行首中文标点 %d 处" % len(bad))
    for l in bad[:5]:
        print("      ", repr(l[:40]))
    if bad:
        fails.append("行首标点 %d 处" % len(bad))

    print("\n[4] 板块落地")
    for kw, need in (("核 心 观 点", 1), ("图 版 文 字 · 照 录", 0), ("本册精选", 0),
                     ("编者注｜", 0)):
        n = text.count(kw)
        print("   %-14s %d" % (kw, n))
        if need and n < need:
            fails.append("缺少板块：%s" % kw)

    print("\n[5] 引文逐字比对")
    quotes = [m.group(1).strip() for m in re.finditer(r"^@@(?:QUOTE|GEM) (.+)$", src, re.M)]
    keys = [m.group(1).strip() for m in re.finditer(r"^@@KEY (.+)$", src, re.M)]
    pics = [m.group(1).strip() for m in re.finditer(r"^@@PIC (.+)$", src, re.M)]
    if a.data:
        data = json.load(io.open(a.data, encoding="utf-8"))
        corpus = []
        for c in (data.get("commentData") or {}).get("comments") or []:
            corpus.append(c.get("content") or "")
            for sc in c.get("subComments") or []:
                corpus.append(sc.get("content") or "")
        pool = norm("".join(corpus))
        desc = norm((data.get("note") or {}).get("desc") or "")
        # 「图即正文」型帖子：正文、评论、图版文字都是合法引文来源
        pic_corpus = norm("".join(p_.replace("／", "") for p_ in pics))
        all_corpus = pool + desc + pic_corpus
        miss = [q for q in quotes if norm(re.sub(r"\*\*|==", "", q)) not in all_corpus]
        kmiss = [k for k in keys
                 if norm(re.sub(r"\*\*|==", "", k)) not in all_corpus]
        print("   评论引用 %d 条，未命中 %d 条" % (len(quotes), len(miss)))
        print("   金句 %d 条，未命中 %d 条（比对语料含正文、评论与图版文字 %d 行）"
              % (len(keys), len(kmiss), len(pics)))
        for q in miss:
            print("      MISS:", q[:46])
        for k in kmiss:
            print("      MISS:", k[:46])
        if miss or kmiss:
            fails.append("引文与采集原文不一致（见上）")
    else:
        print("   （未提供 --data，跳过逐字比对；建议补上）")
        warns.append("未做引文逐字比对")
    for p_ in pics:
        ok = norm(p_.replace("／", ""))[:10] in norm_text
        print("   图版文字：%s… → PDF 内%s" % (p_.replace("／", "/")[:18], "有" if ok else "缺"))
        if not ok:
            fails.append("图版文字未落入 PDF：%s" % p_[:24])

    if a.render:
        os.makedirs(a.render, exist_ok=True)
        for i, t in enumerate(pages):
            if any(k in t for k in ("核 心 观 点", "图 版 文 字", "本册精选")):
                out = os.path.join(a.render, "p%02d.png" % (i + 1))
                doc[i].get_pixmap(dpi=105).save(out)
        print("\n抽样页已输出到 %s" % a.render)

    print("\n==== 结论 ====")
    for w in warns:
        print("WARN", w)
    if fails:
        for f in fails:
            print("FAIL", f)
        sys.exit(1)
    print("PASS 全部检查通过")


if __name__ == "__main__":
    main()
