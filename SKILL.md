---
name: slide-forge
description: 从一句自然语言描述生成整套演示文稿，产出「图片版」整页图 PPTX/PDF 与「元素版」对象级可编辑 PPTX。适用于用户只给了主题/风格/页数就想要 PPT，或给了参考文本/文档要快速成稿；不适用于已有 PPT 只想转可编辑（直接用 image-to-editable-ppt）。
---

# slide-forge（幻灯工坊）

把一段文字描述变成两份交付物：

| 产出 | 形态 |
| --- | --- |
| **图片版** | 每页一张整页 16:9 高清图 → `.pptx`（整页铺满 + 讲者备注）+ `.pdf` |
| **元素版** | 由图片版经 `image-to-editable-ppt` 重建的对象级可编辑 `.pptx`（文字/形状/图片各自可选可改） |

本技能是**编排层**：负责把描述转成风格锁定 + 逐页提示词、调用生图后端逐页出图、跑质量闸门、组装 PPTX，并驱动元素版流程。页面重建的全部规则以 `image-to-editable-ppt` 的 SKILL.md 为准，本文件不重述、也不覆盖它。

## 一、什么时候用

- 用户给了一段描述（主题 / 风格 / 页数 / 受众 / 用途 / 参考材料）就想要一份 PPT；
- 用户说"帮我做个 PPT""把这些材料讲成一页页的图""做个能改的 PPT"。

**不要用**的场景：已有一份 PPT/图片只想转成可编辑 → 直接加载 `image-to-editable-ppt` 技能。

## 二、输入与「不要反复追问」

必需：**一份描述**。其余都尽量从描述里提取，提不到就用默认值（默认值清单见
`references/spec-format.md`）。只在下面三件事上问用户，一次问清、不要连问：

1. 用哪个生图模型（若环境里没有可用的密钥/模型配置）；
2. 是否已配置生图 API 与飞桨 OCR token；
3. 是否现在开始**真实**生图（会产生费用）。

缺失信息的默认值（不要问、直接落）：

| 缺失项 | 默认 |
| --- | --- |
| 页数 | 10（3–40 之间钳制） |
| 风格 | 按关键词路由预设；无命中 → `clean-corporate` |
| 受众 / 用途 / 时长 | 通用受众 / 分享 / 页数相同分钟数 |
| 页面结构 | 封面 → 总览 → 内容页 → 总结 → 下一步 |
| 缺失数据 | 写 `【待补】`，**绝不编造** |
| 讲者备注 | 每页 3–4 句口语稿 |
| 画幅 | 16:9；gpt-image 系列用 `1536x1024` + `fit=auto` 适配 |

## 三、工作流

先自检，再决定是否需要问上面三个问题：

```bash
python3 <skill>/scripts/deck.py doctor
```

想一条命令走完（到质检为止），可以直接：

```bash
python3 <skill>/scripts/deck.py all "<用户原话>" --until qa
```

`all` 会从描述里自动抠出页数 / 时长 / 受众（例如"3 页""约 20 分钟""给大学生讲"），
其余走默认值。下面的三步是它的展开，需要精细控制时逐步执行。

### 阶段 1 · 描述 → 规格与提示词

用 `prompts/extract-spec.md` 的规则把用户描述写成 `deck_spec.json`，然后渲染：

```bash
# 方式 A：用户信息很少时，先让脚本出一个默认骨架，再在上面补内容
python3 <skill>/scripts/deck.py spec skeleton "给大学生讲 Transformer，科技风，10 页" \
    --out <run>/deck_spec.json

# 方式 B：先按 prompts/extract-spec.md 手写 deck_spec.json，再渲染

python3 <skill>/scripts/deck.py spec render --spec <run>/deck_spec.json --print-first
```

产出 `<run>/deck_spec.json`、`<run>/风格锁定与每页提示词.md`（与用户要求的模板同构）、
`<run>/prompts/page-NN.md`。**先看渲染结果再往下走**：标题、页数、风格是否符合用户意图。

### 阶段 2 · 逐页生图 + 质量闸门 + 图片版

```bash
python3 <skill>/scripts/deck.py gen --spec <run>/deck_spec.json --dry-run      # 先看将发出去的提示词
python3 <skill>/scripts/deck.py gen --spec <run>/deck_spec.json --concurrency 3
python3 <skill>/scripts/deck.py qa  --out-dir <run>                            # 质量闸门 + 总览图
python3 <skill>/scripts/deck.py pptx --out-dir <run>                           # 图片版 PPTX + PDF
```

- 生图用**进程内并发**（`--concurrency`，默认 3），不要为此派子代理——每页只是一次 HTTP 调用。
- `qa` 产出 `qa/qa_report.json`、`qa/contact-sheet.png`、`qa/usage.json`（逐页耗时与成本）。
- **人工确认点（必须停一次）**：把 contact sheet 与不合格/警告页展示给用户，确认后再进元素版。
  不合格页用 `gen --only 3,7 --force` 重抽。
- 首轮验证建议先跑小样：`--only 1,2,3 --quality low`，确认中文与版式没问题再全量。

### 阶段 3 · 元素版（委托 image-to-editable-ppt）

1. **按 `image-to-editable-ppt` 的 SKILL.md 全文执行**（Phase 1 Prepare → Phase 2 页面重建 → Phase 3 Record → Phase 4 Finalize）。本技能的脚本只是把它的命令串起来。
   加载方式按顺序尝试：
   - 用 `skill` 工具加载 `image-to-editable-ppt`；
   - **该技能不在本技能目录里时**（常见：它装在别的 agent 的技能根下，例如 `~/.dsh/skills`、`~/.claude/skills`），
     用 `editable_run.py doctor` 解出它的目录（字段 `upstream_skill_dir`），然后直接读
     `<该目录>/SKILL.md` 与 `<该目录>/references/`、`<该目录>/prompts/page-worker.md`，照此执行；
   - 都找不到就停下来报告，并提示安装命令
     `npx -y skills@latest add ningzimu/image-to-editable-ppt-skill --skill image-to-editable-ppt --global`。
2. 编排入口：

```bash
python3 <skill>/scripts/editable_run.py doctor
python3 <skill>/scripts/editable_run.py prepare --spec <run>/deck_spec.json [--subagents]
```

3. 模型对齐：`--edit-model <模型>` 会写进 `editppt` 配置（跨子代理生效），与阶段 2 的生图模型解耦。
4. 在 DSH 运行时**不要**传 `--image-backend builtin-imagegen`：本运行时没有 `image_gen.imagegen` 工具，
   用 `editppt` 默认的 CLI 回退链（Codex OAuth → OpenAI 兼容 API）。
5. 备注保留：图片版 PPTX 自带讲者备注；多页模式直接以它为输入，默认模式在合并时从 `deck_spec.json` 注入。

## 四、子代理模式（默认关闭）

**默认不使用子代理。** 只有当用户明确说"用子代理模式 / 并行加速 / subagents / 多代理跑"时才加
`--subagents`；没有这句话就按默认执行，**不要为此追问**。开工前可以打印一行提示（不是提问）：

> 默认不使用子代理：元素版会逐页本地重建后合并成一份 PPTX；若想单文件原生多页且更快，说"用子代理模式"。

两种模式的差异（依据上游源码：`--local` 只允许单页 run，上游又禁止主 agent 重建多页 run）：

| | 默认（无子代理） | `--subagents` |
| --- | --- | --- |
| run 结构 | N 个单页 run（`editable/parts/pNN/`） | 1 个多页 run（`editable/run/`） |
| 重建者 | 主 agent 逐页 `dispatch --local` | 并行 subagent（page worker） |
| 收尾 | `merge_pages.py` 用上游构建器合并 | `editppt run finalize` |
| 代价 | 逐页串行，占用主对话上下文 | 需要子代理能力；并发受中转站限流约束 |

**开启子代理时的加速策略**

1. `--page-worker-concurrency K`：默认 3，上限 `min(6, page_jobs.json.max_concurrent_pages)`。
2. **无栅栏流水线**：一轮并行派 K 个 page worker；谁先返回就立刻 `record` 并补派下一页，始终保持 K 个槽位满载。
3. 命中 429/超时就降到 K=2 再重试该页；同一页不要因为慢而重启 worker。
4. 只跑一次 `editppt prepare`（OCR hints 共享），worker prompt 已自动追加 `prompts/page-worker-efficiency-annex.md`
   的效率附录（原生形状优先、资产合并成 ≤2 张 sheet、页内图像任务串行）以减少每页图像调用。
5. worker prompt 用**绝对路径**：`editable_run.py prompt --run <run> --page <page_id> --out <run>/pages/<page_id>/worker-prompt.md`。
6. 每 `record` 一页就累加 `imagegen-jobs.json` 的成本到运行账本；超过用户给的预算就停止补派新页。
7. `record` 失败时用 `send_message` 让**原 worker**只修受影响的产物，不要重派、不要 reset 活跃租约。

### 默认模式的逐页循环（主 agent 自己跑）

```bash
# 对每一页 p01..pNN（单页 run）：
python3 <skill>/scripts/editable_run.py prompt   --run <run>/editable/parts/pNN --page page_001 --local
python3 <skill>/scripts/editable_run.py dispatch --run <run>/editable/parts/pNN --page page_001 \
        --agent-id main --prompt-file <run>/editable/parts/pNN/pages/page_001/worker-prompt.md --local
#   ← 由你按 worker-prompt.md 亲自重建该页（产出 manifest.json / page.pptx / preview.png / validation.json …）
python3 <skill>/scripts/editable_run.py record   --run <run>/editable/parts/pNN --page page_001 --agent-id main
python3 <skill>/scripts/editable_run.py finalize --run <run>/editable/parts/pNN

# 全部页完成后合并：
python3 <skill>/scripts/editable_run.py merge --spec <run>/deck_spec.json
```

合并复用上游 `build_pptx_from_manifest.py` + `validate_pptx.py`（不写 XML、不搬 slide），
要求 `validation.json` 顶层 `passed: true`。若合并适配器不可用或校验失败：**如实报告**，
降级为逐页交付 `editable/parts/pNN/pages/page_001/page.pptx`，并建议改用 `--subagents`。

### 子代理模式的循环

```bash
python3 <skill>/scripts/editable_run.py prepare --spec <run>/deck_spec.json --subagents --page-worker-concurrency 3
python3 <skill>/scripts/editable_run.py next --run <run>/editable/run     # 反复调用直到 finalize
```

`next` 返回 `dispatch_pages` 时：对建议的每页执行 `prompt` → 用 subagent 派 worker →
`dispatch --run <run> --page <id> --agent-id <id> --prompt-file <绝对路径>`；返回 `wait` 就等，
不要动活跃租约；返回 finalize 阶段就 `finalize --run <run>/editable/run`。

## 五、密钥与费用纪律

- 密钥只从环境变量或 `~/.slideforge/config.json`(chmod 600) 读：`SLIDEFORGE_IMAGE_API_KEY`、
  `OPENAI_API_KEY`、`OPENROUTER_API_KEY`；`editppt` 侧用 `~/.editppt/config.yaml` 与 `PADDLE_OCR_TOKEN`。
- **绝不**把密钥写进仓库、运行目录、提示词、manifest 或任何产物。
- 先 `--dry-run` 看提示词；真实生图前告知用户会产生费用；`--max-cost` 可设预算上限。
- 逐页成本与耗时写进 `qa/usage.json`，收尾时汇报总额。

## 六、失败模式与处置

| 现象 | 处置 |
| --- | --- |
| `deck.py doctor` 缺 Pillow/numpy/python-pptx | 告知安装命令，不要绕过 |
| 无生图密钥 | 只问一次：给 key，或改用 `--provider editppt-cli` 复用 `editppt` 配置，或停在 dry-run |
| `HTTP 403 额度不足` | 直接告知账户余额不足，停止重试 |
| 质量闸门 fail（空白/尺寸/重复） | `gen --only <页> --force` 重抽；连续 2 次失败就把原图交给用户判断 |
| 质量闸门 warn（文本匹配率低） | 展示 warn 明细与总览图，由用户决定是否重抽 |
| OCR 不可用 | 降级为仅几何检测，在报告里显式标注，**不**声称"文本已校验" |
| 16:9 无法裁切 | `fit=pad` 模糊羽化补边（内容不丢）；用户不满意就换原生支持 16:9 的模型 |
| 找不到 `editppt` | 按 `image-to-editable-ppt` 的 Pre-Run Check 安装，`pipx install --force --editable <i2e-skill>/cli` |
| 多页但无子代理能力 | 用默认模式（逐页单 run + 合并）；若合并也不可用，逐页交付并说明 |
| 合并校验 failed | 按上游 Fix-vs-Warning 修复受影响页；仍不通过就逐页交付 + 报告原因 |

## 七、不要做的事

- 不重写或覆盖 `image-to-editable-ppt` 的页面决策规则；元素版遇规则问题就去读它的 references。
- 不把密钥、token、用户隐私材料写进仓库或产物。
- 不跨页复用同一张图；不伪造 `validation.json` 或 QA 结果。
- 不在用户没要求时派子代理。
- 用户材料里没有的数字，不编。

## 八、资源索引

| 文件 | 用途 |
| --- | --- |
| `scripts/deck.py` | 主 CLI：doctor / spec / gen / qa / pptx / editable / all |
| `scripts/spec_model.py` | 规格模型：预设加载、默认值填充、Markdown 渲染 |
| `scripts/img_providers.py` | 四种生图后端 + 16:9 适配 |
| `scripts/qa.py` | 逐页质量闸门 + 总览图 |
| `scripts/editable_run.py` | 元素版编排（两种模式） |
| `scripts/merge_pages.py` | 默认模式的合并适配器（复用上游构建器） |
| `prompts/extract-spec.md` | 描述 → `deck_spec.json` 的转换规则 |
| `prompts/page-worker-efficiency-annex.md` | 追加到 page worker prompt 的效率约束 |
| `references/spec-format.md` | `deck_spec.json` 字段契约与默认值 |
| `references/prompt-template.md` | 提示词文档模板与字段含义 |
| `references/image-models.md` | 各生图后端参数、成本与 16:9 行为 |
| `references/ocr.md` | 飞桨 PaddleOCR 配置与降级 |
| `references/editable-pipeline.md` | 元素版两模式契约与上游依据 |
| `references/subagent-strategy.md` | 子代理加速策略细节 |
| `references/presets/*.json` | 风格预设（可自行新增） |
