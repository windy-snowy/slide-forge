# 贡献指南

## 本地开发

```bash
git clone <repo> && cd slide-forge
python3 -m pip install Pillow numpy python-pptx     # 只跑测试需要这三个
python3 -m unittest discover -s tests -v
python3 scripts/deck.py doctor
```

**测试不允许联网、不允许调用付费 API。** 需要模拟接口返回时，直接在测试里构造字典喂给
`img_providers.extract_image()`。

## 目录约定

| 目录 | 放什么 |
| --- | --- |
| `scripts/` | 只放可执行脚本，全部使用标准库 + PIL/numpy/python-pptx |
| `references/` | 规则与契约的**唯一权威出处**，脚本里不要在注释里重复规则 |
| `prompts/` | 会被拼进 LLM 提示词的模板 |
| `tests/` | `unittest`，文件名 `test_*.py` |

## 提交前自检

```bash
python3 -m py_compile scripts/*.py tests/*.py
python3 -m unittest discover -s tests
python3 scripts/deck.py spec skeleton "冒烟测试" --out /tmp/s.json --pages 3
python3 scripts/deck.py spec render --spec /tmp/s.json --out-dir /tmp/srun
python3 scripts/deck.py gen --spec /tmp/srun/deck_spec.json --out-dir /tmp/srun --dry-run
```

## 加一个风格预设

1. 在 `references/presets/` 复制一个现有 JSON；
2. 改 `name` / `label` / `description` / `keywords` / `theme_lock` / `global_style_block`；
3. 在 `tests/test_spec_model.py` 里补一条路由断言。

## 改质量阈值

`scripts/qa.py` 的 `DEFAULT_THRESHOLDS` 是唯一出处；改完在 `tests/test_qa.py` 里同步断言。

## 提交信息

用 `<type>: <subject>` 形式（`feat` / `fix` / `docs` / `test` / `refactor` / `chore`），
一个 PR 一件事。涉及 prompt 或阈值的改动，请在 PR 描述里贴出前后对比（截图或报告片段）。

## 不要提交

密钥、`~/.editppt/config.yaml`、`deck-runs/`、生成的 PPTX/PDF、真实客户材料。
