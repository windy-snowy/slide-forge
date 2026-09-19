# deck_spec.json 字段契约

`deck_spec.json` 是 slide-forge 的**唯一机器规格**。选 JSON 而不是 YAML，是因为目标环境常没有
PyYAML（例如 conda base 里只有 Pillow / numpy / python-pptx），JSON 零依赖。

`python3 scripts/deck.py spec render --spec <spec>` 会：

1. 读取 spec；
2. 用预设补齐所有缺失字段（并把补了什么写进 `defaults_applied`）；
3. 覆写 `deck_spec.json`；
4. 渲染 `风格锁定与每页提示词.md` 与 `prompts/page-NN.md`。

也就是说：**你只需要写你有把握的字段**。

## 一、顶层

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `schema_version` | ✅ | 固定 `1` |
| `brief` | ✅ | 用户原话。关键词路由、语言判定、slug 都基于它 |
| `preset` | ❌ | `aurora-glass` / `clean-corporate` / `academic-paper` / `vivid-marketing`；留空则按关键词路由 |
| `meta` | ✅ | 见下表 |
| `theme_lock` | ❌ | 不写则由预设填充；只在用户给了配色/字体/品牌规则时部分覆盖 |
| `global_style_block` | ❌ | 每页提示词前置的全局风格块；不写则由预设提供 |
| `content_box_rule` | ❌ | 构图安全区约束；不写用内置默认 |
| `pages` | ❌ | 不写则自动生成默认骨架 |
| `backends` | ❌ | 生图/OCR 后端设置 |
| `defaults_applied` | 输出 | 脚本回写的"补了哪些默认值"清单 |

## 二、meta

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `title` | `【待补】主题` | 主标题，也用于产出文件名 |
| `subtitle` | brief 首行截断 | 副标题 |
| `slug` | 由 title 生成 | 运行目录名后缀 |
| `language` | 有中文则 `zh-CN`，否则 `en-US` | 提示词与文案语言 |
| `audience` | `通用受众` | 面向谁 |
| `purpose` | `分享` | 用途 |
| `duration_min` | `page_count`（最小 5） | 讲多久 |
| `page_count` | `10`，钳制 3–40；若给了 `pages` 则以 `pages` 长度为准 | 总页数 |
| `aspect` | `16:9` | 画幅 |
| `resolution` | `2K` | 原生支持分辨率的后端用它（如 OpenRouter images） |
| `speaker_notes` | `true` | 是否写讲者备注 |

## 三、theme_lock

| 键 | 含义 |
| --- | --- |
| `canvas` | 画布与渲染尺寸 |
| `base` | 基底颜色/渐变 |
| `accents` | 强调色与使用比例 |
| `surfaces` | 卡片/材质规格（圆角、填充、描边、投影） |
| `lighting` | 光照与氛围 |
| `layout` | 网格、页边距、留白要求 |
| `typography` | 对象：`cjk_font` / `latin_font` / `title_px` / `card_title_px` / `body_px` / `caption_px` / `letter_spacing` / `min_body_px` |
| `visual_anchors` | 视觉锚点（3D 物、图标风格等） |
| `chart_language` | 图表语言与禁用图表类型 |
| `logo_rule` | Logo 占位规则（一律不生成真实 Logo） |
| `rhythm` | 页间节奏变化规则 |
| `negative` | 全局负向约束数组，会继承到每一页 |

## 四、pages[]

| 字段 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `index` | ❌ | 顺序号 | 1 起 |
| `role` | ❌ | `content` | `cover` / `overview` / `section` / `content` / `summary` / `next` |
| `title` | ✅ | `第 N 页` | ≤ 18 字 |
| `objective` | ❌ | 通用句 | 这一页要让观众得到什么 |
| `core_text` | ✅ | `【待补】…` | 3–4 条，每条 ≤ 20 字，会被逐个送进提示词并用于 QA 文本比对 |
| `layout` | ❌ | `左右对照` | 版式结构 |
| `visual_elements` | ❌ | 通用句 | 画面里出现什么、怎么标注 |
| `style_hint` | ❌ | 由 theme_lock 生成 | 该页的风格提示词一句 |
| `logo_rule` | ❌ | 继承 theme_lock | Logo 规则 |
| `negative` | ❌ | 继承 theme_lock | 该页额外的负向约束 |
| `notes` | ❌ | 按 role 生成的通用讲稿 | 讲者备注，3–4 句口语 |

## 五、backends

```json
{
  "image": {
    "provider": "openai-images | chat-image | openrouter-images | editppt-cli",
    "model": "gpt-image-2",
    "size": "1536x1024",
    "quality": "medium",
    "fit": "auto",
    "api_mode": "images",
    "concurrency": 3
  },
  "ocr": { "provider": "paddleocr-vl" }
}
```

`fit` 只对没有原生 16:9 的后端生效：`auto`（内容能进就裁切，否则模糊羽化补边）/ `pad` / `crop` / `none`。

## 六、自动生成的默认页面骨架

页数 N 时 roles = `cover, overview, [content]×(N-4), summary, next`；`N=3` → `cover, overview, summary`；
`N=2` → `cover, summary`；`N=1` → `cover`。骨架里的 `core_text` 一律是 `【待补】…`，
提醒用户或 agent 去补真实内容——**不要用编造的内容替换它**。

## 七、最小可用示例

```json
{
  "schema_version": 1,
  "brief": "给大学生讲 Transformer，科技风，10 页，课堂分享",
  "meta": { "title": "Transformer 从注意力到大模型", "audience": "计算机专业大三学生",
            "purpose": "课堂技术分享", "page_count": 3 },
  "pages": [
    { "index": 1, "role": "cover", "title": "Transformer：从注意力到大模型基石",
      "objective": "3 秒建立高质量技术分享的第一印象",
      "core_text": ["从注意力机制到大模型基石", "2017 → 2025 · 原理/架构/实战", "共 3 页看懂"],
      "layout": "封面（左标题区 + 右视觉锚点）",
      "visual_elements": "右侧悬浮玻璃圆环，左上体积光束",
      "notes": "开场先问一句：今天的大模型底座到底是什么？然后用 3 页把它讲清楚。" },
    { "index": 2, "role": "content", "title": "一图看懂整体结构",
      "objective": "理解编码器/解码器分工", "core_text": ["编码器 ×6：自注意力+前馈", "解码器 ×6：多一层交叉注意力", "输入=词嵌入+位置编码"],
      "layout": "链路图 + 三张说明卡", "visual_elements": "两列玻璃模块堆叠，中间青色交叉连线",
      "notes": "先给全景：左边理解输入、右边生成输出，全靠注意力连起来。" },
    { "index": 3, "role": "summary", "title": "三句话总结",
      "objective": "收束成可带走的结论", "core_text": ["注意力是唯一核心零件", "残差+归一化让深层可训", "位置编码注入顺序信息"],
      "layout": "三张总结卡", "visual_elements": "三张并列卡片，底部一条水平光带",
      "notes": "收尾逐句复述三句话，然后进入提问环节。" }
  ]
}
```
