---
name: xhs-essence-book
description: 把小红书帖子（图文、正文、作者回复、评论区高含金量内容、图片里的文字）采集、精选、汇编成一本可读的精华小书 PDF。当用户提供小红书笔记链接/分享文案/xhslink 短链，说「做成小书」「摘录成册」「整理成精华册」「把这条帖子做成 PDF」「评论区也收进去」时使用。支持多篇同主题合集、小红书风格排版、逐字照录与图版文字转录。
version: 1.1.0
---

# 小红书精华小书

一条链接进，一本小书出：**采集 → 读图 → 精选 → 成稿 → 排版 → 验收 → 归档**。
本技能自带采集器、排版引擎、验收脚本与书架归档管理，不依赖第三方付费接口、不需要登录。

## 何时用

- 用户丢来小红书笔记链接 / 分享文案 / `xhslink.com` 短链，想把内容留成册子；
- 用户想把刷到的若干篇同主题帖子汇成一本合集；
- 用户强调「评论区也要」「图里的字也要」「要像小红书那样排版」。

## 依赖

- Python 3.9+，需要 `reportlab`、`pymupdf`、`fonttools`（排版与验收）；
- 中文字体：宋体 / 黑体 / 楷体 / 仿宋（Windows 自带；macOS、Linux 需自行安装或用 `--font-dir` 指定）；
- `curl`（采集）；
- 排版引擎：优先用已安装的 `ebook-pdf-maker` 技能（需含 `--preset xhs` 的版本）；
  也可把 `book_pdf.py` 放进本目录 `vendor/`，或用环境变量 `XHS_BOOK_ENGINE` 指定。

先跑一次环境自检：

```bash
python scripts/build_book.py --help          # 缺依赖会直接报出来
python -c "import reportlab, pymupdf; print('ok')"
```

## 七步流程

### 1 采集

```bash
python scripts/collect_note.py "<笔记链接>" -o note/
```

产物：`note/note_data.json`（正文、作者、互动数、发布时间、话题标签、首屏评论及其附图）、
`note/comments.md`（评论人读版，带赞数、回复关系、附图文件名）、`note/images/`（原帖图与评论图，文件名标明归属）。

要点：
- 移动端 SSR 页面才带数据，桌面 UA 拿到的是空壳；脚本已固定用 iPhone UA。
- 只可见首屏评论（通常 5 条一级评论 + 部分回复），**不是全量**，成书时必须写明可见范围。
- 短链会自动跟随跳转；若被风控，让用户用手机浏览器另存页面，再用 `--html 页面文件` 解析。

### 2 读图（最容易漏的一步）

**逐张看图片**，不要只看文件名。分三类处理：

| 图片类型 | 处理 |
|---|---|
| 标题卡、观点卡、图表、时间线、手写笔记 | 收进书里，并把**图中文字逐字转录**（`@@PIC`） |
| 与主题无关的推广截图、带第三方水印的付费长图 | **不收、不转录**，在数据章写明「几张、为何不收」 |
| 头像、缩略图、平台 UI 截图 | 忽略 |

转录规矩：按图片原断行（`@@PIC` 里用 `／` 分隔），装饰元素（引号、色块、水印）不转录，但要在紧随的 `@@NOTE` 里说明「哪些没算文字」；评论区的附图必须写清是谁的回复、图片尺寸。

### 3 精选

- **原文**：全文照录，只重排分段；关键句 `==…==` 高亮，最锋利的半句 `**…**` 加粗。
- **核心观点**：每章一条 `@@LEAD`，一句话结论；章内 `@@POINT` 分层拆解。
- **作者的话**：作者在评论区的回复单独成块（`@@BY 昵称｜作者本人回复` + `@@QUOTE`），往往比正文更克制。
- **评论区**：按三条标准选，每条都要能说出理由——能否延伸原文框架、能否校正原文、能否照见读者处境。
- **精髓评论**：全书只抬 1–2 条为 `@@GEM`，且必须在紧随的 `@@NOTE` 里写清「为什么是它」。
- 未选入的高赞也要交代取舍理由，一段 `@@NOTE` 即可。

### 4 成稿

按 `FORMAT.md` 写纯 TXT，`templates/book_source_template.txt` 是可复制的骨架。
**照录不改字**：不润色、不缩写、不改标点、不补句末标点；允许的归一化只有三项（略去表情代码与表情符号、合并换行、统一引号样式），且必须在章节说明里逐项写明。

### 5 排版

```bash
python scripts/build_book.py --source note/book_source.txt \
  --title "书名" --author "原作者昵称" \
  --intro "一句话说明收了什么、仅供个人存档" -o note/书名.pdf
```

默认 `--preset xhs`（小红书风格：白底、珊瑚红、黑体正文 10.4/17.6、版心更宽）。
也可 `--preset modern`（宣纸底宋体）或 `classic`（仅限公版古籍，**当代内容禁用**）。

### 6 验收

```bash
python scripts/verify_book.py --pdf note/书名.pdf --source note/book_source.txt \
  --data note/note_data.json --render note/抽样页
```

必须全 PASS：无 `@@`/`**`/`==` 残留、无行首中文标点、引文与采集原文逐字一致、图版文字已落页、无「公版古籍」错误文案、目录书签齐全。
最后用 `ViewImage` 看 2–3 张抽样页，确认板块层级、卡片不跨页、插图不裁切。

### 7 归档（成书后必做）

```bash
# 查重：这条笔记是否已经做过书
python scripts/shelf.py check "<笔记链接或ID>"
# 归档：自动收 PDF、书稿、采集数据、图片、验收报告进书架，并更新 INDEX.md
python scripts/shelf.py archive <成书工作目录> --title "书名" --author "原作者" \
  --note-id "<笔记链接或ID>" --tags "标签,逗号分隔" --brief "一句话简介" \
  --pdf 成品.pdf --source book_source.txt --data note_data.json --verify 验收日志
python scripts/shelf.py list      # 查看书架
```

书架根目录默认 `C:\Users\无相道一\WorkBuddy\xhs-library\`（`--root` 可改）：

```
xhs-library/
├── INDEX.md      总目录：每本书一行（日期｜书名｜原作者｜标签｜笔记ID｜简介｜位置）
├── skill/        本技能包
└── books/        每本书一个文件夹：日期_书名_作者，全套归档
    └── 2026-11-14_xxx/
        ├── 书名.pdf、book_source.txt、note_data.json、comments.md
        ├── images/、样张/、verify_report.txt、note.meta.md（归档卡片）
```

- 同一笔记再次 archive 会被拦下并提示旧档位置；要重制加 `--v2`（旧版保留，新目录带 _v2）。
- **`books/` 与 `INDEX.md` 只在本地，不随 git 公开**——书的内容含他人原创，公开仓库只放 skill 工具本身。

## 书稿标记速查

`@@LEAD` 核心观点卡 · `@@H2` 小节 · `@@KEY` 金句 · `@@POINT` 分点 · `@@NOTE` 编者注（自动加「编者注｜」）·
`@@BY` 评论署名 · `@@QUOTE` 引用块 · `@@GEM` 精髓特写 · `@@IMG 路径 | 图注` 插图 · `@@PIC 图里的文字` 图版文字 ·
`@@CAP` 小字 · `@@RULE` 分隔线 · `@@PAGE` 分页；行内 `**重点**`（珊瑚红加粗）、`==重点==`（淡黄高亮）。

## 硬规则

1. **三种身份不混**：原文照录 / 他人评论 / 编者文字，样式与板块永不串用。
2. **引文逐字**：评论与金句必须能在 `note_data.json` 里逐字命中，标点也不许改。
3. **图片要有交代**：收了的图给图注与图版文字；没收的图说明原因与数量。
4. **署名三要素**：谁说的、多少赞、什么关系（一级评论 / 回复谁 / 作者本人）。
5. **版权口径**：当代内容一律 `xhs` 或 `modern`；书写明「著作权归原作者及评论作者所有，仅供个人阅读存档，请勿传播或商用」。
6. **不编数据**：拿不到的发布时间、互动数、图片一律留白并说明，不推测、不补写。
7. **每本书必须归档**：验收通过后 `shelf.py archive` 进书架并更新 INDEX.md；`books/` 与 `INDEX.md` 不进 git。
8. **查重在先**：动手成书前先 `shelf.py check`，已归档的提示旧档位置，重制才用 `--v2`。

## 目录

```
xhs-essence-book/
├── SKILL.md                      本文件
├── FORMAT.md                     书稿格式语言（标记、组合规则、SOP、验收清单）
├── README.md                     安装与仓库说明
├── templates/book_source_template.txt
├── scripts/collect_note.py       采集（SSR 解析 + 图片落地 + 评论导出）
├── scripts/build_book.py         排版（默认 --preset xhs）
├── scripts/verify_book.py        验收（残留、引文、标点、版权、抽样页）
└── scripts/shelf.py              书架归档（init/archive/list/check）
```
