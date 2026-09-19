# OCR：百度飞桨 PaddleOCR

OCR 在 slide-forge 里有两个用途，配置一次即可：

1. **质量闸门回读文字**：把生成页图当作 `source.png`，用 `editppt page hints` 拿到逐行文字与
   坐标（后端 `paddleocr-vl`），再与 `deck_spec.json` 的 `core_text` 比对，判断有没有错字/漏字/乱码。
2. **元素版文本定位**：`image-to-editable-ppt` 用它校正文本框、字号与字号分组，让重建出来的
   文字尺寸稳定得多。这一条由上游技能自己使用，slide-forge 不干预。

## 一、拿 token

1. 打开 <https://aistudio.baidu.com/account/accessToken>；
2. 免费申请个人访问令牌；
3. 任选一种方式配置：

```bash
# 方式 A：写进 editppt 的配置（推荐，跨子代理生效）
editppt config --paddle-ocr-token "<token>"

# 方式 B：环境变量
export PADDLE_OCR_TOKEN="<token>"
```

4. 验证：

```bash
editppt doctor     # 期望看到 text hints=paddleocr-vl
```

`editppt config` 会把 token 写进 `~/.editppt/config.yaml`，页面 worker（子代理）也能读到。

## 二、没有 token 会怎样

- `editppt page hints` 会退回离线检测器 `builtin-ink`：**只有几何信息（在哪、多大），没有文字内容**。
- slide-forge 的 QA 会因此拿不到 OCR 文本 → 自动降级为**仅几何检测**，并在
  `qa/qa_report.json` 里写明 `ocr_backend: null` + `"OCR 未返回可用文字，跳过文本保真度检测"`。
- **不要**在这种状态下宣称"中文已校验通过"。要如实告诉用户：文本只做了几何检测。

## 三、token 已配置但请求失败

可能原因：网络受限、DNS、沙箱拦截、配额。处置顺序：

1. 报告中转/网络问题，重跑 `editppt run hints <run>` 或 `deck.py qa`；
2. 仍失败 → 告知用户 OCR 只影响"文本尺寸稳定性"和"文本保真度检测"，问是否继续；
3. 只有在用户明确拒绝时才按**仅几何检测**继续。

## 四、配额

飞桨官方 API 有免费额度，个人使用通常远够（每张图一次调用）。
配额与错误码见 <https://ai.baidu.com/ai-doc/AISTUDIO/Xmjclapam>。

## 五、自定义 OCR

`deck_spec.json` 里的 `backends.ocr.provider` 目前只用于记录；实际 OCR 由 `editppt` 决定。
要换后端，改 `editppt` 的配置，或在 `scripts/qa.py` 的 `ocr_lines()` 里替换实现——
该函数是唯一调用点，返回值约定为 `(lines, backend)`，`lines[i]` 形如
`{"text": "...", "box_px": [x, y, w, h]}`。
