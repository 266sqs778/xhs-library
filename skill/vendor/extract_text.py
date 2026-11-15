# -*- coding: utf-8 -*-
"""文档 → 纯文本 提取器（仅用标准库，零依赖）。
用途：把 txt / md / docx / epub / html / pdf 归一化为"每段一行、空行分段"的纯文本，
      供 book_pdf.py 排版。

用法:
  python extract_text.py <输入文件> [-o 输出.txt]

格式要点:
  docx  : zip 解包 word/document.xml，<w:p> 为段落，<w:t>/<w:tab> 为文本
  epub  : zip 解包，读 META-INF/container.xml → .opf → spine 顺序 → 各 xhtml 正文
  html  : 去 script/style/注释，块级标签补换行
  pdf   : 需 PyMuPDF(fitz)，可选；无则报错提示先转 txt
"""
import os, re, sys, zipfile
import xml.etree.ElementTree as ET


# ---------------- 通用清洗 ----------------
def html_to_text(raw):
    """HTML/XHTML → 纯文本（块级标签补换行，保留源文的空行分段结构）"""
    raw = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", "", raw)
    raw = re.sub(r"(?s)<!--.*?-->", "", raw)
    # 块级/换行标签 → 换行
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|blockquote|section|article)>", "\n", raw)
    raw = re.sub(r"(?i)<(p|div|tr|li|h[1-6]|blockquote|section|article)[^>]*>", "\n", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    for a, b in [("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"),
                 ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"),
                 ("&ldquo;", "“"), ("&rdquo;", "”"), ("&hellip;", "…"),
                 ("&mdash;", "—")]:
        raw = raw.replace(a, b)
    raw = raw.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    # 折叠 3+ 空行为 2 行，去行尾空白（保留空行=分段信号）
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    raw = "\n".join(l.rstrip() for l in raw.split("\n"))
    return raw.strip() + "\n"


# ---------------- docx ----------------
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    out = []
    body = root.find(f"{_W_NS}body")
    if body is None:
        body = root
    for p in body.iter(f"{_W_NS}p"):
        buf = []
        for node in p.iter():
            tag = node.tag
            if tag == f"{_W_NS}t":
                buf.append(node.text or "")
            elif tag == f"{_W_NS}tab":
                buf.append("\t")
            elif tag in (f"{_W_NS}br",):
                buf.append("\n")
        line = "".join(buf).strip()
        out.append(line)
    return "\n".join(out).strip() + "\n"


# ---------------- epub ----------------
def _opf_path(z):
    try:
        c = z.read("META-INF/container.xml").decode("utf-8", "ignore")
        m = re.search(r'full-path="([^"]+)"', c)
        if m:
            return m.group(1)
    except KeyError:
        pass
    for n in z.namelist():
        if n.lower().endswith(".opf"):
            return n
    return None


# 壳文件命名（calibre 等工具惯例）：目录/封面/版权页，均不入正文
_SHELL_NAME_RE = re.compile(
    r"(?i)(^|[^a-z])(toc|nav|cover|titlepage|title_page|notices?|copyright|colophon)([^a-z]|$)")
# 裸章节标题行（目录页特征）："第一回" / "卷三" / "十二" 等，无正文
_BARE_HEAD_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百千零〇\d]+[篇卷章回部]|卷[之]?[一二三四五六七八九十百千零〇\d]+|[一二三四五六七八九十百千零〇\d]{1,4})$")


def _looks_like_toc_chunk(text):
    """目录页启发式：文本短且过半是非空行都是裸章节标题行（≥3 行）。
    真正的章节页是散文正文，不会命中；单行"卷一"分辑页因 ≥3 行下限而不会误删。"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines or len(text) > 2000:
        return False
    hits = sum(1 for l in lines if _BARE_HEAD_RE.match(l))
    return hits >= 3 and hits >= len(lines) * 0.5


def epub_to_text(path):
    with zipfile.ZipFile(path) as z:
        opf = _opf_path(z)
        if not opf:
            raise RuntimeError("epub 内找不到 .opf")
        base = os.path.dirname(opf)
        ox = z.read(opf).decode("utf-8", "ignore")
        # manifest：id -> (href, properties)，记录 nav 文档与壳文件
        manifest = {}
        for m in re.finditer(r"<item[^>]+>", ox):
            tag = m.group(0)
            mid = re.search(r'id="([^"]+)"', tag)
            mhref = re.search(r'href="([^"]+)"', tag)
            mprop = re.search(r'properties="([^"]*)"', tag)
            if mid and mhref:
                manifest[mid.group(1)] = (mhref.group(1), mprop.group(1) if mprop else "")
        spine = re.findall(r'<itemref[^>]*idref="([^"]+)"', ox)
        names = [manifest[i][0] for i in spine if i in manifest]
        nav_hrefs = {manifest[i][0] for i in manifest
                     if "nav" in manifest[i][1].split()}
        if not names:                      # 退化：按文件名顺序取所有 xhtml/html
            names = [n for n in z.namelist()
                     if n.lower().endswith((".xhtml", ".html", ".htm"))]
            names.sort()
        chunks = []
        for n in names:
            short = os.path.basename(n)
            fp = n if not base else f"{base}/{n}"
            fp = fp.replace("//", "/")
            if fp not in z.namelist():
                cand = [x for x in z.namelist() if x.endswith(os.path.basename(n))]
                if not cand:
                    continue
                fp = cand[0]
            # 跳过 nav 文档与目录/封面/版权壳文件
            if n in nav_hrefs or _SHELL_NAME_RE.search(short):
                continue
            try:
                txt = html_to_text(z.read(fp).decode("utf-8", "ignore"))
            except Exception:
                continue
            # 内容兜底：裸目录页不进正文
            if _looks_like_toc_chunk(txt):
                continue
            chunks.append(txt)
    return "\n\n".join(chunks).strip() + "\n"


# ---------------- pdf（可选） ----------------
def pdf_to_text(path):
    try:
        import fitz
    except ImportError:
        raise RuntimeError("提取 PDF 需 PyMuPDF：pip install pymupdf（venv 内）")
    doc = fitz.open(path)
    out = []
    for pg in doc:
        out.append(pg.get_text())
    doc.close()
    return "\n".join(out)


def extract(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md", ".markdown", ".text"):
        for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
            try:
                return open(path, encoding=enc).read()
            except Exception:
                continue
        return open(path, encoding="utf-8", errors="ignore").read()
    if ext == ".docx":
        return docx_to_text(path)
    if ext == ".epub":
        return epub_to_text(path)
    if ext in (".html", ".htm", ".xhtml", ".xml"):
        return html_to_text(open(path, encoding="utf-8", errors="ignore").read())
    if ext == ".pdf":
        return pdf_to_text(path)
    raise RuntimeError("不支持的格式: %s" % ext)


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    src = sys.argv[1]
    out = None
    if "-o" in sys.argv:
        out = sys.argv[sys.argv.index("-o") + 1]
    txt = extract(src)
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        open(out, "w", encoding="utf-8").write(txt)
        print("[OK] %s -> %s (%d字)" % (src, out, len(txt)))
    else:
        sys.stdout.write(txt)


if __name__ == "__main__":
    main()
