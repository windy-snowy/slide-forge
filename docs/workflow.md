# 工作流与状态机

## 一、三个阶段

```
用户描述（+ 参考材料）
   │
   ├─ 阶段 1  规格化 ─────────────────────────────────────────────
   │     prompts/extract-spec.md  →  deck_spec.json
   │     deck.py spec render       →  风格锁定与每页提示词.md + prompts/page-NN.md
   │     （缺什么补什么：页数/风格/版式/负向约束/备注）
   │
   ├─ 阶段 2  出图 + 质检 + 图片版 ────────────────────────────────
   │     deck.py gen   --concurrency 3   →  images/page-NN.png + qa/usage.json
   │     deck.py qa                      →  qa/qa_report.json + contact-sheet.png
   │     ★ 人工确认点：看总览图，决定是否重抽
   │     deck.py pptx                    →  <title>-图片版.pptx（含讲者备注）+ .pdf
   │
   └─ 阶段 3  元素版 ──────────────────────────────────────────────
         editable_run.py prepare  →  默认：N 个单页 run ／ --subagents：1 个多页 run
         逐页重建（主 agent 本地 或 page worker 子代理）
         record → finalize → merge
                                        →  <title>-元素版.pptx
```

## 二、运行目录布局

```
deck-runs/20260101-120000-<slug>/
├── deck_spec.json                 # 唯一机器规格（可重跑）
├── 风格锁定与每页提示词.md          # 人工可读，与用户要求的模板同构
├── prompts/page-01.md …           # 实际发给生图模型的完整提示词
├── images/page-01.png …           # 整页 16:9 出图
├── qa/
│   ├── qa_report.json             # 逐页指标 + 闸门结论
│   ├── contact-sheet.png          # 总览图（人工确认用）
│   └── usage.json                 # 逐页耗时/成本/重试次数
├── out/
│   ├── <title>-图片版.pptx
│   ├── <title>-图片版.pdf
│   └── <title>-元素版.pptx        # 阶段 3 产物
└── editable/
    ├── plan.json                  # 模式与各部分路径
    ├── parts/p01 … pNN/           # 默认模式：每页一个独立单页 run
    ├── run/                       # 子代理模式：单个多页 run
    └── merged/                    # 默认模式的合并清单 + validation.json
```

## 三、状态与断点续跑

| 状态 | 判别依据 | 怎么续 |
| --- | --- | --- |
| 规格已就绪 | `deck_spec.json` 存在 | `deck.py spec render` 重渲染 |
| 部分出图 | `images/` 有缺页 | `deck.py gen --only 3,7`（已有页自动跳过） |
| 出图完成 | 每页都有图 | `deck.py qa` |
| 质检未过 | `qa_report.json.summary.gate_ok == false` | `gen --only <失败页> --force` |
| 图片版就绪 | `out/*-图片版.pptx` | `deck.py pptx` 可重跑 |
| 元素版进行中 | `page_jobs.json` 里各页状态 | `editable_run.py next --run <run>` |
| 元素版完成 | `editable/merged/validation.json.passed == true` 或上游 `run_summary.json` | 交付 |

所有产物都是文件，任何一步中断后重跑同一条命令即可继续；`gen` 默认跳过已存在的页。

## 四、两处必须停下来看人

1. **质检后（阶段 2 → 3 之间）**：把 `qa/contact-sheet.png` 与逐页图给用户确认。这一步
   是"生成质量确认"，也是用户唯一能低成本改风格/重抽某页的时机。
2. **元素版开始前**：告知将调用 `editppt` 的图像接口做资产分离，会产生额外费用；
   以及在多页场景下默认模式比子代理模式慢。

## 五、模型与密钥的分工

> 前置：元素版需要 `image-to-editable-ppt` 的 SKILL.md 与 `references/` 可读（不要求它出现在当前 agent 的技能目录里）。
> 用 `python3 scripts/editable_run.py doctor` 解析 `upstream_skill_dir`；`merge_pages.py --check` 单独体检合并适配器。

| 用途 | 谁在用 | 配置位置 |
| --- | --- | --- |
| 阶段 2 出图 | `img_providers.py` | `SLIDEFORGE_IMAGE_*` / `OPENAI_*` / `OPENROUTER_API_KEY` / `~/.slideforge/config.json` / `~/.editppt/config.yaml` |
| 阶段 3 资产分离 | `editppt image edit` | `~/.editppt/config.yaml`（`editppt config --model` 写入） |
| OCR | `paddle_text_hints.py` | `PADDLE_OCR_TOKEN` 或 `~/.editppt/config.yaml` |

两边的模型可以不同：`--image-model` 管阶段 2，`--edit-model` 管阶段 3。
