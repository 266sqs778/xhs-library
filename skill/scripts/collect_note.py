# -*- coding: utf-8 -*-
"""采集小红书笔记：公开分享页 → note_data.json + images/ + comments.md

不依赖第三方接口，也不需要登录：用 iPhone UA 抓移动端 SSR 页面，
页面里的 window.__INITIAL_STATE__ 就带着 note（正文/图/互动数）与 commentData（首屏评论）。

用法：
    python collect_note.py "https://www.xiaohongshu.com/discovery/item/xxxx?..." -o out/
    python collect_note.py "https://xhslink.com/xxxx" -o out/        # 短链会自动跟随跳转
    python collect_note.py --html saved.html -o out/                 # 离线解析已保存的页面

产物：
    out/note_data.json   note + commentData + meta
    out/comments.md      评论的人读版（含赞数、回复关系、附图文件名）
    out/images/          原帖图与评论图，文件名带归属
    out/page.html        原始页面（便于复查）
"""
import argparse
import datetime
import io
import json
import os
import re
import subprocess
import sys

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
NOTE_ID_RE = re.compile(r"/(?:discovery/item|explore|item)/([0-9a-fA-F]{20,32})")


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def resolve_url(url):
    """短链（xhslink.com / xhslink.cn）跟随第一跳，拿到带 note id 的正式地址。

    必须用 GET 取响应头：部分短链对 HEAD 直接返回 404。
    """
    if "xhslink." not in url:
        return url
    r = sh(["curl", "-s", "-D", "-", "-o", os.devnull,
            "--max-time", "25", "-A", UA, url])
    loc = ""
    for line in (r.stdout or "").splitlines():
        if line.lower().startswith("location:"):
            loc = line.split(":", 1)[1].strip()
            break
    return loc or url


def note_id_of(url):
    m = NOTE_ID_RE.search(url or "")
    return m.group(1) if m else ""


def fetch_page(url, outdir):
    page = os.path.join(outdir, "page.html")
    r = sh(["curl", "-sL", "--max-time", "40", "-A", UA,
            "-H", "Referer: https://www.xiaohongshu.com/",
            "-H", "Accept-Language: zh-CN,zh;q=0.9",
            url, "-o", page])
    if not os.path.exists(page) or os.path.getsize(page) < 20000:
        sys.exit("[FATAL] 页面抓取失败或过小，可能被风控。可先用浏览器另存页面，再用 --html 解析。")
    return page


def load_state(html):
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not m:
        m = re.search(r"__INITIAL_STATE__\s*=\s*(\{.*\})\s*</script>", html, re.S)
    if not m:
        sys.exit("[FATAL] 页面里没有 __INITIAL_STATE__，可能是桌面版空壳页；请用移动端 UA 重抓。")
    raw = re.sub(r"\bundefined\b", "null", m.group(1))
    return json.loads(raw)


def walk(obj, hit, path=""):
    if isinstance(obj, dict):
        if "commentData" in obj and "comments" in (obj.get("commentData") or {}):
            hit.setdefault("comments", obj["commentData"])
        if "imageList" in obj and "interactInfo" in obj and "desc" in obj:
            hit.setdefault("note", obj)
        for k, v in obj.items():
            walk(v, hit, path + "/" + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:80]):
            walk(v, hit, path + "/%d" % i)


def pick_img_url(pic):
    """优先原图，其次 stream / infoList 里的大图。"""
    if not isinstance(pic, dict):
        return ""
    for key in ("originUrl", "urlDefault", "urlPre", "url"):
        u = pic.get(key)
        if u and u.startswith("http"):
            return u
    for key in ("infoList", "stream"):
        for it in pic.get(key) or []:
            u = (it or {}).get("url") or (it or {}).get("masterUrl")
            if u and u.startswith("http"):
                return u
    return ""


def dl(url, path):
    u = url.replace("http://", "https://")
    sh(["curl", "-sL", "--max-time", "40", "-A", UA,
        "-H", "Referer: https://www.xiaohongshu.com/", u, "-o", path])
    ok = os.path.exists(path) and os.path.getsize(path) > 1024
    if not ok and os.path.exists(path):
        os.remove(path)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", help="笔记链接（支持 xhslink 短链）")
    ap.add_argument("--html", help="已保存的页面文件，离线解析")
    ap.add_argument("-o", "--out", default="note", help="输出目录")
    a = ap.parse_args()

    os.makedirs(os.path.join(a.out, "images"), exist_ok=True)

    if a.html:
        html = io.open(a.html, encoding="utf-8", errors="replace").read()
        url = a.url or ""
    else:
        if not a.url:
            ap.error("需要笔记链接，或用 --html 指定已保存页面")
        url = resolve_url(a.url)
        html = io.open(fetch_page(url, a.out), encoding="utf-8", errors="replace").read()

    state = load_state(html)
    hit = {}
    walk(state, hit)
    note, comments = hit.get("note"), hit.get("comments")
    if not note:
        sys.exit("[FATAL] 没有在页面数据里找到 note（正文/图/互动数），可能页面形态变了。")

    # 字段归一化：笔记作者是 user.nickName，评论者是 user.nickname
    u = note.get("user") or {}
    note["author"] = u.get("nickName") or u.get("nickname") or ""
    for c in (comments or {}).get("comments") or []:
        c["nickname"] = (c.get("user") or {}).get("nickname", "")
        for sc in c.get("subComments") or []:
            sc["nickname"] = (sc.get("user") or {}).get("nickname", "")

    nid = note.get("noteId") or note_id_of(url)
    data = {
        "note": note,
        "commentData": comments or {"comments": []},
        "meta": {
            "url": url,
            "noteId": nid,
            "fetchedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "noteImageCount": len(note.get("imageList") or []),
            "visibleTopComments": len((comments or {}).get("comments") or []),
        },
    }

    # ---------- 下载图片 ----------
    saved = []          # (文件名, 归属说明)
    for i, pic in enumerate(note.get("imageList") or [], 1):
        u = pick_img_url(pic)
        if not u:
            continue
        fn = "images/note_%02d.jpg" % i
        if dl(u, os.path.join(a.out, fn)):
            saved.append((fn, "原帖配图 %d" % i))

    ci = 0
    for c in (comments or {}).get("comments") or []:
        ci += 1
        for j, pic in enumerate(c.get("pictures") or [], 1):
            u = pick_img_url(pic)
            if not u:
                continue
            fn = "images/comment_%02d_%02d.jpg" % (ci, j)
            if dl(u, os.path.join(a.out, fn)):
                saved.append((fn, "评论附图：%s 的第 %d 张" % (c.get("nickname", "?"), j)))
        for sc in c.get("subComments") or []:
            for j, pic in enumerate(sc.get("pictures") or [], 1):
                u = pick_img_url(pic)
                if not u:
                    continue
                fn = "images/reply_%02d_%02d.jpg" % (ci, j)
                if dl(u, os.path.join(a.out, fn)):
                    saved.append((fn, "回复附图：%s 的第 %d 张" % (sc.get("nickname", "?"), j)))

    json.dump(data, io.open(os.path.join(a.out, "note_data.json"), "w",
                            encoding="utf-8"), ensure_ascii=False, indent=1)

    # ---------- 评论人读版 ----------
    lines = ["# 评论区原文（公开页可见部分）", ""]
    for idx, c in enumerate((comments or {}).get("comments") or [], 1):
        pics = "、".join("图片 %d" % (j + 1) for j in range(len(c.get("pictures") or [])))
        lines.append("## %d. %s｜赞 %s｜回复 %s%s"
                     % (idx, c.get("nickname", "?"), c.get("likeCount", "?"),
                        c.get("subCommentCount", 0), ("｜附图 " + pics) if pics else ""))
        lines.append("")
        lines.append(c.get("content", "").strip())
        lines.append("")
        for sc in c.get("subComments") or []:
            lines.append("- **%s**：%s" % (sc.get("nickname", "?"), sc.get("content", "").strip()))
        lines.append("")
    io.open(os.path.join(a.out, "comments.md"), "w", encoding="utf-8",
            newline="").write("\n".join(lines))

    # ---------- 摘要 ----------
    ii = note.get("interactInfo") or {}
    print("[OK] 笔记：%s" % (note.get("title") or "(无标题)"))
    print("     作者：%s｜赞 %s｜藏 %s｜评 %s｜分享 %s"
          % (note.get("author") or "?", ii.get("likedCount"),
             ii.get("collectedCount"), ii.get("commentCount"), ii.get("shareCount")))
    print("     正文 %d 字｜配图 %d 张｜可见一级评论 %d 条"
          % (len(note.get("desc") or ""), len(note.get("imageList") or []),
             len((comments or {}).get("comments") or [])))
    print("     图片落地 %d 张：" % len(saved))
    for fn, who in saved:
        print("       %-28s %s" % (fn, who))
    print("     产物：%s/note_data.json、comments.md、images/"
          % a.out.rstrip("/\\"))


if __name__ == "__main__":
    main()
