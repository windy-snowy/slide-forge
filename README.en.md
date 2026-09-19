# slide-forge

[中文](README.md) | **English**

> One sentence in → two decks out: an **Image deck** (full-page renders, best looking) and an **Element deck** (object-level editable, best to modify).

[![CI](https://github.com/<your-name>/slide-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/<your-name>/slide-forge/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)

![Example cover](examples/transformer-glass/images/p01.jpg)

## What it does

Say:

> Make a 10-page technical talk deck about Transformers for university students — dark tech style, glassmorphism, ~20 minutes.

slide-forge will:

1. **Normalize** that sentence into a reproducible `deck_spec.json` (theme lock + per-page prompts), filling anything missing with sensible defaults;
2. **Render each page** with the image model you choose, run a **quality gate** (16:9, blank, duplicate, Chinese text fidelity) and show you a contact sheet to confirm;
3. Deliver **two decks**:

| Output | Name | Form | Use when |
| --- | --- | --- | --- |
| Visual | **Image deck** | one full-page 16:9 render per slide → `PPTX` (with speaker notes) + `PDF` | sharing, presenting, archiving |
| Editable | **Element deck** | every text box, shape and image is its own object → editable `PPTX` | you need to change text, colors, layout |

The editable deck is rebuilt by [`ningzimu/image-to-editable-ppt-skill`](https://github.com/ningzimu/image-to-editable-ppt-skill);
slide-forge orchestrates it and hands you a single file.

## Features

- **One sentence is enough** — page count, style, audience, purpose and duration fall back to defaults; no interrogation loop.
- **Four style presets** — aurora-glass (dark tech), clean-corporate (default), academic-paper, vivid-marketing; auto-routed by keywords, easy to add your own.
- **Multiple image backends** — OpenAI-compatible (gpt-image family), OpenRouter (native 16:9), `chat/completions` relays, and a CLI backend reusing your `editppt` config.
- **Quality gate** — size / aspect / blank / cross-page duplicates (dHash) / Chinese text fidelity via PaddleOCR; failures are re-rolled automatically and a contact sheet is produced for human confirmation.
- **Speaker notes** — 3–4 spoken sentences per page, embedded into the PPTX and carried into the element deck.
- **Subagent mode is opt-in (off by default)** — say "use subagent mode" to rebuild the element deck with parallel page workers.
- **Never fabricates facts** — anything not in your material becomes a `【待补】` placeholder.

## Install

```bash
git clone https://github.com/<your-name>/slide-forge.git ~/slide-forge
cd ~/slide-forge && ./install.sh          # symlink into ~/.dsh/skills/slide-forge
./install.sh --target ~/.claude/skills    # or another agent
./install.sh --copy                       # when symlinks are unavailable
```

Then just ask your agent: *"use slide-forge to build a deck about …"*.

Command line only:

```bash
cd ~/slide-forge
python3 -m pip install Pillow numpy python-pptx
python3 scripts/deck.py doctor
```

## Quickstart

```bash
SF=~/slide-forge

python3 $SF/scripts/deck.py doctor

# 1) sentence -> spec + prompts (inspect first)
python3 $SF/scripts/deck.py all "…your description…" --until render --print-first

# 2) render pages (dry-run first: prints prompts, calls nothing)
python3 $SF/scripts/deck.py gen --spec <run>/deck_spec.json --out-dir <run> --dry-run
python3 $SF/scripts/deck.py gen --spec <run>/deck_spec.json --out-dir <run> --only 1,2,3 --quality low

# 3) quality gate -> review the contact sheet
python3 $SF/scripts/deck.py qa --out-dir <run>

# 4) image deck (PPTX + PDF)
python3 $SF/scripts/deck.py pptx --out-dir <run>

# 5) element deck (no subagents by default)
python3 $SF/scripts/editable_run.py prepare --spec <run>/deck_spec.json
python3 $SF/scripts/editable_run.py merge   --spec <run>/deck_spec.json
```

## Which output do I want?

| | Image deck | Element deck |
| --- | --- | --- |
| Visual fidelity | ★★★★★ | ★★★☆ (rebuilt from the render) |
| Editable | only as a whole page | per text box / shape / image |
| Speed | fast (N renders) | slower (per-page object reconstruction) |
| Cost | rendering | rendering + asset separation |
| Best for | presenting, sharing | further editing, handing off |

## Documentation

- [Publish to GitHub](docs/PUBLISH-TO-GITHUB.md) (Chinese, step by step)
- [Workflow and state machine](docs/workflow.md) · [FAQ](docs/faq.md)
- [Spec format](references/spec-format.md) · [Prompt template](references/prompt-template.md)
- [Image backends](references/image-models.md) · [OCR setup](references/ocr.md)
- [Element deck contract](references/editable-pipeline.md) · [Subagent strategy](references/subagent-strategy.md)

## Requirements

Python 3.8+, `Pillow`, `numpy`, `python-pptx`, an image generation API.
Optional but recommended: [`editppt`](https://github.com/ningzimu/image-to-editable-ppt-skill) (element deck),
LibreOffice `soffice` (PDF export), a PaddleOCR token (text fidelity checks).

## License

MIT — see [LICENSE](LICENSE).
