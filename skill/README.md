# 小红书精华小书 · Skill

把一条小红书帖子（图文、正文、作者回复、评论区高含金量内容、图片里的文字）编成一本可读的 PDF 小书。

- **采集**：公开分享页的移动端 SSR 数据，不登录、不调第三方付费接口
- **精选**：原文照录 + 核心观点 + 金句 + 评论区精选 + 精髓特写
- **排版**：小红书风格（白底珊瑚红、黑体正文、信息密度高），也能切宣纸宋体的书籍版式
- **验收**：残留标记、引文逐字比对、行首标点、版权口径、目录书签、抽样页

## 安装

作为 Agent Skill 使用时，把整个目录放到：

| 范围 | 路径 |
|---|---|
| 用户级（所有项目可用） | `~/.workbuddy/skills/xhs-essence-book/` |
| 项目级 | `<项目>/.workbuddy/skills/xhs-essence-book/` |

依赖：

```bash
python -m pip install reportlab pymupdf fonttools
```

中文字体需要系统里有宋体 / 黑体 / 楷体 / 仿宋（Windows 自带）。

排版引擎不随仓库分发，默认复用已安装的 `ebook-pdf-maker` 技能（需要含 `--preset xhs` 的版本）。
找不到时会依次回退到本目录 `vendor/book_pdf.py` 或环境变量 `XHS_BOOK_ENGINE` 指定的路径。

## 用法

```bash
# 1. 采集
python scripts/collect_note.py "https://www.xiaohongshu.com/discovery/item/xxxx" -o note/

# 2. 按 FORMAT.md 写书稿（参考 templates/book_source_template.txt）

# 3. 排版
python scripts/build_book.py --source note/book_source.txt --title "书名" \
  --author "原作者" --intro "内容简介" -o note/书名.pdf

# 4. 验收
python scripts/verify_book.py --pdf note/书名.pdf --source note/book_source.txt \
  --data note/note_data.json --render note/抽样页

# 5. 查重 + 归档进书架
python scripts/shelf.py check "<笔记链接或ID>"
python scripts/shelf.py archive note/ --title "书名" --author "原作者" \
  --note-id "<笔记链接或ID>" --tags "标签" --brief "一句话简介" \
  --pdf 书名.pdf --source book_source.txt --data note_data.json
```

## 书架归档体系

成书不是终点。每本验收通过的书都归档进书架（默认 `C:\Users\无相道一\WorkBuddy\xhs-library\`）：

```
xhs-library/                    整体一个包 = 一个 git 仓库
├── INDEX.md                    总目录：每本书一行（日期｜书名｜原作者｜标签｜笔记ID｜简介｜位置）
├── skill/                      本技能包（随 git 公开）
└── books/                      每本书一个文件夹（只在本地，不进 git）
    └── 2026-11-14_书名_作者/
        ├── 书名.pdf            成品
        ├── book_source.txt     书稿（含 @@ 标记的纯文本，可重排）
        ├── note_data.json      采集数据（引文逐字比对的依据）
        ├── comments.md         评论人读版
        ├── images/ 样张/       原帖图 / 成书样张
        ├── verify_report.txt   验收日志
        └── note.meta.md        归档卡片（书名、原作者、笔记ID、原帖地址、标签、版本）
```

- **命名**：`日期_书名_原作者`，自动清理 Windows 非法字符与 emoji
- **查重**：按笔记 ID；同笔记再次归档会被拦下并提示旧档位置，重制加 `--v2`（旧版保留）
- **版权**：`books/` 与 `INDEX.md` 已在 `.gitignore` 里排除——书的内容含他人原创，公开仓库只放工具本身

## 版式

| preset | 外观 | 用途 |
|---|---|---|
| `xhs`（默认） | 白底、顶部珊瑚红条、黑体正文 10.4pt/行距 17.6、珊瑚红板块、版心更宽 | 信息流摘录、图文笔记 |
| `modern` | 宣纸底、宋体、传统书籍观感 | 长篇文字摘录 |
| `classic` | 封面「国学经典 · 原文整理丛书」+ 公版声明 | **仅限公版古籍**，当代内容会造成错误版权声明 |

## 目录

```
SKILL.md                        流程与硬规则（Agent 读这个）
FORMAT.md                       书稿格式语言：标记总表、组合规则、SOP、验收清单
templates/book_source_template.txt  书稿骨架
scripts/collect_note.py         采集
scripts/build_book.py           排版
scripts/verify_book.py          验收
scripts/shelf.py                书架归档（init/archive/list/check）
```

引擎来自 [ebook-pdf-maker](../ebook-pdf-maker)，本仓库在其基础上用到并依赖这些能力：`--preset xhs`、`@@PIC` 图版文字板块、中文标点禁则、分页保护。

## 版权

本技能只做个人阅读存档用途的摘录与编排。成书必须保留原作者与评论作者署名、原帖地址，并注明「请勿传播或商用」；公开分发需取得原作者授权。
