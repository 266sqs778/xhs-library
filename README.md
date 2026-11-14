# xhs-library · 小红书书架

把刷到的小红书帖子做成一本本可读的 PDF 精华小书，并归档成一座私人书架。

- **skill/**：全流程工具（采集 → 读图 → 精选 → 成稿 → 排版 → 验收 → 归档），详见 [skill/README.md](skill/README.md)
- **books/**：生成的书，每本一个文件夹（`日期_书名_作者`，全套归档）——**只在本地，不进 git**
- **INDEX.md**：书架总目录，每本书一行——**只在本地，不进 git**（模板见 [INDEX.template.md](INDEX.template.md)）

## 快速开始

```bash
python -m pip install reportlab pymupdf fonttools

# 初始化书架
python skill/scripts/shelf.py init

# 采集一条笔记
python skill/scripts/collect_note.py "https://www.xiaohongshu.com/discovery/item/xxxx" -o note/

# 按 skill/FORMAT.md 写书稿 note/book_source.txt，然后排版 + 验收
python skill/scripts/build_book.py --source note/book_source.txt --title "书名" \
  --author "原作者" --intro "简介" -o note/书名.pdf
python skill/scripts/verify_book.py --pdf note/书名.pdf --source note/book_source.txt \
  --data note/note_data.json --render note/样张

# 归档进书架
python skill/scripts/shelf.py archive note/ --title "书名" --author "原作者" \
  --note-id "<笔记链接或ID>" --tags "标签" --brief "一句话简介" \
  --pdf 书名.pdf --source book_source.txt --data note_data.json
```

书架默认根目录：`C:\Users\无相道一\WorkBuddy\xhs-library\`（`--root` 可改）。

## 版权口径

本仓库只开源工具代码。`books/` 与 `INDEX.md` 里的书稿内容（他人正文、图片、评论）
著作权归原作者及评论作者所有，仅供个人阅读存档，请勿传播或商用，因此不随本仓库公开。
