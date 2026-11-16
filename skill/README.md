# 小红书精华小书 · Skill（v2.1）

把一条小红书帖子（图文、正文、作者回复、评论区高含金量内容、图片里的文字）编成一本**内容优先**的 PDF 小书，并归档进书架。

- **采集**：公开分享页的移动端 SSR 数据，不登录、不调第三方付费接口
- **精选**：原文照录 + 评论卡（自带来源）+ 金句（句句署名）+ 精髓特写
- **排版**：小红书风格（白底珊瑚红、黑体正文、信息密度高），v2.1 默认 `dense` 紧凑密度模式
  （9pt/13.4 行距、出版说明与目录合并、每章约 1 页），也能切宣纸宋体的书籍版式
- **联系页**：每本末尾自动一页「联系与合作」三码矩阵 + 一小段说明 + 品牌关联
- **验收**：残留标记、引文逐字比对、行首标点、版权口径、目录书签、**二维码矩阵与内容密度**、抽样页
- **归档**：`shelf.py` 按笔记 ID 查重，每本一个文件夹，`INDEX.md` 总目录

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

**排版引擎随包分发**：`vendor/book_pdf.py` 已内含 `--preset xhs`、`@@CMT/@@STAR` 评论卡、
`@@CONTACT` 联系页、中文标点禁则与分页保护，不需要额外安装 `ebook-pdf-maker`。
查找顺序：`XHS_BOOK_ENGINE` 环境变量 → 本包 `vendor/` → 已安装的 `ebook-pdf-maker`。
`build_book.py` 会校验引擎是否含 `@@CONTACT`，版本过旧直接报错，不会静默出缺页的书。

## 用法

```bash
# 0. 查重
python scripts/shelf.py check "<笔记链接或ID>"

# 1. 采集
python scripts/collect_note.py "https://www.xiaohongshu.com/discovery/item/xxxx" -o note/

# 2. 按 FORMAT.md 写书稿（四章结构，参考 templates/book_source_template.txt）

# 3. 排版（默认 xhs + dense 紧凑密度，自动补 @@CONTACT 联系页）
python scripts/build_book.py --source note/book_source.txt --title "书名" \
  --author "原作者" --intro "内容简介" -o note/书名.pdf

#    想要旧版大字号宽松版式：加 --density normal
#    单独微调：--size 9.6 --lead 14.2

# 4. 验收（含二维码矩阵、来源、内容密度）
python scripts/verify_book.py --pdf note/书名.pdf --source note/book_source.txt \
  --data note/note_data.json --render note/抽样页

# 5. 归档进书架
python scripts/shelf.py archive note/ --title "书名" --author "原作者" \
  --note-id "<笔记链接或ID>" --tags "标签" --brief "一句话简介" \
  --pdf 书名.pdf --source book_source.txt --data note_data.json \
  --verify verify_report.txt --render 抽样页
```

## 联系页与品牌资源

`assets/brand/brand.json` 配文案与三张二维码，改文案、换码只改这个目录，不用碰引擎和书稿：

```
assets/brand/
├── brand.json       标题 / 说明段落 / 三码标签 / 品牌行 / 页脚 / 验收关键词
├── qr_weixin.jpg            冷石 · 微信
├── qr_huangjinchen.jpg      老哥 · 黄金臣
├── qr_lengshi_miaowu.jpg    冷石妙悟 · 模因公社
└── README.md                字段说明与注意事项
```

书稿里**不写** `@@CONTACT` 也没关系：`build_book.py` 会生成同目录临时副本补上标记，排完删除。
页脚固定保留「扫码联系的是整理者，非原帖作者」——书内正文是他人原创，不能让读者误以为码是原帖作者的。
语气保持克制的一则说明，不写促销话术。

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
        └── note.meta.md        归档卡片
```

- **命名**：`日期_书名_原作者`，自动清理 Windows 非法字符与 emoji
- **查重**：按笔记 ID；同笔记再次归档会被拦下并提示旧档位置，重制加 `--v2`（旧版保留）
- **版权**：`books/` 与 `INDEX.md` 已在 `.gitignore` 里排除——书的内容含他人原创，公开仓库只放工具本身

## 版式

| preset | 外观 | 用途 |
|---|---|---|
| `xhs` + `dense`（**默认**） | 白底、顶部珊瑚红条、黑体正文 9.0pt/行距 13.4、段间距 ×0.45、卡片内边距 ×0.55、版心更宽；出版说明与目录合并一页，二维码矩阵为真正尾页 | 信息流摘录、图文/评论卡册；每章约 1 页 |
| `xhs` + `normal` | 同款配色，正文 10.4pt/行距 17.6、留白更多（v2.0 及以前的版式） | 收藏版、需要大字号时 |
| `modern` | 宣纸底、宋体、传统书籍观感 | 长篇文字摘录 |
| `classic` | 封面「国学经典 · 原文整理丛书」+ 公版声明 | **仅限公版古籍**，当代内容会造成错误版权声明 |

`--density` 只对 `xhs` 生效；`modern`/`classic` 会保持原有宽松版式。
**压页数的正确做法**是收紧密度与拆细章节，不是删掉评论原文：评论应收尽收，
一章跨 2 页以上就拆成两章。

## 目录

```
SKILL.md                        流程与硬规则（Agent 读这个）
FORMAT.md                       书稿格式语言：四章规范、标记总表、硬上限、验收清单
README.md                       本文件
templates/book_source_template.txt  四章书稿骨架
assets/brand/                   品牌资源（brand.json + 三张二维码 + README）
vendor/book_pdf.py              排版引擎（xhs preset、评论卡、联系页、--density dense）
scripts/collect_note.py         采集
scripts/build_book.py           排版（默认 xhs + dense，自动补联系页）
scripts/verify_book.py          验收（矩阵 / 来源 / 内容密度）
scripts/shelf.py                书架归档（init/archive/list/check）
```

引擎最初来自 [ebook-pdf-maker](../ebook-pdf-maker)，本包已把含小红书版式与联系页的版本 vendor 进来，
clone 后即可独立出书。

## 版权

本技能只做个人阅读存档用途的摘录与编排。成书必须保留原作者与评论作者署名、原帖地址，并注明「请勿传播或商用」；公开分发需取得原作者授权。
