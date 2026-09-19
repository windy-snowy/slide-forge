# FAQ 与已知限制

## 通用

**Q：一定要联网/付费 API 吗？**
是。阶段 2 需要生图 API，阶段 3 需要图像编辑 API（可用同一个），OCR 需要飞桨 token。
想零成本先看效果：`deck.py gen --dry-run` 只打印提示词，不调用任何接口。

**Q：支持哪些生图模型？**
见 `references/image-models.md`。四类后端：OpenAI 兼容的 `openai-images`、
`chat-image`（modalities 写法）、`openrouter-images`（原生 16:9）、`editppt-cli`（复用 editppt 配置）。

**Q：能生成中文以外的语言吗？**
可以。`meta.language` 影响文案与提示词；但预设里的字体与版式建议是按中文场景调的，
英文场景建议自建一个预设。

**Q：为什么不直接用 python-pptx 画元素版，而非要过一遍图片？**
因为"图片版"是**视觉质量**的最优解（扩散模型能做出设计稿级别的画面），而"元素版"是
**可编辑性**的最优解。两者取舍不同，所以都给你，而不是二选一。

## 质量闸门

**Q：`qa` 报 `OCR 未返回可用文字` 是什么意思？**
三种可能：没配飞桨 token、网络/配额问题、或该页文字太少导致 OCR 返回空。
报告里的 `ocr_note` 会写明具体原因。此时只做了**几何检测**（尺寸/空白/重复），
**没有**验证中文是否正确——不要据此宣称"文字没问题"。

**Q：飞桨偶发返回 0 行怎么办？**
脚本会自动重试一次，仍为空就降级为几何检测并记录原因。这一般是服务端的偶发行为，
重跑 `deck.py qa` 通常就好了。

**Q：文本匹配率 0.7 算不算失败？**
算 `warn` 不算 `fail`。OCR 对艺术字/发光字/斜排字本身就会读错，所以低分只代表
"值得人看一眼"，把低分那几行和原图对照后自行决定是否重抽。

**Q：怎么调阈值？**
`qa.py` 里的 `DEFAULT_THRESHOLDS`，或在调用 `qa_mod.evaluate(thresholds={...})` 时覆盖。

**Q：出图里的标题和 `deck_spec.json` 里写的**不完全一样**，是 bug 吗？**
不是 bug，是生图模型的正常行为：它会**改写/精简标题用词**，甚至把某条 `core_text`
换成一张图。实测两个例子：

| 位置 | spec 里写的 | 出图里实际渲染的 |
| --- | --- | --- |
| `examples/transformer-glass` 第 3 页 | `自注意力：每个词都在“看”别的词` | `自注意力机制：一个词如何“看到”全句` |
| 3 页小样第 2 页 | `它指向小猫，权重 0.72` | 画成一条标着 0.72 的弧线 + 箭头 |

这正是 QA 把文本匹配率偏低的页标成 **`warn`（值得人看一眼）而不是 `fail`（不合格）**的原因。
想让关键文字**逐字出现在画面上**，做法是：

1. 把它写进该页的 `core_text`，并保持简短（≤20 字效果最好）；
2. 在 `negative` 里明确写 `不要改写标题用词`；
3. 出图后看 `qa_report.json` 里 `lines[].best_ratio` 低分的行，决定是否 `gen --only N --force` 重抽。

**Q：`warn` 页要不要全部重抽？**
不必。`warn` 只代表"OCR 匹配率偏低"，可能是模型用了更好的视觉表达。判断依据是**看原图**：
文字是否逐字正确、有无乱码、有没有被裁切。文字对就放行。

## 元素版

**Q：为什么默认模式要把每一页拆成单独的 run？**
因为上游 `editppt` 的 `--local`（主 agent 本地重建）**只允许单页 run**
（`record_page_dispatch.py:55`），而上游又明确规定主 agent 不得重建多页 run。
所以无子代理时唯一合规路径就是"逐页单 run + 合并"。

**Q：合并会不会破坏版式？**
不会。合并**不搬 XML、不用 python-pptx 复制 slide**，而是复用上游自带的
`build_pptx_from_manifest.py`，它按每页自己的 `manifest.json` 重建每一页；
我们只是把 N 个单页目录串成一份清单。

**Q：合并失败怎么办？**
`validation.json.passed != true` 时会如实报错，不会伪造成功。此时可以：
①按上游 Fix-vs-Warning 修复受影响页后重跑 `merge`；②直接用
`editable/parts/pNN/pages/page_001/page.pptx` 逐页交付；③改用 `--subagents` 模式。

**Q：`skill` 工具里没有 `image-to-editable-ppt`，怎么办？**
很常见：它可能装在**另一个 agent 的技能根**下（例如 `~/.dsh/skills`），不在当前 agent 的技能目录里。
slide-forge 不依赖它出现在技能目录：`editable_run.py doctor` 会解析出 `upstream_skill_dir`，
直接读那里的 `SKILL.md` + `references/` 照此执行即可。想让它也出现在技能目录里：
`./install.sh --with-upstream`，或
`npx -y skills@latest add ningzimu/image-to-editable-ppt-skill --skill image-to-editable-ppt --global`。

**Q：`find_skill_root` 找不到上游技能？**
设置 `SLIDEFORGE_I2E_SKILL_ROOT=/path/to/image-to-editable-ppt`，
或确认 `~/.dsh/skills/image-to-editable-ppt/SKILL.md` 存在。`merge_pages.py --check` 可以单独体检。

**Q：子代理模式并发开多少？**
默认 3。单页资产分离会打 3–8 次图像接口，`K` 越大越容易触发 429。
遇限流就降到 2，并把质量档位降到 `low`。详见 `references/subagent-strategy.md`。

## 环境相关（本机实测）

| 现象 | 说明 |
| --- | --- |
| 系统 `python3` 没有 PyYAML | 所以规格用 JSON；`~/.editppt/config.yaml` 用容错解析读取 |
| `editppt` 装在独立 conda 环境 | 调用其 runtime 脚本时用其 shebang 解释器（`merge_pages._editppt_python()`） |
| 没有 `xelatex` / `tectonic` | `editppt formula render-latex` 可能不可用；公式会按上游的图片资产路径处理，并记录为 warning |
| 没有 `gh` CLI | 上传 GitHub 请按 `docs/PUBLISH-TO-GITHUB.md` 的 HTTPS+PAT 或 SSH 方式 |
| gpt-image 系列无原生 16:9 | 用 `fit=auto`：能裁就裁，不能就模糊羽化补边，内容不丢 |
| git 2.25 不支持 `git init -b` | 用 `git init && git symbolic-ref HEAD refs/heads/main` |
| 飞桨对"稀疏合成图"偶尔返回 0 行 | 真实幻灯片（元素密集）通常正常；QA 会降级并说明 |

## 成本

**Q：一份 10 页大概多少钱？**
取决于模型与档位，以响应里的 `usage` 为准，脚本会把每页成本累加进 `qa/usage.json`。
最省钱的做法是先 `--only 1,2,3 --quality low` 看小样，通过再全量。

**Q：怎么设预算上限？**
`--max-cost 2.0`：累计成本达到上限后停止重试剩余页，并保留已完成页。
