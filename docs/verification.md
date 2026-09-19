# 验证记录

这份文件记录 slide-forge 在真实环境里**实测过的**与**没有实测的**，以及每一步的证据来源。
写下来是为了让使用者知道哪些路径可以信、哪些还需要自己跑一遍。

环境：Linux + conda python 3.8.10（Pillow 10.4 / numpy 1.21 / python-pptx 1.0.2）、
`editppt` 已装（CLI 回退后端 = OpenAI 兼容 API，`IMAGE_TO_EDITABLE_PPT_IMAGE_MODEL=gpt-image-2`）、
飞桨 OCR token 已配置、`soffice` 可用、git 2.25.1、无 `gh` CLI。

## 一、单元测试

```bash
python3 -m unittest discover -s tests
# Ran 98 tests ... OK
```

覆盖：规格默认值与提示词拼装、四种预设与路由、描述里的页数/时长/受众解析、
16:9 适配（pad/crop/none）、四种后端的 URL 与返回解析、配置优先级、质量闸门各项判定、
dHash 重复检测、文本保真度、合并清单结构、合并前置校验、上游定位与降级、
技能契约（frontmatter / 资源索引 / 文档链接 / 示例完整性 / 无硬编码密钥）。

CI（`.github/workflows/ci.yml`）在 Python 3.8 与 3.11 上跑：语法检查、单元测试、
`spec skeleton → spec render → gen --dry-run` 冒烟，**不触网、不调用付费 API**。

## 二、图片版：3 页真实小样（已端到端跑通）

输入描述：`给大学生讲 Transformer，3 页小样：封面 + 自注意力 + 总结，深色科技风、玻璃拟态，课堂分享`

| 环节 | 命令 | 实测结果 |
| --- | --- | --- |
| 规格化 | `deck.py spec render` | `deck_spec.json` + `风格锁定与每页提示词.md`（四节同构）+ 3 个 `prompts/page-NN.md` |
| 出图 | `deck.py gen --concurrency 3` | **3/3 成功**，墙钟 56s；单页 36.7s / 42.7s / 56.0s；`gpt-image-2`，`1536x1024`，`quality=low` |
| 16:9 适配 | `fit=auto` | 2 页原生已近 16:9（1672×940）无需处理；1 页走模糊羽化补边（1820×1024），内容零损失 |
| 质检 | `deck.py qa` | 通过 2 / 警告 1 / 不合格 0；OCR 后端 `paddleocr-vl`；文本匹配率 0.851 / 0.48 / 1.0 |
| 图片版 | `deck.py pptx` | `PPTX` 4.1MB（3 页满版图 + 备注 34/52/18 字）+ `PDF` 0.5MB；程序化核对：13.333″×7.5″、3 页、每页 1 张满版图、每页都有 notes |

**那 1 页警告的人工复核**：画面文字逐字正确。模型把 `它指向小猫，权重 0.72` 用
「一条标注 0.72 的弧线」表达而非渲染成一行文字，所以 OCR 匹配率 0.48。
这验证了「文本匹配率只用于定位可疑页，最终判断权在人」的设计：

![contact sheet 示例](../examples/transformer-glass/contact-sheet.jpg)

## 三、元素版：编排与合并路径（已用真实上游产物验证）

### 3.1 编排链路（真实跑通）

```bash
editable_run.py doctor                     # 解析出 upstream_skill_dir / runtime，merge_available=true
editable_run.py prepare --spec deck_spec.json --subagents --page-worker-concurrency 3
#   → 多页 run，notes_manifest.json 里 3 条讲者备注从「图片版 PPTX」自动保留
editable_run.py next --run <run>           # stage=dispatch_pages，3 页可派
editable_run.py prompt --run <run> --page page_00N
#   → 生成 worker-prompt.md 并自动追加效率附录
editppt run dispatch ... --agent-id <id>   # dispatched（活跃租约）
editppt run status                         # active_dispatches=3，slots_available=0
```

也验证了单页 run 的默认路径：`editable_run.py prepare`（不带 `--subagents`）会为每页建
独立单页 run，`run next` 返回 `rebuild_page_locally`。

### 3.2 合并适配器（真实数据，passed=true）

合并是默认（无子代理）模式的收尾步骤。用一个**真实上游重建产物**验证（`image2ppt-run/run-real`
的单页 run，其 `validation.json` 本来就是 `passed: true`）：

```bash
merge_pages.py --parts <parts> --spec <spec> --out 单页元素版.pptx
```

结果：

```json
{"slides": 1, "expected_pages": 1, "page_validation_missing": [],
 "failed_page_validations": [], "page_contract_violations": [],
 "notes_found": 1, "missing_parts": [], "warnings": [], "passed": true}
```

产物核对（程序化）：13.333″×7.5″、**22 个可独立选中的文本框**、7 个原生形状、20 张图片、
讲者备注保留 —— 不是"整页图片 + 盖一层假文字"。

> 这个验证过程发现并修复了一个真实 bug：合并清单最初漏了 `pages[].validation` 字段，
> 上游 `validate_pptx.py` 会把它解析成目录并报 `Is a directory`。已修复并加了回归测试。

### 3.3 子代理页面重建：**本轮未跑完**

3 个 page worker 已按策略并行派出（K=3，无栅栏），并确认它们在真实执行
（例如 `page_003` 已产出 `assets/clean_base.png`，`page_001` 已写出 clean-base 与 asset-sheet 提示词）。
但页面重建本身是上游 `image-to-editable-ppt` 的核心工作量（逐页对象级判定 + manifest 坐标），
单页耗时远超图片版。**本轮的 3 页元素版没有跑完**，因此：

- 不要把它当成"元素版全流程已验证"；图片版与合并路径是已验证的，页面重建是**上游技能的既有能力**，
  本轮只验证了编排与交接契约。
- 想自己跑完：保留 `editable/run/` 目录，用 `editable_run.py next --run <run>` 继续，
  或对已完成页 `record` 后 `finalize`。

## 四、没有实测的部分（诚实清单）

| 项目 | 状态 |
| --- | --- |
| `openrouter-images` 后端真实调用 | 只做了 URL/请求体/解析的单元测试；本机没有 OpenRouter key |
| `chat-image` 后端真实调用 | 同上 |
| `editppt-cli` 后端真实调用 | 只做了 dry-run 命令拼装测试（真实路径走的是 `openai-images`） |
| `vivid-marketing` / `academic-paper` / `clean-corporate` 预设出图 | 只验证了规格化与提示词渲染；**没有真实出图**（避免多余花费） |
| 10 页全量 + 元素版全量 | 未跑（按约定先跑 3 页小样，全量待用户确认） |
| GitHub 上传 | 未执行（本机无 `gh`、无凭据）；仓库已 commit，教程见 `PUBLISH-TO-GITHUB.md` |
| 公式 LaTeX 渲染 | 本机无 `xelatex`/`tectonic`，未验证 |

## 五、复现上面每一步

```bash
SF=<repo>
python3 -m unittest discover -s $SF/tests -v
python3 $SF/scripts/deck.py doctor
python3 $SF/scripts/deck.py all "给大学生讲 Transformer，科技风，3 页，用于课堂分享，约 20 分钟" --until render
# 真实出图需要密钥；先 dry-run 看提示词
python3 $SF/scripts/deck.py gen --spec <run>/deck_spec.json --out-dir <run> --dry-run
```
