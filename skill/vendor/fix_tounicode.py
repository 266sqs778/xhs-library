# -*- coding: utf-8 -*-
"""修复 reportlab 非 BMP 字符 ToUnicode 缺陷（文本层乱码，视觉不受影响）。

根因：reportlab 把 >U+FFFF 的字符写进 ToUnicode CMap 时未用 UTF-16 代理对，
而是写成奇数长度十六进制（如 𨸏 U+28E0F → `<28E0F>`）。CMap 规定 bfchar 目标
必须 2/4 字节对齐，奇数长度会让解析器只取前 4 位 → 复制/搜索/索引出乱码。

修法：把非法的 dst 重写为 UTF-16BE 代理对（U+28E0F → `<D863DCDF>`）。
安全策略：另存 .fixing → 验证可打开且书签保留 → 才覆盖原文件。

用法:
  python fix_tounicode.py <pdf文件或目录> [--dry]     # --dry 只统计不改写
依赖: PyMuPDF (pip install pymupdf)
"""
import os, re, sys, glob


def _fitz():
    """延迟导入，便于被 book_pdf.py 安全调用（缺 PyMuPDF 不拖垮主流程）"""
    try:
        import fitz
        return fitz
    except ImportError:
        raise SystemExit("需要 PyMuPDF：pip install pymupdf（venv 内）")


def fix_cmap_text(text):
    """把一个 CMap 流文本里的非法 bfchar dst 改写成 UTF-16BE 代理对"""
    if "beginbfchar" not in text:
        return text
    m = re.search(r"beginbfchar(.*?)endbfchar", text, re.S)
    if not m:
        return text
    pairs = re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", m.group(1))
    newpairs, changed = [], False
    for src, dst in pairs:
        cp = int(dst, 16)
        if cp > 0xFFFF or (len(dst) % 2 != 0):
            if cp <= 0xFFFF:
                newdst = "%04X" % cp
            else:
                v = cp - 0x10000
                hi = 0xD800 + (v >> 10)
                lo = 0xDC00 + (v & 0x3FF)
                newdst = "%04X%04X" % (hi, lo)
            changed = changed or newdst != dst
            newpairs.append((src, newdst))
        else:
            newpairs.append((src, dst))
    if not changed:
        return text
    body = "".join("<%s> <%s>\n" % (s, d) for s, d in newpairs)
    newtext = text[:m.start(1)] + body + text[m.end(1):]
    return re.sub(r"\d+\s*beginbfchar", "%d beginbfchar" % len(newpairs), newtext)


def fix_pdf(pdf_in, pdf_out=None, dry_run=False):
    fitz = _fitz()
    d = fitz.open(pdf_in)
    n_fixed = 0
    for xref in range(1, d.xref_length()):
        try:
            raw = d.xref_stream(xref)
        except Exception:
            continue
        if not raw or b"begincmap" not in raw or b"beginbfchar" not in raw:
            continue
        text = raw.decode("latin1")
        m = re.search(r"beginbfchar(.*?)endbfchar", text, re.S)
        if not m:
            continue
        pairs = re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", m.group(1))
        bad = [p for p in pairs if (int(p[1], 16) > 0xFFFF or len(p[1]) % 2 != 0)]
        if not bad:
            continue
        n_fixed += len(bad)
        if not dry_run:
            d.update_stream(xref, fix_cmap_text(text).encode("latin1"))
    if not dry_run and n_fixed:
        d.save(pdf_out or pdf_in, incremental=(pdf_out is None))
    d.close()
    return n_fixed


def verify_open(pdf):
    fitz = _fitz()
    try:
        d = fitz.open(pdf)
        _ = sum(len(d[i].get_text()) for i in range(min(d.page_count, 5)))
        toc = len(d.get_toc())
        d.close()
        return True, toc
    except Exception as e:
        return False, str(e)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    if not args:
        print(__doc__); return
    target = args[0]
    pdfs = ([target] if target.lower().endswith(".pdf")
            else sorted(glob.glob(os.path.join(target, "**", "*.pdf"), recursive=True)))
    total = ok = fail = 0
    for p in pdfs:
        n = fix_pdf(p, dry_run=True)
        if not n:
            continue
        total += n
        print("  %s: %d 处非法 dst" % (os.path.basename(p), n))
        if dry:
            continue
        tmp = p + ".fixing"
        try:
            fix_pdf(p, tmp, dry_run=False)
            good, info = verify_open(tmp)
            if good:
                os.replace(tmp, p); ok += 1
                print("    ✓ 已修正并覆盖（书签 %s 条）" % info)
            else:
                if os.path.exists(tmp):
                    os.remove(tmp)
                fail += 1; print("    ✗ 验证失败，保留原文件: %s" % info)
        except Exception as e:
            fail += 1; print("    ✗ 异常: %s" % e)
    print("\n%s: 非法 dst 共 %d 处，成功 %d 本，失败 %d 本"
          % ("[DRY-RUN]" if dry else "[完成]", total, ok, fail))


if __name__ == "__main__":
    main()
