# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本。

## [Unreleased]

### Added

- 新增风格预设 `jp-anime-pastel`（日系小清新 · 二次元柔和）：奶油白 + 樱粉 + 浅天蓝的低饱和水彩配色、
  和纸胶带与手账排版、圆体字，并内置"不绘制任何可识别既有动漫角色形象"的版权约束。

### Fixed

- **质量闸门误报**：整页 OCR 分段失败时（例如卡片里的文字被当成图片跳过），原本会报"文本匹配率偏低"，
  误导成文字写错。现在会明确提示"可能是分段/检出错位，请人工看图确认"。
- 新增**条带兜底 OCR**：行命中率不达标时自动把图按横向条带切开重新识别并合并，实测把匹配率
  从 0.263 救回到 0.959（整页放大无效，条带切分有效）。

### Changed

- 测试从 98 增至 104。

## [0.1.0] - 2026-01-01

### Added

- **阶段 1 · 规格化**：`deck.py spec skeleton|render`，把一段自然语言描述转成
  `deck_spec.json`，自动补齐页数、风格预设、版式、负向约束与讲者备注；渲染出与模板同构的
  `风格锁定与每页提示词.md` 与逐页提示词 `prompts/page-NN.md`。
- **四种风格预设**：`aurora-glass`（深色极光玻璃拟态）、`clean-corporate`（默认浅色商务）、
  `academic-paper`（学术）、`vivid-marketing`（高对比营销），按描述关键词自动路由。
- **阶段 2 · 出图与质检**：四种生图后端（`openai-images` / `chat-image` /
  `openrouter-images` / `editppt-cli`）、进程内并发、指数退避重试、成本记账、`--max-cost` 预算闸门；
  16:9 智能裁切 / 模糊羽化补边适配。
- **质量闸门**：尺寸、宽高比、空白、跨页重复（dHash）、中文文本保真度（飞桨 OCR + difflib），
  失败自动重抽一次，产出 `qa_report.json` 与 `contact-sheet.png`。
- **图片版组装**：整页图铺满 + 讲者备注 → `PPTX`，`soffice` 导出 `PDF`。
- **阶段 3 · 元素版**：委托 `image-to-editable-ppt`，两种模式——
  默认（无子代理）逐页单 run 重建后由上游构建器合并；`--subagents` 单次多页 run + 流水线并行派工。
- `install.sh`：软链/复制安装到 `~/.dsh/skills`、`~/.claude/skills` 等技能目录。
- 文档：`docs/PUBLISH-TO-GITHUB.md`（上传 GitHub 全流程）、`docs/workflow.md`、`docs/faq.md`、`docs/verification.md`（验证记录）。
- 98 个单元测试 + GitHub Actions CI（不含任何付费 API 调用）。
