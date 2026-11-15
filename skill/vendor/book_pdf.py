# -*- coding: utf-8 -*-
"""
通用电子书 PDF 排版引擎（由 54 本古籍重排实战提炼）。

把一份纯文本（txt，可由 extract_text.py 从 docx/epub/html 提取）排成
「封面 → 出版说明 → 目录(书签) → 正文 → 封底」的完整 PDF 书。

用法:
  python book_pdf.py --txt 书.txt --title 书名 --author 作者 --intro 简介 \
                     [--poetry 1] [--out out.pdf] [--assets 素材目录] [--page A5]

关键设计（踩坑沉淀，勿随意改动）:
  1. 段落重建：扫描/OCR 源文常被按固定列宽硬截断（每行 12-22 字、行尾无标点）。
     自动检测（行尾标点比例 <0.35）后进入合并模式，断段信号 = 章节头 / 行首缩进≥2字 /
     句末标点 / 500 字硬上限；**空行不作为断段信号**（扫描本常在每列后插空行）。
  2. 居中 vs 两端对齐：不要整本书一刀切居中。诗集内按段落长度判定——
     ≤40 字的诗句居中，长段（散文/序跋/合并连排）两端对齐，否则散文尾行居中很难看。
  3. 生僻字：非 BMP 字符按字形选字体（扩展B 用 simsunb，扩展G 用 SimsunExtG）并包
     <font> 标签混排；私用区(PUA)字符任何字体都无字形，直接剔除。
  4. reportlab 会把非 BMP 字符的 ToUnicode CMap 写成奇数长度十六进制 → 复制/搜索乱码。
     生成后务必跑一次 fix_tounicode.py 修正文本层（视觉不受影响，但文本层必须修）。
"""
import os, re, sys, math, json, argparse, unicodedata, warnings
warnings.filterwarnings("ignore")

from reportlab.lib.pagesizes import A5, A4
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                PageBreak, Spacer, NextPageTemplate, Table,
                                TableStyle, Image, Flowable, KeepTogether)
from reportlab.platypus.tableofcontents import TableOfContents

# 中文标点禁则：reportlab 默认只收半角与日文标点，中文全角「，。；：！？」等
# 会被排到行首。补齐后这些标点会悬挂在上一行行末，避免行首标点。
try:
    import reportlab.lib.textsplit as _rl_textsplit
    import reportlab.platypus.paragraph as _rl_paragraph
    _CJK_CANNOT_START = "，。！？；：、）》」』】〕”’…％·"
    _rl_textsplit.ALL_CANNOT_START += _CJK_CANNOT_START
    _rl_paragraph.ALL_CANNOT_START += _CJK_CANNOT_START
except Exception:
    pass

try:
    import zhconv
    def conv(t):
        return zhconv.convert(t, "zh-cn")
except ImportError:                       # zhconv 非必需，缺失则原样输出
    def conv(t):
        return t


# ---------------- 字体（跨平台自动探测，可用 --font-dir / BOOK_FONT_DIR 覆盖）----------------
def _argv_font_dir():
    for i, s in enumerate(sys.argv):
        if s == "--font-dir" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if s.startswith("--font-dir="):
            return s.split("=", 1)[1]
    return os.environ.get("BOOK_FONT_DIR")


_fd = _argv_font_dir()
if _fd:
    os.environ["BOOK_FONT_DIR"] = _fd

if _fd:
    FONT_DIRS = [_fd]
elif os.name == "nt":
    FONT_DIRS = [os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")]
elif sys.platform == "darwin":
    FONT_DIRS = ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental",
                 "/Library/Fonts"]
else:
    FONT_DIRS = ["/usr/share/fonts", "/usr/share/fonts/truetype",
                 os.path.expanduser("~/.fonts")]

CAND = {
    "Song": ["simsun.ttc", "simsun.ttf"],
    "Hei": ["simhei.ttf", "SimHei.ttf"],
    "Kai": ["simkai.ttf", "SimKai.ttf"],
    "Fang": ["simfang.ttf", "SimFang.ttf"],
    "SongB": ["simsunb.ttf"],        # CJK 扩展B（生僻字兜底，可选）
    "SongExtG": ["SimsunExtG.ttf"],  # CJK 扩展G（极僻字，可选）
}
FONT_PATH = {}


def _reg(name, names):
    for fn in names:
        for d in FONT_DIRS:
            p = os.path.join(d, fn)
            if not os.path.exists(p):
                continue
            try:
                pdfmetrics.registerFont(TTFont(name, p))
                FONT_PATH[name] = p
                return True
            except Exception:
                continue
    return False


_reg("Song", CAND["Song"])
_reg("Hei", CAND["Hei"])
_reg("Kai", CAND["Kai"])
_reg("Fang", CAND["Fang"])
HAS_B = _reg("SongB", CAND["SongB"])        # CJK 扩展B
HAS_G = _reg("SongExtG", CAND["SongExtG"])  # CJK 扩展G
if HAS_B:
    addMapping("SongB", 0, 0, "SongB")
if HAS_G:
    addMapping("SongExtG", 0, 0, "SongExtG")


def _cmap_cover(path):
    """取字体非 BMP 覆盖码位（必须用 format=12 子表，getBestCmap 只返 BMP 不可信）"""
    try:
        from fontTools.ttLib import TTFont as _FT
        tt = _FT(path, lazy=True)
        best = None
        for t in tt["cmap"].tables:
            if getattr(t, "format", None) == 12:
                if best is None or len(t.cmap) > len(best.cmap):
                    best = t
        return set(best.cmap.keys()) if best else set()
    except Exception:
        return set()


COV_B = _cmap_cover(FONT_PATH["SongB"]) if HAS_B else set()
COV_G = _cmap_cover(FONT_PATH["SongExtG"]) if HAS_G else set()

PAPER, INK, SEAL, GRAY, LGRAY = (HexColor("#f0e7d2"), HexColor("#3a3228"),
                                 HexColor("#9e2b25"), HexColor("#5a5048"),
                                 HexColor("#888888"))

# 配色方案。classic / modern 共用宣纸底色；xhs 为小红书风格：白底、珊瑚红、浅粉卡片。
PALETTES = {
    "classic": dict(paper="#f0e7d2", ink="#3a3228", seal="#9e2b25", gray="#5a5048",
                    lgray="#888888", lead_bg="#f7efdd", gem_bg="#fbf1e9",
                    quote_bg="#f2f3ef", pic_bg="#fbfaf5", hl="#f7e3a1",
                    head_rule="#dddddd", cmt_bg="#f7f2e8"),
    "xhs": dict(paper="#ffffff", ink="#2b2b2b", seal="#ff2e4d", gray="#8a8a8a",
                lgray="#d8d8d8", lead_bg="#fff2f3", gem_bg="#fff8f9",
                quote_bg="#f6f7f8", pic_bg="#fffdf7", hl="#ffe9a0",
                head_rule="#ececec", cmt_bg="#fff5f6"),
}
ACCENT_HEX = "#9e2b25"
HL_HEX = "#f7e3a1"
LEAD_BG = HexColor("#f7efdd")
GEM_BG = HexColor("#fbf1e9")
QUOTE_BG = HexColor("#f2f3ef")
PIC_BG = HexColor("#fbfaf5")
CMT_BG = HexColor("#f7f2e8")
HEAD_RULE = HexColor("#dddddd")


def apply_palette(name="classic"):
    """切换全局配色（供 make_styles / 绘制函数在运行时读取）。"""
    global PAPER, INK, SEAL, GRAY, LGRAY, ACCENT_HEX, HL_HEX
    global LEAD_BG, GEM_BG, QUOTE_BG, PIC_BG, CMT_BG, HEAD_RULE
    pal = PALETTES.get(name) or PALETTES["classic"]
    PAPER = HexColor(pal["paper"])
    INK = HexColor(pal["ink"])
    SEAL = HexColor(pal["seal"])
    GRAY = HexColor(pal["gray"])
    LGRAY = HexColor(pal["lgray"])
    LEAD_BG = HexColor(pal["lead_bg"])
    GEM_BG = HexColor(pal["gem_bg"])
    QUOTE_BG = HexColor(pal["quote_bg"])
    PIC_BG = HexColor(pal.get("pic_bg") or pal["quote_bg"])
    CMT_BG = HexColor(pal.get("cmt_bg") or pal["lead_bg"])
    HEAD_RULE = HexColor(pal["head_rule"])
    ACCENT_HEX = pal["seal"]
    HL_HEX = pal["hl"]
STATE = {"book": "", "chap": ""}

# 品牌素材（二维码/头像）：默认 skill 自带 templates/，可用 --assets 或 BOOK_ASSET_DIR 覆盖
# 品牌名：--brand 或环境变量 BOOK_BRAND；为空=通用版（无藏书印/品牌段/联系图）
_HERE = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = (os.environ.get("BOOK_ASSET_DIR")
             or os.path.join(os.path.dirname(_HERE), "templates"))


def _draw_seal(c, W, H, m, brand=""):
    """右下角朱红藏书印（2×2 田字排布）；brand 为空时不绘制。"""
    if not brand:
        return
    sw = sh = 20 * mm
    x0 = W - m - 6 - sw; y0 = m + 6
    c.setFillColor(SEAL); c.rect(x0, y0, sw, sh, fill=1, stroke=0)
    c.setFillColor(PAPER); c.setFont("Kai", 14)
    cxR, cxL = x0 + sw * 0.75, x0 + sw * 0.25
    cyT, cyB = y0 + sh * 0.75, y0 + sh * 0.25
    for ch, (x, y) in zip(brand[:4], [(cxR, cyT), (cxR, cyB), (cxL, cyT), (cxL, cyB)]):
        c.drawCentredString(x, y - 6, ch)


# ---------------- 文本清洗 ----------------
def clean_text(raw):
    raw = re.sub(r"<[^>]+>", "", raw)
    for a, b in [("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"),
                 ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'")]:
        raw = raw.replace(a, b)
    raw = raw.replace("\x0c", "").replace("\xa0", " ")
    raw = re.sub(r"\{\{.*?\}\}", "", raw)
    raw = re.sub(r"\{\{|\}\}", "", raw)
    # 维基分类标记：整段删除（先于通用链接剥除，避免残留 `Category:xxx`）
    raw = re.sub(r"\[\[(?:Category|分类):[^\]]*\]\]", "", raw, flags=re.I)
    raw = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", raw)
    raw = raw.replace("'''", "").replace("''", "")
    raw = re.sub(r"<noinclude>.*?</noinclude>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"<includeonly>.*?</includeonly>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"</?noinclude>|</?includeonly>", "", raw, flags=re.I)
    # 整行的维基分类标记（无方括号的纯文本行）
    raw = "\n".join(l for l in raw.split("\n")
                    if not re.match(r"^\s*(Category|分类)\s*[:：]", l, re.I))
    raw = raw.replace("︻", "【").replace("︼", "】")
    return raw


def clean_chapter_title(t):
    if not t:
        return ""
    t = t.strip()
    if t.strip("【】︻︼[]（）()").strip() in ("目录", "目 录", "目录页", ""):
        return ""
    t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = t.replace("'''", "").replace("''", "")
    t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------- 生僻字混排 ----------------
_RARE_RE = re.compile(r"([\U00020000-\U0010FFFF]+)")
_PUA_RE = re.compile(r"[\uE000-\uF8FF\U000F0000-\U000FFFFD\U00100000-\U0010FFFD]")
_SUB_TAB = str.maketrans({"・": "·", "‧": "·"})


def _pick_font(cp):
    if cp in COV_B:
        return "SongB"
    if cp in COV_G:
        return "SongExtG"
    return "SongExtG" if HAS_G else ("SongB" if HAS_B else "Song")


_INLINE_RE = re.compile(r"(\*\*.+?\*\*|==.+?==)")


def _rich_plain(t):
    """纯文本 → 带生僻字字体标签的片段（含转义）"""
    parts = _RARE_RE.split(t)
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 0:
            out.append(esc(p)); continue
        buf, cur = "", None
        for ch in p:
            cp = ord(ch)
            if cp not in COV_B and cp not in COV_G:
                n = unicodedata.normalize("NFKC", ch)
                if n and ord(n[0]) != cp and ord(n[0]) in COV_B:
                    ch = n[0]; cp = ord(ch)
            f = _pick_font(cp)
            if f != cur:
                if buf:
                    out.append('<font name="%s">%s</font>' % (cur, esc(buf)))
                cur, buf = f, ""
            buf += ch
        if buf:
            out.append('<font name="%s">%s</font>' % (cur, esc(buf)))
    return "".join(out)


def rich(t):
    """源文本 → 段落标记。行内支持 **朱红加粗重点** 与 ==底色高亮==。"""
    t = _PUA_RE.sub("", t.translate(_SUB_TAB))
    out = []
    for seg in _INLINE_RE.split(t):
        if not seg:
            continue
        if len(seg) > 4 and seg.startswith("**") and seg.endswith("**"):
            out.append('<font name="Hei" color="%s">%s</font>'
                       % (ACCENT_HEX, _rich_plain(seg[2:-2])))
        elif len(seg) > 4 and seg.startswith("==") and seg.endswith("=="):
            out.append('<font backColor="%s">%s</font>'
                       % (HL_HEX, _rich_plain(seg[2:-2])))
        else:
            out.append(_rich_plain(seg))
    # 整段只有一段行内标记时，reportlab 的 CJK 单片段路径不会绘制 backColor；
    # 补一个空片段强制走多片段路径，底色才画得出来。
    if len(out) == 1 and out[0].startswith("<font "):
        return out[0] + '<font name="Song"> </font>'
    return "".join(out)


# ---------------- 章节解析 ----------------
META_RE = re.compile(r"^(内容|书名|作者|来源|说明|分类|标签|字数|出版社|整理|注译|简介"
                     r"|正文|全文|原文|校订|编者|出品|朝代|年份|卷数|册数)[:：]")
HEAD_RE = re.compile(r"^第[一二三四五六七八九十百千零〇\d]+[篇卷章回部]")
VOL_RE = re.compile(r"^卷(?:之)?[一二三四五六七八九十百千零〇\d]+")
STANDALONE_RE = re.compile(r"[卷部]$")
BRACKET_RE = re.compile(r"^【[^】]{1,30}】$")
FRONT_RE = re.compile(r"^(序|序言|前言|引言|引|导言|凡例|例言|附录|后记|跋"
                      r"|编辑说明|说明|自序)$")
WIKI_HEAD_RE = re.compile(r"^={1,4}\s*(.{1,30}?)\s*={1,4}$")
TAIL_NUM_RE = re.compile(r"^[^，。！？；：\s]{1,14}第[一二三四五六七八九十百千〇\d]{1,6}$")
BOOK_DASH_RE = re.compile(r"^[^，。！？；：、\s（）()「」《》]{1,8}[-－—]\s*[^，。！？；：\s]{1,30}$")
GONG_YEAR_RE = re.compile(r"^[^，。！？；\s]{1,4}公[一二三四五六七八九十元]{1,3}年$")
PSEUDO_TITLES = {"原文", "注释", "翻译", "解读", "译文", "赏析", "题解", "说明",
                 "提要", "点评", "校勘", "校记", "正文", "全文", "集解", "附录",
                 "题目", "答案", "白话", "文言"}
NAV_RE = re.compile(r"^(?:上|下)一[篇章回卷]$")
NAV_WORDS = {"返回", "目录", "首页", "上一页", "下一页", "顶部", "底部",
             "上一章", "下一章", "上一回", "下一回"}


# 守卫：叙事行伪标题（"第四回中既将薛家母子……"），回目数词后紧跟虚词
_HEAD_PARTICLE_RE = re.compile(
    r"^第[一二三四五六七八九十百千零〇\d]+[篇卷章回部][中里内外前后之间上下]")


def _is_head_line(s, enhanced=False):
    if HEAD_RE.match(s) or VOL_RE.match(s) or BRACKET_RE.match(s) or FRONT_RE.match(s):
        if _HEAD_PARTICLE_RE.match(s) or len(s) > 40:
            return False
        return True
    if 2 <= len(s) <= 9 and STANDALONE_RE.search(s):
        return True
    if not enhanced:
        return False
    return bool(WIKI_HEAD_RE.match(s) or TAIL_NUM_RE.match(s)
                or BOOK_DASH_RE.match(s) or GONG_YEAR_RE.match(s))


def _norm_title(t):
    if not t:
        return ""
    t = re.sub(r"^[^，。！？；：\s]{1,8}[-－—]\s*", "", t)
    return re.sub(r"\s+", "", t)


# 句读/标点：行尾标点比例极低 → OCR 列宽硬截断
_PUNCT_END = set("。！？.!?」』）〕》、；：，")
_SENT_END = set("。！？.!?」』）〕》")


def is_wrapped(lines):
    ne = [l.strip() for l in lines if l.strip()]
    if len(ne) < 20:
        return False
    return sum(1 for l in ne if l[-1] in _PUNCT_END) / len(ne) < 0.35


def parse_text(raw):
    """返回 [(章节标题|None, [段落...]), ...]"""
    raw = conv(clean_text(raw))
    lines = [l.rstrip() for l in raw.split("\n")]

    def build(enhanced, merge):
        chapters, title, paras = [], None, []
        buf = ""

        def flush_buf():
            nonlocal buf
            if buf:
                paras.append(buf); buf = ""

        def flush():
            nonlocal title, paras
            if paras or title:
                if (enhanced and title and chapters
                        and _norm_title(title) == _norm_title(chapters[-1][0])):
                    chapters[-1][1].extend(paras)
                else:
                    chapters.append((title, paras))
            paras = []

        for ln in lines:
            s = ln.strip()
            if not s:
                continue          # 空行不断段（合并模式下扫描本每列后都插空行）
            indent = len(ln) - len(ln.lstrip())
            if s.startswith("@@"):
                # 结构化标记独占一行，任何模式下都不与相邻文字合并
                if merge:
                    flush_buf()
                paras.append(s)
                continue
            if s.startswith("#"):
                h = re.sub(r"^#+\s*", "", s).strip()
                if h and _is_head_line(h, enhanced):
                    s = h
                else:
                    continue
            if META_RE.match(s):
                continue
            if (NAV_RE.match(s) or s in NAV_WORDS
                    or "回目录" in s or "上一篇" in s or "下一篇" in s):
                continue
            # 维基标题 `== X ==` 只在宽松回退里识别；严格模式下 `==…==`
            # 是行内高亮（整行高亮时形似维基标题），不能被剥掉。
            mw = WIKI_HEAD_RE.match(s) if enhanced else None
            if mw:
                s = mw.group(1).strip()
                if not s:
                    continue
            mb = BRACKET_RE.match(s)
            if mb and mb.group(0)[1:-1].strip() in PSEUDO_TITLES:
                continue
            if _is_head_line(s, enhanced):
                if merge:
                    flush_buf()
                flush(); title = s; paras = []; continue
            if merge:
                if buf and (buf[-1] in _SENT_END or indent >= 2 or len(buf) >= 500):
                    flush_buf()
                buf = buf + s if buf else s
            else:
                paras.append(s)
        if merge:
            flush_buf()
        flush()
        return chapters

    merge = is_wrapped(lines)
    chs = build(False, merge)
    if sum(1 for t, _ in chs if t) < 3:      # 严格规则抓不到 → 宽松规则兜底
        chs2 = build(True, merge)
        if sum(1 for t, _ in chs2 if t) > sum(1 for t, _ in chs if t):
            chs = chs2
    if not chs:
        chs = [(None, [l.strip() for l in lines if l.strip()])]
    return chs, merge


# ---------------- 样式 ----------------
def S(**kw):
    base = dict(fontName="Song", wordWrap="CJK", firstLineIndent=0,
                spaceBefore=0, spaceAfter=0)
    base.update(kw)
    return ParagraphStyle("x", **base)


def make_styles(size=11.5, lead=21.5, preset="classic"):
    st = {
        "cover_series": S(fontName="Kai", fontSize=13, leading=20,
                          alignment=TA_CENTER, textColor=SEAL),
        "cover_title": S(fontName="Kai", fontSize=46, leading=58,
                         alignment=TA_CENTER, textColor=HexColor("#2b2520")),
        "cover_year": S(fontName="Song", fontSize=11, leading=20,
                        alignment=TA_CENTER, textColor=GRAY),
        "cover_author": S(fontName="Kai", fontSize=15, leading=26,
                          alignment=TA_CENTER, textColor=INK),
        "front_title": S(fontName="Hei", fontSize=16, leading=24,
                         alignment=TA_CENTER, spaceAfter=10),
        "front_body": S(fontName="Fang", fontSize=10, leading=16.5,
                        alignment=TA_JUSTIFY),
        "toc_title": S(fontName="Hei", fontSize=17, leading=26,
                       alignment=TA_CENTER, spaceAfter=12),
        "chapter": S(fontName="Hei", fontSize=16, leading=26, alignment=TA_CENTER,
                     spaceBefore=16, spaceAfter=14, keepWithNext=1),
        "body": S(fontName="Song", fontSize=size, leading=lead,
                  alignment=TA_JUSTIFY, firstLineIndent=size * 2, spaceAfter=7),
        "body_poem": S(fontName="Song", fontSize=size, leading=lead,
                       alignment=TA_CENTER, firstLineIndent=0, spaceAfter=0),
        "note": S(fontName="Hei", fontSize=size - 1.3, leading=lead - 4.5,
                  alignment=TA_JUSTIFY, firstLineIndent=0, leftIndent=16,
                  rightIndent=4, textColor=GRAY, spaceBefore=3, spaceAfter=10),
        # --- 结构化板块（精华小书 / 摘录类书稿）---
        "h2": S(fontName="Hei", fontSize=size + 1.5, leading=lead + 3,
                alignment=0, textColor=INK, spaceBefore=15, spaceAfter=7,
                keepWithNext=1),
        "lead": S(fontName="Hei", fontSize=size + 0.5, leading=lead + 1,
                  alignment=TA_JUSTIFY, textColor=HexColor("#2b2520"),
                  spaceBefore=0, spaceAfter=0),
        "lead_label": S(fontName="Hei", fontSize=8.5, leading=13,
                        alignment=0, textColor=SEAL, spaceBefore=0, spaceAfter=4),
        "quote": S(fontName="Fang", fontSize=size - 0.3, leading=lead - 0.5,
                   alignment=TA_JUSTIFY, firstLineIndent=0, textColor=INK,
                   spaceBefore=0, spaceAfter=0),
        "byline": S(fontName="Hei", fontSize=size - 2.2, leading=lead - 5,
                    alignment=TA_JUSTIFY, firstLineIndent=0, textColor=GRAY,
                    spaceBefore=9, spaceAfter=4),
        "gem": S(fontName="Kai", fontSize=size + 2.5, leading=lead + 7,
                 alignment=TA_JUSTIFY, firstLineIndent=0,
                 textColor=HexColor("#2b2520"), spaceBefore=0, spaceAfter=0),
        "gem_label": S(fontName="Hei", fontSize=9, leading=15,
                       alignment=TA_CENTER, textColor=SEAL,
                       spaceBefore=0, spaceAfter=7),
        "key": S(fontName="Hei", fontSize=size + 0.2, leading=lead + 1,
                 alignment=TA_JUSTIFY, firstLineIndent=0, leftIndent=10,
                 textColor=SEAL, spaceBefore=8, spaceAfter=9),
        "point": S(fontName="Song", fontSize=size - 0.3, leading=lead - 1,
                   alignment=TA_JUSTIFY, firstLineIndent=0, leftIndent=16,
                   spaceBefore=0, spaceAfter=5),
        "cap": S(fontName="Song", fontSize=size - 2.2, leading=lead - 5,
                 alignment=TA_CENTER, firstLineIndent=0, textColor=GRAY,
                 spaceBefore=4, spaceAfter=8),
    }
    st.update({
        "pic_label": S(fontName="Hei", fontSize=8.5, leading=13, alignment=0,
                       textColor=SEAL, spaceBefore=0, spaceAfter=4),
        "pic": S(fontName="Song", fontSize=size + 1.6, leading=lead + 5,
                 alignment=0, firstLineIndent=0, textColor=INK,
                 spaceBefore=0, spaceAfter=0),
        # 评论卡：一张卡自带来源行与原文，来源不脱离内容
        "cmt_src": S(fontName="Hei", fontSize=size - 2.2, leading=lead - 4.5,
                     alignment=0, firstLineIndent=0, textColor=GRAY,
                     spaceBefore=0, spaceAfter=5),
        "cmt_body": S(fontName="Hei", fontSize=size + 0.6, leading=lead + 1,
                      alignment=TA_JUSTIFY, firstLineIndent=0, textColor=INK,
                      spaceBefore=0, spaceAfter=0),
        "cmt_star": S(fontName="Hei", fontSize=size + 1.8, leading=lead + 3,
                      alignment=TA_JUSTIFY, firstLineIndent=0, textColor=INK,
                      spaceBefore=0, spaceAfter=0),
        "cmt_note": S(fontName="Hei", fontSize=size - 2.4, leading=lead - 4,
                      alignment=0, firstLineIndent=0, textColor=GRAY,
                      spaceBefore=5, spaceAfter=0),
        # 金句署名：右对齐独立小字，避免 CJK 换行把昵称拆断
        "key_by": S(fontName="Hei", fontSize=size - 2.4, leading=lead - 4,
                    alignment=TA_RIGHT, firstLineIndent=0, textColor=GRAY,
                    spaceBefore=0, spaceAfter=9),
    })
    if preset == "xhs":
        # 小红书风格：黑体正文、无首行缩进、行距收紧，字号整体小一档
        st.update({
            "chapter": S(fontName="Hei", fontSize=15, leading=24, alignment=0,
                         leftIndent=13, spaceBefore=13, spaceAfter=7,
                         textColor=INK, keepWithNext=1),
            "body": S(fontName="Hei", fontSize=size, leading=lead,
                      alignment=TA_JUSTIFY, firstLineIndent=0, spaceAfter=5),
            "body_poem": S(fontName="Hei", fontSize=size, leading=lead,
                           alignment=TA_CENTER, firstLineIndent=0, spaceAfter=0),
            "note": S(fontName="Hei", fontSize=size - 1.6, leading=lead - 3.5,
                      alignment=TA_JUSTIFY, firstLineIndent=0, leftIndent=11,
                      rightIndent=2, textColor=GRAY, spaceBefore=2,
                      spaceAfter=8),
            "h2": S(fontName="Hei", fontSize=size + 1.3, leading=lead + 3,
                    alignment=0, textColor=SEAL, spaceBefore=12, spaceAfter=5,
                    keepWithNext=1),
            "lead": S(fontName="Hei", fontSize=size, leading=lead,
                      alignment=TA_JUSTIFY, textColor=INK,
                      spaceBefore=0, spaceAfter=0),
            "lead_label": S(fontName="Hei", fontSize=8, leading=12,
                            alignment=0, textColor=SEAL, spaceBefore=0,
                            spaceAfter=3),
            "quote": S(fontName="Hei", fontSize=size - 0.2, leading=lead - 0.5,
                       alignment=TA_JUSTIFY, firstLineIndent=0,
                       textColor=HexColor("#3d3d3d"), spaceBefore=0, spaceAfter=0),
            "byline": S(fontName="Hei", fontSize=size - 2.4, leading=lead - 5,
                        alignment=TA_JUSTIFY, firstLineIndent=0, textColor=GRAY,
                        spaceBefore=8, spaceAfter=3),
            "gem": S(fontName="Hei", fontSize=size + 1.2, leading=lead + 3,
                     alignment=TA_JUSTIFY, firstLineIndent=0, textColor=INK,
                     spaceBefore=0, spaceAfter=0),
            "gem_label": S(fontName="Hei", fontSize=8.4, leading=13,
                           alignment=TA_CENTER, textColor=SEAL,
                           spaceBefore=0, spaceAfter=6),
            "key": S(fontName="Hei", fontSize=size, leading=lead,
                     alignment=TA_JUSTIFY, firstLineIndent=0, leftIndent=9,
                     textColor=SEAL, spaceBefore=6, spaceAfter=7),
            "point": S(fontName="Hei", fontSize=size - 0.3, leading=lead - 1,
                       alignment=TA_JUSTIFY, firstLineIndent=0, leftIndent=13,
                       spaceBefore=0, spaceAfter=3),
            "cap": S(fontName="Hei", fontSize=size - 2, leading=lead - 5,
                     alignment=TA_CENTER, firstLineIndent=0, textColor=GRAY,
                     spaceBefore=3, spaceAfter=6),
            "pic_label": S(fontName="Hei", fontSize=8, leading=12,
                           alignment=0, textColor=GRAY, spaceBefore=0,
                           spaceAfter=3),
            "pic": S(fontName="Song", fontSize=size + 1.2, leading=lead + 3,
                     alignment=0, firstLineIndent=0, textColor=INK,
                     spaceBefore=0, spaceAfter=0),
        })
    return st


def card(rows, width, fill, bar, bar_w=3, pad_v=9, rules=False, box=False):
    """带左侧色条的浅底板块，rows 为 Flowable 列表。

    box=True 时补一圈细边框（精髓评论卡用）。
    """
    t = Table([[r] for r in rows], colWidths=[width])
    cmds = [("BACKGROUND", (0, 0), (-1, -1), fill),
            ("LINEBEFORE", (0, 0), (0, -1), bar_w, bar),
            ("LEFTPADDING", (0, 0), (-1, -1), 13),
            ("RIGHTPADDING", (0, 0), (-1, -1), 11),
            ("TOPPADDING", (0, 0), (-1, -1), pad_v),
            ("BOTTOMPADDING", (0, 0), (-1, -1), pad_v),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    if rules:
        cmds += [("LINEABOVE", (0, 0), (-1, 0), 0.6, bar),
                 ("LINEBELOW", (0, -1), (-1, -1), 0.6, bar)]
    if box:
        cmds += [("BOX", (0, 0), (-1, -1), 0.8, bar)]
    t.setStyle(TableStyle(cmds))
    return t


def rule(width, color=None, gap=9):
    t = Table([[""]], colWidths=[width], rowHeights=[1])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5,
                            color or LGRAY),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return [Spacer(1, gap), t, Spacer(1, gap)]


def _is_poem_title(s):
    s = s.strip()
    return bool(s) and ("／" in s or "/" in s or s[0] in "○〇")


def _ends_sentence(s):
    s = s.strip()
    return bool(s) and s[-1] in "。！？”』」）.!?"


def _is_verse(s):
    return bool(s.strip()) and len(s.strip()) <= 40


# ---------------- 文档组装 ----------------
class BookDoc(BaseDocTemplate):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.chap_map = {}
        self._chap_seq = 0

    def handle_documentBegin(self):
        self._chap_seq = 0
        self.chap_map = {}
        super().handle_documentBegin()

    def afterFlowable(self, f):
        if not isinstance(f, ChapterHead):
            return
        txt = clean_chapter_title(f.getPlainText())
        if not txt:
            return
        disp = "【%s】" % txt if re.match(
            r"第[一二三四五六七八九十百千零〇\d]+[回章]", txt) and "【" not in txt else txt
        self._chap_seq += 1
        key = "ch-%d" % self._chap_seq
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(disp, key, level=0)
        self.notify("TOCEntry", (0, disp, self.page, key))
        self.chap_map[self.page] = disp


class ChapterHead(Paragraph):
    accent = None          # 设置后，在标题左侧画一条竖色条（xhs 版式）

    def draw(self):
        STATE["chap"] = self.getPlainText()
        if self.accent:
            c = self.canv
            c.saveState()
            c.setFillColor(self.accent)
            h = getattr(self, "fontSize", 15) * 1.05
            c.rect(0, self.height - h - 1.5, 3.4, h, fill=1, stroke=0)
            c.restoreState()
        Paragraph.draw(self)


class _TOC(TableOfContents):
    def __init__(self):
        ts = TableStyle([("TOPPADDING", (0, 0), (-1, -1), 0),
                         ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                         ("LEFTPADDING", (0, 0), (-1, -1), 0),
                         ("RIGHTPADDING", (0, 0), (-1, -1), 0)])
        super().__init__(tableStyle=ts)
        self.dotsMinLevel = 0
        self.levelStyles = [ParagraphStyle("toc0", fontName="Song", fontSize=11,
                                           leading=19, wordWrap="CJK")]


# 版式文案主题。classic 为默认的古籍整理版，逐字保持原有输出；
# modern 用于当代网络内容摘录，避免「公有领域 / 公版古籍」这类与事实不符的版权声明。
THEMES = {
    "classic": {
        "name": "classic",
        "cover_series": "国学经典 · 原文整理丛书",
        "back_series": "国 学 经 典 · 原 文 整 理 丛 书",
        "edition": "二〇二六年 · 公版古籍整理版",
        "intro_suffix": " 本版据公版底本细心校勘、重排标点，存真去芜，便于今日读者展卷研读。",
        "editor_note": "愿这本重排的经典便于掌上展卷、随时研读，使传世文字免于湮没，代代可读。",
        "copyright_line": "本书据公版文献重新整理，原书著作权已入公有领域。",
        "front_maker": "本整理本由%s制作并发布，请在「合理使用」范围内使用。",
        "front_notice": "【关于公版书】本书版权保护期已届满，属于公有领域（公版书）。根据我国"
                        "《著作权法》第二十、二十一条，作者死亡后第五十年的十二月三十一日起，除署名权、"
                        "修改权、保护作品完整权外，作品进入公有领域。本书即属此列。",
        "front_license": "【使用许可】本书可供中华人民共和国及世界上大多数地区的任何人免费使用，"
                         "几乎不受限制；您可依据「公版书许可条款」对其进行复制、赠送或改编。"
                         "若您不在中华人民共和国境内，请先了解所在国家／地区的法律规定。",
        "front_disclaimer": "本整理本仅供个人阅读与学习之用；整理者不对文本讹误承担考据责任，"
                           "读者宜以权威印本为据。",
    },
    "modern": {
        "name": "modern",
        "cover_series": "刷到即存 · 精华小书",
        "back_series": "刷 到 即 存 · 小 红 书 精 华",
        "edition": "二〇二六年 · 个人阅读存档本",
        "intro_suffix": "",
        "editor_note": "把信息流里一划就过、却让人停了三秒的东西，认真留成书页。仅供个人翻阅，不作他用。",
        "copyright_line": "著作权归原作者所有 · 仅供个人阅读存档，请勿传播或商用",
        "front_maker": "本册由%s为个人阅读存档而整理，不含任何品牌或商业用途。",
        "front_notice": "【关于版权】本册所收原文为当代创作者的作品，著作权归各原作者所有，不属于公有领域。"
                        "本册保留作者署名与出处，仅为个人阅读存档所作的非商业摘录，"
                        "未获授权不得转载、公开传播或用于商业目的。",
        "front_license": "【使用范围】本册仅供制作人个人阅读、学习与存档。如需引用原文，请回到原帖核对，"
                         "并注明原作者与链接；编者序、拆解与按语为编者观点，不代表原作者立场。",
        "front_disclaimer": "本册依据公开分享页采集整理，原帖图片、发布时间与互动数据未能取得的部分"
                           "均未补写或推测。内容整理者不对文本完整性承担考据责任。",
    },
    "xhs": {
        "name": "xhs",
        "cover_series": "刷 到 即 存 · 小 红 书 精 华",
        "back_series": "刷 到 即 存 · 小 红 书 精 华",
        "edition": "二〇二六年 · 个人阅读存档本",
        "intro_suffix": "",
        "editor_note": "把信息流里一划就过、却让人停了三秒的东西，认真留成书页。仅供个人翻阅，不作他用。",
        "copyright_line": "著作权归原作者所有 · 仅供个人阅读存档，请勿传播或商用",
        "front_maker": "本册由%s为个人阅读存档而整理，不含任何品牌或商业用途。",
        "front_notice": "【关于版权】本册所收原文为当代创作者的作品，著作权归各原作者所有，不属于公有领域。"
                        "本册保留作者署名与出处，仅为个人阅读存档所作的非商业摘录，"
                        "未获授权不得转载、公开传播或用于商业目的。",
        "front_license": "【使用范围】本册仅供制作人个人阅读、学习与存档。如需引用原文，请回到原帖核对，"
                         "并注明原作者与链接；编者序、拆解与按语为编者观点，不代表原作者立场。",
        "front_disclaimer": "本册依据公开分享页采集整理，图片内文字已逐字转录并标明来源；"
                            "未取得或不可核实的部分均未补写或推测。",
    },
}


class BackCover(Flowable):
    """封底页（末页）：宣纸底+双线框，含丛书名/书名/作者/简介/寄语/声明；品牌模式另附藏书印与联系图。"""
    def __init__(self, title, author, intro, assets=None, brand="", theme=None):
        Flowable.__init__(self)
        self.title, self.author, self.intro = title, author, intro
        self.assets = assets or ASSET_DIR
        self.brand = brand
        self.theme = theme or THEMES["classic"]

    def wrap(self, aw, ah):
        return (aw, ah)

    def draw(self):
        c, W, H = self.canv, PAGE_W, PAGE_H
        c.setFillColor(PAPER); c.rect(0, 0, W, H, fill=1, stroke=0)
        m = 14 * mm
        xhs = (self.theme.get("name") == "xhs")
        if xhs:
            c.setFillColor(SEAL)
            c.rect(0, H - 5 * mm, W, 5 * mm, fill=1, stroke=0)
        else:
            c.setStrokeColor(INK); c.setLineWidth(1.3)
            c.rect(m, m, W - 2 * m, H - 2 * m, fill=0, stroke=1)
            c.setLineWidth(0.4)
            c.rect(m - 2.5 * mm, m - 2.5 * mm, W - 2 * (m - 2.5 * mm),
                   H - 2 * (m - 2.5 * mm), fill=0, stroke=1)
        _draw_seal(c, W, H, m, self.brand)
        cx = W / 2
        content_w = 108 * mm
        x0 = (W - content_w) / 2
        c.setFillColor(INK); c.setStrokeColor(INK)
        y = H - 24 * mm
        # 丛书名（与封面同款红字）
        c.setFillColor(SEAL)
        c.setFont("Hei" if xhs else "Kai", 11.5 if xhs else 13)
        c.drawCentredString(cx, y, self.theme["back_series"])
        y -= 18 * mm
        # 书名 / 作者
        c.setFillColor(INK); c.setFont("Hei" if xhs else "Kai", 24)
        t = self.title
        c.drawCentredString(cx, y, " ".join(t) if len(t) <= 4 else t)
        y -= 7 * mm
        c.setFillColor(GRAY); c.setFont("Hei" if xhs else "Kai", 11 if xhs else 12)
        c.drawCentredString(cx, y, self.author)
        y -= 7 * mm
        # 细分隔线
        c.setLineWidth(0.8 if xhs else 0.6)
        c.setStrokeColor(SEAL if xhs else INK)
        c.line(cx - 12 * mm, y, cx + 12 * mm, y)
        y -= 9 * mm
        # 内容简介
        c.setFillColor(INK); c.setFont("Hei", 14)
        c.drawCentredString(cx, y, "内 容 简 介")
        y -= 7 * mm
        full = self.intro + self.theme["intro_suffix"]
        c.setFillColor(HexColor("#2a2a2a"))
        c.setFont("Hei" if xhs else "Song", 10 if xhs else 10.5)
        for ln in _bc_wrap(full, "Hei" if xhs else "Song", 10 if xhs else 10.5,
                           content_w):
            c.drawString(x0, y, ln); y -= 5.6 * mm
        y -= 4 * mm
        # 编者寄语（品牌模式带品牌名，通用版为中性寄语）
        c.setFillColor(INK); c.setFont("Hei", 13)
        c.drawCentredString(cx, y, "编 者 寄 语")
        y -= 6 * mm
        if self.brand and self.theme["name"] == "classic":
            brand = ("%s 深耕公版古籍之数字化整理，校勘标点、重排传世，"
                     "使经典免于湮没，便于掌上展卷、随时研读。" % self.brand)
        else:
            brand = self.theme["editor_note"]
        c.setFillColor(GRAY)
        c.setFont("Hei" if xhs else "Song", 9 if xhs else 9.5)
        for ln in _bc_wrap(brand, "Hei" if xhs else "Song", 9 if xhs else 9.5,
                           content_w):
            c.drawString(x0, y, ln); y -= 5.0 * mm
        y -= 4 * mm
        # 公版声明
        c.setFillColor(GRAY if xhs else LGRAY)
        c.setFont("Hei" if xhs else "Song", 8 if xhs else 8.5)
        c.drawCentredString(cx, y, self.theme["copyright_line"])
        y -= 5 * mm
        # 联系二维码 + 头像（仅品牌模式且有素材时绘制）
        if self.brand:
            qr = _qr_file(self.assets)
            av = os.path.join(self.assets, "头像_%s.jpg" % self.brand)
            qw = ah = 22 * mm
            gap = 6 * mm
            total = qw + gap + ah
            qx = cx - total / 2
            ax = qx + qw + gap
            if os.path.exists(qr):
                c.drawImage(qr, qx, y - qw, width=qw, height=qw)
            if os.path.exists(av):
                c.drawImage(av, ax, y - ah, width=ah, height=ah)
            c.setFont("Song", 8); c.setFillColor(GRAY)
            c.drawCentredString(qx + qw / 2, y - qw - 3.5 * mm, "扫码联系")
            c.drawCentredString(ax + ah / 2, y - ah - 3.5 * mm, self.brand)
            y -= qw + 9 * mm
        else:
            y -= 6 * mm
        # 版本年
        c.setFillColor(GRAY); c.setFont("Song", 10)
        c.drawCentredString(cx, y, self.theme["edition"])


def _bc_wrap(text, font, size, max_w):
    """按宽度折行，并做中文标点禁则：不让行首出现标点。"""
    bad_start = "，。、；：！？）》」』】〕”’,.;:!?)]}"
    bad_end = "（《「『【〔“‘([{"
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        if pdfmetrics.stringWidth(cur + ch, font, size) > max_w and cur:
            # 行首禁止标点：把上一字挪到下一行，避免标点落在行首
            if ch in bad_start and len(cur) > 1:
                lines.append(cur[:-1]); cur = cur[-1] + ch
            # 行尾禁止开引号/开括号：把它一起挪下去
            elif cur[-1] in bad_end and len(cur) > 1:
                lines.append(cur[:-1]); cur = cur[-1] + ch
            else:
                lines.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def _qr_file(assets):
    """二维码素材：优先通用名 二维码.jpg，兼容历史名。"""
    for name in ("二维码.jpg", "二维码_微信.jpg", "qrcode.jpg"):
        p = os.path.join(assets, name)
        if os.path.exists(p):
            return p
    return os.path.join(assets, "二维码.jpg")


def _contact_block(brand=""):
    """出版说明页脚：二维码 + 品牌头像 双栏联系图（仅品牌模式且素材齐全时）。"""
    if not brand:
        return Spacer(1, 2)
    qr = _qr_file(ASSET_DIR)
    av = os.path.join(ASSET_DIR, "头像_%s.jpg" % brand)
    if not (os.path.exists(qr) and os.path.exists(av)):
        return Spacer(1, 2)
    w_qr = 27 * mm
    h_qr = w_qr * 1871.0 / 1632.0
    h_av = 27 * mm
    cell = (PAGE_W - 108) / 2.0        # 与正文左右边距(M_L/M_R=54pt)一致的栏宽
    t = Table([[Image(qr, width=w_qr, height=h_qr), Image(av, width=h_av, height=h_av)]],
              colWidths=[cell, cell])
    t.setStyle(TableStyle([
        ("ALIGN",     (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",    (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, HexColor("#dddddd")),
    ]))
    return t


def make_toc_chapters(chapters, title="", max_vol=15):
    """无章节标题时按字数切分为「书名·第N辑」兜底，保证每本书都有目录"""
    if any(t for t, _ in chapters):
        return chapters
    paras = [p for _, ps in chapters for p in ps]
    total = sum(len(p) for p in paras)
    n = max(5, min(max_vol, math.ceil(total / 8000))) if total else 6
    groups, cur, cs, target = [], [], 0, total / n
    for p in paras:
        if cur and cs + len(p) > target and len(groups) < n - 1:
            groups.append(cur); cur, cs = [], 0
        cur.append(p); cs += len(p)
    if cur:
        groups.append(cur)
    return [("%s·第%d辑" % (title, i + 1) if title else "第%d辑" % (i + 1), g)
            for i, g in enumerate(groups)]


def assemble(chapters, out, title, author, intro, poetry=False,
             assets=None, size=11.5, lead=21.5, page=A5, brand="", theme=None,
             preset="classic"):
    global PAGE_W, PAGE_H
    PAGE_W, PAGE_H = page
    theme = theme or THEMES["classic"]
    title, author, intro = conv(title), conv(author), conv(intro)
    STATE["book"] = title
    ST = make_styles(size, lead, preset)

    if preset == "xhs":
        M_TOP, M_BOT, M_L, M_R = 42, 36, 44, 44   # 版心更宽，信息密度更高
    else:
        M_TOP, M_BOT, M_L, M_R = 58, 52, 54, 54
    LEFT, RIGHT = M_L, PAGE_W - M_R
    TOP_Y, BOT_Y = PAGE_H - M_TOP, M_BOT

    doc = BookDoc(out, pagesize=page, leftMargin=M_L, rightMargin=M_R,
                  topMargin=M_TOP, bottomMargin=M_BOT, title=title, author=author)
    frame = Frame(LEFT, BOT_Y, RIGHT - LEFT, TOP_Y - BOT_Y - 12, id="body")
    frame_toc = Frame(M_L, 28 * mm, PAGE_W - M_L - M_R,
                      (PAGE_H - 30 * mm) - 28 * mm - 12, id="toc")
    frame_back = Frame(0, 0, PAGE_W, PAGE_H, id="back",
                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    def body_bg(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(HEAD_RULE); canvas.setLineWidth(0.6)
        canvas.line(LEFT, TOP_Y - 8, RIGHT, TOP_Y - 8)
        canvas.setFont("Song", 8.5); canvas.setFillColor(HexColor("#666666"))
        canvas.drawString(LEFT, TOP_Y, STATE["book"])
        if theme["name"] == "classic":
            chap = ""
            for pg in sorted(doc.chap_map):
                if pg <= doc.page:
                    chap = doc.chap_map[pg]
                else:
                    break
            canvas.drawRightString(RIGHT, TOP_Y, chap)
        else:
            canvas.drawRightString(RIGHT, TOP_Y, theme["cover_series"])
        canvas.setFont("Song", 9)
        canvas.drawCentredString(PAGE_W / 2, BOT_Y - 14, "— %d —" % doc.page)
        canvas.restoreState()

    def plain_bg(canvas, doc):
        canvas.saveState()
        canvas.setFont("Song", 9); canvas.setFillColor(LGRAY)
        canvas.drawCentredString(PAGE_W / 2, 16 * mm, "— %d —" % doc.page)
        canvas.restoreState()

    def cover_bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(PAPER); canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        if preset == "xhs":
            canvas.setFillColor(SEAL)
            canvas.rect(0, PAGE_H - 5 * mm, PAGE_W, 5 * mm, fill=1, stroke=0)
            canvas.setStrokeColor(SEAL); canvas.setLineWidth(1.2)
            canvas.line(46, PAGE_H - 96, 46 + 26 * mm, PAGE_H - 96)
            canvas.restoreState()
            return
        m = 14 * mm
        canvas.setStrokeColor(INK); canvas.setLineWidth(1.3)
        canvas.rect(m, m, PAGE_W - 2 * m, PAGE_H - 2 * m, fill=0, stroke=1)
        canvas.setLineWidth(0.4)
        canvas.rect(m - 2.5 * mm, m - 2.5 * mm, PAGE_W - 2 * (m - 2.5 * mm),
                    PAGE_H - 2 * (m - 2.5 * mm), fill=0, stroke=1)
        _draw_seal(canvas, PAGE_W, PAGE_H, m, brand)
        canvas.restoreState()

    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame], onPage=cover_bg),
        PageTemplate(id="toc", frames=[frame_toc], onPage=plain_bg),
        PageTemplate(id="body", frames=[frame], onPage=body_bg),
        PageTemplate(id="back", frames=[frame_back], onPage=plain_bg),
    ])

    if preset == "xhs":
        cov_series = ParagraphStyle("cov_series_x", parent=ST["cover_series"],
                                    fontName="Hei", fontSize=9.5, leading=16,
                                    alignment=0, spaceAfter=0)
        cov_title = ParagraphStyle("cov_title_x", parent=ST["cover_title"],
                                   fontName="Hei", fontSize=33, leading=45,
                                   alignment=0, textColor=INK)
        cov_author = ParagraphStyle("cov_author_x", parent=ST["cover_author"],
                                    fontName="Hei", fontSize=12, leading=20,
                                    alignment=0, textColor=GRAY)
        cov_year = ParagraphStyle("cov_year_x", parent=ST["cover_year"],
                                  fontName="Hei", fontSize=9, leading=16,
                                  alignment=0, textColor=LGRAY)
        story = [Spacer(1, 96), Paragraph(theme["cover_series"], cov_series),
                 Spacer(1, 30), Paragraph(title, cov_title),
                 Spacer(1, 40), Paragraph(author, cov_author),
                 Spacer(1, 150), Paragraph(theme["edition"], cov_year),
                 NextPageTemplate("toc"), PageBreak()]
    else:
        story = [Spacer(1, 70), Paragraph(theme["cover_series"], ST["cover_series"]),
                 Spacer(1, 26),
                 Paragraph(" ".join(title) if len(title) <= 4 else title, ST["cover_title"]),
                 Spacer(1, 50), Paragraph(author, ST["cover_author"]), Spacer(1, 122),
                 Paragraph(theme["edition"], ST["cover_year"]),
                 NextPageTemplate("toc"), PageBreak()]

    # 出版说明（简介 → 制作说明 → 版权声明 → 使用范围 → 免责 → 联系图[品牌模式]）
    maker = ("「%s」" % brand) if brand else "整理者"
    story += [Paragraph("出 版 说 明", ST["front_title"]), Spacer(1, 6),
              Paragraph(rich(intro), ST["front_body"]), Spacer(1, 8),
              Paragraph(esc(theme["front_maker"] % maker), ST["front_body"]),
              Spacer(1, 8),
              Paragraph(esc(theme["front_notice"]), ST["front_body"]),
              Spacer(1, 8),
              Paragraph(esc(theme["front_license"]), ST["front_body"]),
              Spacer(1, 8),
              Paragraph(esc(theme["front_disclaimer"]), ST["front_body"]),
              Spacer(1, 8),
              _contact_block(brand)]

    toc_chapters = make_toc_chapters(chapters, title)
    story += [NextPageTemplate("toc"), PageBreak(), Paragraph("目 录", ST["toc_title"]),
              _TOC(), NextPageTemplate("body"), PageBreak()]

    cap_style = ParagraphStyle("img_caption", parent=ST["body"], fontSize=9,
                               leading=14, alignment=1, textColor=GRAY)

    def card_flow(p):
        """卡片类板块只返回 Table，交给 KeepTogether 包裹，杜绝跨页断裂。"""
        w = RIGHT - LEFT
        if p.startswith(("@@CMT ", "@@STAR ")):
            # 评论卡：来源行 ｜ 原文 ｜ 可选一句短评，一张卡自足
            star = p.startswith("@@STAR ")
            spec = p[7:].strip() if star else p[6:].strip()
            parts = [x.strip() for x in spec.split("｜", 2)]
            src = parts[0] if parts else ""
            body = parts[1] if len(parts) > 1 else ""
            note = parts[2] if len(parts) > 2 else ""
            rows = [Paragraph(rich(src), ST["cmt_src"]),
                    Paragraph(rich(body),
                              ST["cmt_star"] if star else ST["cmt_body"])]
            if note:
                rows.append(Paragraph(rich(note), ST["cmt_note"]))
            return card(rows, w, CMT_BG, SEAL, 3 if star else 2.5,
                        10 if star else 8, box=star)
        if p.startswith("@@LEAD "):
            return card([Paragraph("核 心 观 点", ST["lead_label"]),
                         Paragraph(rich(p[7:].strip()), ST["lead"])],
                        w, LEAD_BG, SEAL, 3, 9)
        if p.startswith("@@GEM "):
            return card([Paragraph("本册精选 · 精髓评论", ST["gem_label"]),
                         Paragraph(rich(p[6:].strip()), ST["gem"])],
                        w, GEM_BG, SEAL, 2.5, 11, rules=True)
        if p.startswith("@@PIC "):
            body = "<br/>".join(rich(seg) for seg in p[6:].strip().split("／"))
            return card([Paragraph("图 版 文 字 · 照 录", ST["pic_label"]),
                         Paragraph(body, ST["pic"])],
                        w, PIC_BG, LGRAY, 1, 9, rules=True)
        if p.startswith("@@QUOTE "):
            return card([Paragraph(rich(p[8:].strip()), ST["quote"])],
                        w, QUOTE_BG, GRAY, 2, 7)
        return None

    def flat(flows):
        """把 KeepTogether 展开成扁平列表：reportlab 的 KeepTogether 不支持嵌套。"""
        out = []
        for f in flows:
            if isinstance(f, KeepTogether):
                out.extend(flat(f._content))
            else:
                out.append(f)
        return out

    def by_para(p):
        return Paragraph(rich("— " + p[5:].strip()), ST["byline"])

    def contact_flow(width):
        """`@@CONTACT` → 二维码矩阵联系页。

        品牌资源由 --assets 指定，目录里的 brand.json 配文案与三张二维码；
        缺资源时给出可见的占位提示，绝不静默丢页。整块 KeepTogether，不跨页。
        """
        bdir = assets or ASSET_DIR or ""
        cfg_path = os.path.join(bdir, "brand.json")
        if not os.path.exists(cfg_path):
            return [Paragraph("〔品牌资源缺失：%s〕" % esc(cfg_path), ST["cap"])]
        try:
            cfg = json.load(open(cfg_path, encoding="utf-8"))
        except Exception as e:
            return [Paragraph("〔brand.json 解析失败：%s〕" % esc(str(e)), ST["cap"])]

        hei = "Hei" if preset == "xhs" else "Song"

        def cs(name, **kw):
            base = dict(parent=ST["body"], fontName=hei, firstLineIndent=0,
                        wordWrap="CJK", alignment=TA_CENTER, textColor=INK,
                        spaceBefore=0, spaceAfter=0)
            base.update(kw)
            return ParagraphStyle(name, **base)

        s_title = cs("ct_title", fontSize=13.5, leading=20, textColor=SEAL,
                     spaceAfter=7)
        s_body = cs("ct_body", fontSize=9.4, leading=15.4,
                    alignment=TA_JUSTIFY, spaceAfter=4)
        s_label = cs("ct_label", fontSize=9, leading=13, spaceBefore=5)
        s_hint = cs("ct_hint", fontSize=7.6, leading=11, textColor=GRAY)
        s_brand = cs("ct_brand", fontSize=9, leading=14, textColor=SEAL,
                     spaceAfter=3)
        s_foot = cs("ct_foot", fontSize=7.6, leading=12, textColor=GRAY,
                    spaceBefore=4)

        out = [Paragraph(esc(cfg.get("title", "")), s_title)]
        if cfg.get("intro"):
            out.append(Paragraph(esc(cfg["intro"]), s_body))
        for para in cfg.get("paragraphs", []):
            out.append(Paragraph(esc(para), s_body))

        qrs = (cfg.get("qr") or [])[:3]
        imgs, labels, hints = [], [], []
        cellw = (width - 16) / 3.0
        qsize = min(cellw - 2, 104)
        for q in qrs:
            fp = os.path.join(bdir, q.get("file", ""))
            if os.path.exists(fp):
                im = Image(fp, width=qsize, height=qsize)
                im.hAlign = "CENTER"
                imgs.append(im)
            else:
                imgs.append(Paragraph("〔二维码缺失〕", s_hint))
            labels.append(Paragraph(esc(q.get("label", "")), s_label))
            hints.append(Paragraph(esc(q.get("hint", "")), s_hint))
        if imgs:
            t = Table([imgs, labels, hints], colWidths=[cellw] * len(imgs))
            t.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LINEABOVE", (0, 0), (-1, 0), 0.6, HEAD_RULE),
                ("LINEBELOW", (0, -1), (-1, -1), 0.6, HEAD_RULE),
            ]))
            out.append(Spacer(1, 6))
            out.append(t)
        bl = cfg.get("brand_line") or []
        if isinstance(bl, str):
            bl = [bl]
        if bl:
            out.append(Spacer(1, 9))
            for line in bl:
                out.append(Paragraph(esc(line), s_brand))
        if cfg.get("footer"):
            out.append(Paragraph(esc(cfg["footer"]), s_foot))
        return out

    def block(p):
        """结构化书稿标记 → Flowable 列表；无标记则按正文段落排。"""
        w = RIGHT - LEFT
        c = card_flow(p)
        if c is not None:
            if p.startswith("@@LEAD "):
                before, after = 7, 8
            elif p.startswith("@@GEM "):
                before, after = 9, 10
            elif p.startswith("@@STAR "):
                before, after = 9, 11
            elif p.startswith("@@CMT "):
                before, after = 0, 8
            else:
                before, after = 0, 6
            out = [Spacer(1, before)] if before else []
            return out + [KeepTogether([c]), Spacer(1, after)]
        if p.startswith("@@NOTE "):
            return [Paragraph(rich("编者注｜" + p[7:].strip()), ST["note"])]
        if p.startswith("@@H2 "):
            return [Spacer(1, 5), Paragraph(rich(p[5:].strip()), ST["h2"])]
        if p.startswith("@@BY "):
            return [by_para(p)]
        if p.startswith("@@KEY "):
            # 金句自带出处：`@@KEY 原句｜昵称`。署名独立右对齐成行，
            # 与金句绑成一组，既不被拆行也不会落到下一页。
            spec = p[6:].strip()
            main, sep, by = spec.partition("｜")
            if sep and by.strip():
                tight = ParagraphStyle("key_tight", parent=ST["key"], spaceAfter=1)
                return [KeepTogether([Paragraph(rich(main.strip()), tight),
                                      Paragraph("—— " + esc(by.strip()),
                                                ST["key_by"])])]
            return [Paragraph(rich(spec), ST["key"])]
        if p.startswith("@@POINT "):
            return [Paragraph(rich("· " + p[8:].strip()), ST["point"])]
        if p.startswith("@@CAP "):
            return [Paragraph(rich(p[6:].strip()), ST["cap"])]
        if p == "@@RULE":
            return rule(w)
        if p == "@@PAGE":
            return [PageBreak()]
        if p.startswith("@@CONTACT"):
            # 固定尾页：二维码矩阵 + 说明。分隔线与正文一起绑定，整块不跨页。
            return [KeepTogether(rule(w, SEAL, 6) + contact_flow(w)), Spacer(1, 8)]
        if p.startswith("@@IMG "):
            spec = p[6:].strip()
            img_path, sep, cap = spec.partition(" | ")
            img_path = img_path.strip()
            if os.path.exists(img_path):
                im = Image(img_path)
                iw, ih = im.imageWidth, im.imageHeight
                scale = min(w / iw, (262.0 if preset == "xhs" else 340.0) / ih)
                im.drawWidth, im.drawHeight = iw * scale, ih * scale
                im.hAlign = "CENTER"
                grp = [im]
                if cap.strip():
                    grp += [Spacer(1, 5), Paragraph(rich(cap.strip()), cap_style)]
                return [Spacer(1, 8), KeepTogether(grp), Spacer(1, 8)]
            return [Paragraph(rich("〔插图缺失：%s〕" % img_path), cap_style)]
        return [Paragraph(rich(p), ST["body"])]

    def render_structured(paras):
        """署名行与紧随其后的引用／特写绑成一组，不许被分页拆开。"""
        out, i, n = [], 0, len(paras)
        while i < n:
            p = paras[i]
            nxt = paras[i + 1] if i + 1 < n else ""
            if p.startswith("@@BY ") and nxt.startswith(("@@QUOTE ", "@@GEM ")):
                gem = nxt.startswith("@@GEM ")
                if gem:
                    out.append(Spacer(1, 10))
                out.append(KeepTogether([by_para(p), card_flow(nxt)]))
                out.append(Spacer(1, 12 if gem else 7))
                i += 2
                continue
            if p.startswith("@@H2 ") and nxt.startswith(("@@CMT ", "@@STAR ")):
                # 小节标题不许孤零零留在页尾：与紧随的第一张评论卡同页
                grp = flat(block(p)) + [card_flow(nxt)]
                out.append(KeepTogether(grp))
                out.append(Spacer(1, 8))
                i += 2
                continue
            out.extend(block(p))
            i += 1
        return out

    for tc_, paras in toc_chapters:
        t = clean_chapter_title(tc_)
        head = None
        if t:
            head = ChapterHead(rich(t), ST["chapter"])
            if preset == "xhs":
                head.accent = SEAL
        if not poetry:
            items = render_structured(paras)
            # 章标题与紧随其后的第一个板块绑成一组，避免标题孤零零留在页尾
            if head is not None and items:
                k = 0
                while k < len(items) and isinstance(items[k], Spacer):
                    k += 1
                if k < len(items):
                    story.append(KeepTogether(flat([head] + items[:k + 1])))
                    items = items[k + 1:]
                else:
                    story.append(head)
            elif head is not None:
                story.append(head)
            story.extend(items)
        else:
            if head is not None:
                story.append(head)
            n = len(paras)
            for i, p in enumerate(paras):
                if p.startswith("@@"):
                    story.extend(block(p))
                    continue
                # 短行（诗句）居中；长段（散文/合并连排）两端对齐
                story.append(Paragraph(rich(p),
                             ST["body_poem"] if _is_verse(p) else ST["body"]))
                nxt = paras[i + 1] if i + 1 < n else None
                if _is_poem_title(p) or (nxt and _is_poem_title(nxt)):
                    story.append(Spacer(1, 10))
                elif _ends_sentence(p) and (nxt is None or _is_verse(nxt)):
                    story.append(Spacer(1, 9))
                else:
                    story.append(Spacer(1, 2))
        story.append(Spacer(1, 6))

    story += [NextPageTemplate("back"), PageBreak(),
              BackCover(title, author, intro, assets, brand, theme)]
    doc.multiBuild(story)
    return True


def _page_count(pdf):
    try:
        import fitz
        d = fitz.open(pdf)
        n = d.page_count
        d.close()
        return n
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser(
        description="把 txt/docx/epub/html/md 排成带封面、目录、书签、封底的 PDF 电子书")
    ap.add_argument("--in", dest="src", help="源文件（docx/epub/html/md/txt），自动提取文本")
    ap.add_argument("--txt", help="已提取好的纯文本（与 --in 二选一）")
    ap.add_argument("--title", required=True)
    ap.add_argument("--author", default="佚 名")
    ap.add_argument("--intro", default="")
    ap.add_argument("--poetry", type=int, default=0,
                    help="1=诗集/韵文（短行居中），0=散文/小说（两端对齐）")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--assets", default=None, help="品牌素材目录（二维码/头像），仅品牌模式使用")
    ap.add_argument("--brand", default=os.environ.get("BOOK_BRAND", ""),
                    help="品牌名（藏书印/品牌段/联系图）；留空=通用版，不含任何品牌与二维码")
    ap.add_argument("--preset", default="classic",
                    choices=["classic", "modern", "xhs"],
                    help="版式：classic=古籍整理版（默认）；modern=当代内容摘录版；"
                         "xhs=小红书风格（白底珊瑚红、黑体正文、字号更小、密度更高）")
    ap.add_argument("--page", default="A5", choices=["A5", "A4"])
    ap.add_argument("--size", type=float, default=None,
                    help="正文字号；留空按版式取默认（classic/modern 11.5，xhs 10.4）")
    ap.add_argument("--lead", type=float, default=None,
                    help="行距；留空按版式取默认（classic/modern 21.5，xhs 17.6）")
    ap.add_argument("--font-dir", default=None, help="字体目录，缺省按系统自动探测")
    ap.add_argument("--no-fix", action="store_true", help="跳过非 BMP 文本层修复（不建议）")
    a = ap.parse_args()

    if "Song" not in FONT_PATH:
        sys.exit("[FATAL] 未在 %s 找到中文字体（simsun/simhei/simkai/simfang）。\n"
                 "        用 --font-dir 指定字体目录，或先安装中文字体。"
                 % "、".join(FONT_DIRS))

    src = a.src or a.txt
    if not src:
        ap.error("必须指定 --in 或 --txt")
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)

    if a.src:                                  # ① 自动提取（docx/epub/html/md/txt）
        import extract_text
        raw = extract_text.extract(a.src)
    else:
        raw = open(a.txt, encoding="utf-8", errors="ignore").read()

    chapters, merged = parse_text(raw)         # ② 排版生成
    out = a.out or (os.path.splitext(src)[0] + ".pdf")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    # 字号默认值随版式走：xhs 更小更紧，其余保持原有设定
    if a.size is None:
        a.size = 10.4 if a.preset == "xhs" else 11.5
    if a.lead is None:
        a.lead = 17.6 if a.preset == "xhs" else 21.5
    apply_palette("xhs" if a.preset == "xhs" else "classic")
    assemble(chapters, out, a.title, a.author, a.intro or ("《%s》整理本。" % a.title),
             poetry=bool(a.poetry), assets=a.assets, size=a.size, lead=a.lead,
             page=A5 if a.page == "A5" else A4, brand=a.brand, theme=THEMES[a.preset],
             preset=a.preset)
    npar = sum(len(ps) for _, ps in chapters)
    # 用分辑兜底后的结果统计，保证「N章」与 PDF 目录条目数一致
    nch = sum(1 for t, _ in make_toc_chapters(chapters, a.title) if t)

    # ③ 文本层修复（非 BMP 字符 ToUnicode），默认开启
    fix = "未执行"
    if not a.no_fix:
        try:
            import fix_tounicode
            n = fix_tounicode.fix_pdf(out, dry_run=True)
            if n == 0:
                fix = "无需修复"
            else:
                tmp = out + ".fixing"
                fix_tounicode.fix_pdf(out, tmp)
                ok, _info = fix_tounicode.verify_open(tmp)
                if ok:
                    os.replace(tmp, out)
                    fix = "修正%d处" % n
                else:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    fix = "修复失败(保留原文件)"
        except BaseException as e:
            fix = "跳过(%s)" % e

    print("[OK] %s | %d章 | %d段 | 合并=%s | %d页 | 文本层=%s | %dKB"
          % (out, nch, npar, "是" if merged else "否", _page_count(out), fix,
             os.path.getsize(out) // 1024))


if __name__ == "__main__":
    main()
