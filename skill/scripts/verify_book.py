# -*- coding: utf-8 -*-
"""成书验收：标记残留、板块落地、引文逐字比对、行首标点、版权文案、
目录书签、二维码矩阵联系页、内容密度、抽样页。

用法：
    python verify_book.py --pdf out.pdf --source book_source.txt [--data note_data.json] [--render 抽样目录]
    python verify_book.py --pdf 历史书.pdf --source 旧稿.txt --no-contact   # 复核旧档时跳过联系页

退出码非 0 表示有不通过项。
"""
import argparse
import collections
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def norm(s):
    s = re.sub(r"\[[^\]]+\]", "", s)          # [笑哭R] 等平台表情代码
    s = EMOJI_RE.sub("", s)                    # 🌿 ❤️ 😭 等表情符号
    return re.sub(r"[\s\"「」“”]", "", s)


def flat(s):
    """PDF 文本会因 CJK 换行把词拆开（如「九紫离 / 火运」），比对前去所有空白。"""
    return re.sub(r"\s+", "", s)


def strip_markup(s):
    return re.sub(r"\*\*|==", "", s)


def source_lines(src):
    """书稿里的原文照录片段（评论卡 / 引用 / 精髓 / 金句主句）。"""
    quotes, keys, pics = [], [], []
    for l in src.split("\n"):
        t = l.strip()
        if t.startswith(("@@CMT ", "@@STAR ", "@@CHAT0 ", "@@CHAT1 ", "@@CHAT2 ")):
            parts = t.split(" ", 1)[1].split("｜")
            if len(parts) > 1:
                quotes.append(parts[1].strip())
        elif t.startswith("@@QUOTE ") or t.startswith("@@GEM "):
            quotes.append(t.split(" ", 1)[1].strip())
        elif t.startswith("@@KEY "):
            keys.append(t[6:].split("｜", 1)[0].strip())
        elif t.startswith("@@PIC "):
            pics.append(t[6:].strip())
    return quotes, keys, pics


def density(src):
    """按内容身份统计字数占比：原文 / 来源 / 编者议论 / 出处说明。

    新格式（4 章 + @@CMT 评论卡）里，原文一律走标记，普通正文只会是
    末章出处说明；旧格式把原文写在普通正文里，故旧格式不启用密度校验。
    """
    cat = collections.Counter()
    for l in src.split("\n"):
        t = l.strip()
        if not t:
            continue
        if t.startswith(("@@CMT ", "@@STAR ", "@@CHAT0 ", "@@CHAT1 ", "@@CHAT2 ")):
            parts = [x.strip() for x in t.split(" ", 1)[1].split("｜", 2)]
            cat["来源"] += len(parts[0])
            cat["原文"] += len(parts[1]) if len(parts) > 1 else 0
            if len(parts) > 2:
                cat["编者议论"] += len(parts[2])
        elif t.startswith("@@KEY "):
            main, sep, by = t[6:].partition("｜")
            cat["原文"] += len(main.strip())
            if sep:
                cat["来源"] += len(by.strip())
        else:
            m = re.match(r"^@@([A-Z0-9]+)\s*(.*)$", t)
            if m:
                k, body = m.group(1), m.group(2)
                mp = {"NOTE": "编者议论", "LEAD": "编者议论", "POINT": "编者议论",
                      "CAP": "编者议论", "H2": "编者议论", "QUOTE": "原文",
                      "GEM": "原文", "PIC": "原文", "BY": "来源",
                      "IMG": "来源", "RULE": None, "PAGE": None, "CONTACT": None}
                bucket = mp.get(k, "编者议论")
                if bucket:
                    cat[bucket] += len(body)
            elif re.match(r"^第[一二三四五六七八九十]+章", t) or t.startswith("附录"):
                cat["编者议论"] += len(t)
            else:
                cat["出处说明"] += len(t)
    return cat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--data", help="采集产物 note_data.json，用于引文逐字比对")
    ap.add_argument("--render", help="抽样页输出目录")
    ap.add_argument("--brand", default=os.path.join(ROOT, "assets", "brand", "brand.json"),
                    help="品牌配置 brand.json")
    ap.add_argument("--no-contact", action="store_true",
                    help="复核历史归档时跳过二维码矩阵检查（正常成书不要用）")
    ap.add_argument("--collection", action="store_true",
                    help="合集模式：一卷为一篇帖子、天然跨多页，跳过单章页数跨度硬失败")
    a = ap.parse_args()

    doc = pymupdf.open(a.pdf)
    pages = [p.get_text() for p in doc]
    text = "\n".join(pages)
    norm_text = norm(text)
    flat_text = flat(text)
    src = io.open(a.source, encoding="utf-8").read()
    fails, warns = [], []

    print("页数 %d｜目录书签 %d" % (len(doc), len(doc.get_toc())))
    for row in doc.get_toc():
        print("   ", row[1], "→ p%d" % row[2])
    if not doc.get_toc():
        fails.append("没有目录书签")

    print("\n[1] 标记残留与占位提示")
    for kw in ("@@", "**", "==", "{{", "[[", "None", "插图缺失",
               "品牌资源缺失", "二维码缺失", "解析失败"):
        n = text.count(kw)
        print("   %-12s %d" % (kw, n))
        if n:
            fails.append("残留标记／占位提示 %s × %d" % (kw, n))

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
    for kw, need in (("核 心 观 点", 0), ("图 版 文 字 · 照 录", 0),
                     ("本册精选", 0), ("编者注｜", 0)):
        n = text.count(kw)
        print("   %-16s %d" % (kw, n))
        if need and n < need:
            fails.append("缺少板块：%s" % kw)

    print("\n[5] 引文逐字比对")
    quotes, keys, pics = source_lines(src)
    lines = src.split("\n")
    bare_quotes = 0
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
        miss = [q for q in quotes if norm(strip_markup(q)) not in all_corpus]
        kmiss = [k for k in keys if norm(strip_markup(k)) not in all_corpus]
        print("   评论引用 %d 条，未命中 %d 条" % (len(quotes), len(miss)))
        print("   金句 %d 条，未命中 %d 条（语料含正文、评论与图版文字 %d 行）"
              % (len(keys), len(kmiss), len(pics)))
        for q in miss:
            print("      MISS:", q[:46])
        for k in kmiss:
            print("      MISS:", k[:46])
        if miss or kmiss:
            fails.append("引文与采集原文不一致（见上）")
        # 只有「来自评论」的 QUOTE/GEM 才必须有 @@BY；
        # 原帖正文、话题标签、图注用引用块照录时不该被当成评论署名缺失。
        for i, l in enumerate(lines):
            if l.strip().startswith(("@@QUOTE ", "@@GEM ")):
                q = l.strip().split(" ", 1)[1]
                from_comment = norm(strip_markup(q)) in pool
                has_by = any(x.strip().startswith("@@BY ")
                             for x in lines[max(0, i - 2):i])
                if from_comment and not has_by:
                    bare_quotes += 1
    else:
        print("   （未提供 --data，跳过逐字比对；建议补上）")
        warns.append("未做引文逐字比对")
    for p_ in pics:
        ok = norm(p_.replace("／", ""))[:10] in norm_text
        print("   图版文字：%s… → PDF 内%s" % (p_.replace("／", "/")[:18], "有" if ok else "缺"))
        if not ok:
            fails.append("图版文字未落入 PDF：%s" % p_[:24])
    # 来源清晰度：金句必须自带署名；引用块必须有署名行
    no_by = [k for k in re.findall(r"^@@KEY (.+)$", src, re.M) if "｜" not in k]
    chat_lines = [l.strip() for l in lines if l.strip().startswith(("@@CHAT0 ", "@@CHAT1 ", "@@CHAT2 "))]
    no_chat_src = [l for l in chat_lines if "｜" not in l]
    print("   气泡 %d 条（缺来源 %d）｜金句缺署名 %d 条｜评论引用块缺署名 %d 条"
          % (len(chat_lines), len(no_chat_src), len(no_by), bare_quotes))
    if no_by or bare_quotes or no_chat_src:
        fails.append("有引文没带来源（金句 %d、气泡 %d、引用块 %d）"
                     % (len(no_by), len(no_chat_src), bare_quotes))

    print("\n[6] 联系页二维码矩阵")
    if a.no_contact:
        warns.append("已按 --no-contact 跳过联系页检查（仅限历史归档复核）")
    elif not os.path.exists(a.brand):
        fails.append("品牌配置缺失：%s" % a.brand)
    else:
        cfg = json.load(io.open(a.brand, encoding="utf-8"))
        title = cfg.get("title", "")
        hits = [i for i, t in enumerate(pages) if title in t or flat(title) in flat(t)]
        if not hits:
            fails.append("PDF 里找不到联系页「%s」" % title)
        else:
            i = hits[-1]
            imgs = doc[i].get_images(full=True)
            need = len(cfg.get("qr") or [])
            print("   联系页 p%d｜内嵌二维码图片 %d 张（需要 %d 张）"
                  % (i + 1, len(imgs), need))
            if len(imgs) < need:
                fails.append("二维码图片不足：%d/%d" % (len(imgs), need))
        must = cfg.get("verify", {}).get("must_contain") or []
        missing = [k for k in must if flat(k) not in flat_text]
        print("   必含文案 %d 项，缺失 %d 项" % (len(must), len(missing)))
        for k in missing:
            print("      MISS:", k)
        if missing:
            fails.append("联系页文案缺失：%s" % "、".join(missing))
        if "非原帖作者" not in flat_text:
            fails.append("联系页未区分「整理者 ≠ 原帖作者」，版权口径不清")

    print("\n[7] 内容密度（新格式书稿）")
    if not re.search(r"^@@(CMT|STAR|CHAT[012]) ", src, re.M):
        warns.append("旧格式书稿（无 @@CMT 评论卡），内容密度改用人工复核")
    else:
        cat = density(src)
        tot = sum(cat.values()) or 1
        for k in ("原文", "来源", "编者议论", "出处说明"):
            print("   %-8s %5d 字 %5.1f%%" % (k, cat[k], 100 * cat[k] / tot))
        note_chars = sum(len(m.group(1)) for m in
                         re.finditer(r"^@@NOTE (.+)$", src, re.M))
        note_ratio = note_chars / tot
        talk_ratio = cat["编者议论"] / tot
        meta_ratio = cat["出处说明"] / tot
        talk_cap = 0.18 if a.collection else 0.15   # 合集多卷各带来源行，放宽到 18%
        print("   NOTE %.1f%%（上限 8%%）｜编者议论 %.1f%%（上限 %.0f%%）｜出处说明 %.1f%%（上限 35%%）"
              % (100 * note_ratio, 100 * talk_ratio, 100 * talk_cap, 100 * meta_ratio))
        if note_ratio > 0.08:
            fails.append("编者注占比 %.1f%% 超过 8%%" % (100 * note_ratio))
        if talk_ratio > talk_cap:
            fails.append("编者议论占比 %.1f%% 超过 %.0f%%" % (100 * talk_ratio, 100 * talk_cap))
        if meta_ratio > 0.35:
            fails.append("出处说明占比 %.1f%% 超过 35%%，元信息喧宾夺主" % (100 * meta_ratio))
        if cat["原文"] / tot < 0.35:
            fails.append("原文照录占比 %.1f%% 不足 35%%" % (100 * cat["原文"] / tot))

    print("\n[8] 章节页数跨度与版心密度")
    toc = doc.get_toc()
    tail = len(pages) + 1
    brand_title = ""
    if os.path.exists(a.brand):
        brand_title = flat(json.load(io.open(a.brand, encoding="utf-8")).get("title", ""))
    for i, t in enumerate(pages):
        ft = flat(t)
        if (brand_title and brand_title in ft) or flat("内容简介") in ft:
            tail = min(tail, i + 1)
    spans = []
    for idx, row in enumerate(toc):
        start = row[2]
        stop = toc[idx + 1][2] if idx + 1 < len(toc) else tail
        end = max(start, stop - 1)
        n = end - start + 1
        spans.append(n)
        print("   %-24s p%d–p%d  %d 页" % (row[1][:24], start, end, n))
    if spans:
        print("   最大章跨度 %d 页（紧凑版目标 ≤2 页，合集模式跳过）" % max(spans))
        if max(spans) > 2 and not a.collection:
            fails.append("仍有章节跨 %d 页，超出紧凑版 ≤2 页目标" % max(spans))
    body_first = toc[0][2] if toc else 1
    body_pages = [p for i, p in enumerate(pages)
                  if body_first <= i + 1 < tail]
    han = [len(re.findall(r"[\u4e00-\u9fff]", p)) for p in body_pages]
    if han:
        print("   正文 %d 页｜平均 %.0f 汉字/页｜最高 %d｜最低 %d"
              % (len(han), sum(han) / len(han), max(han), min(han)))

    if a.render:
        os.makedirs(a.render, exist_ok=True)
        for i, t in enumerate(pages):
            if any(k in t for k in ("核 心 观 点", "图 版 文 字", "本册精选", "联 系 与 合 作")):
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
