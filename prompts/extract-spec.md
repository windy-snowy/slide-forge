# 把用户描述转成 deck_spec.json

你的任务：把用户的一段文字描述（可能带参考文件/参考文本）转成 **一份合法 JSON**，写到
`<run>/deck_spec.json`。**只填你能从用户材料里确证的信息**，其余全部留空，交给
`python3 scripts/deck.py spec render` 用默认值补齐（脚本会告诉你补了什么）。

## 一、硬性规则

1. **只输出 JSON**，不要 Markdown 代码围栏、不要注释、不要解释文字。
2. **不编造事实**：任何用户没给的数据、数字、结论、引用，一律写成 `【待补】…`。
3. `schema_version` 固定为 `1`；顶层必须有 `brief`（用户原话，尽量完整保留）。
4. `pages` 的条数必须等于 `meta.page_count`；页面标题不超过 18 字，`core_text` 每页 3–4 条、每条不超过 20 字。
5. **不要手写 `theme_lock` / `global_style_block` / `logo_rule` / `negative`**——这些由预设提供。
   只有当用户明确给出了配色、字体、品牌色或禁用项时，才写进 `theme_lock` 对应字段（见 §三）。
6. 每页 `notes` 写 3–4 句口语讲稿（开场怎么说、这一页怎么过渡到下一页），不要写书面语摘要。
7. 只有用户明确说了风格关键词时才写 `preset`；否则不写，让脚本按关键词路由。

## 二、输出结构（按需省略字段）

```json
{
  "schema_version": 1,
  "brief": "<用户原话>",
  "preset": "aurora-glass | clean-corporate | academic-paper | vivid-marketing",
  "meta": {
    "title": "<主标题>",
    "subtitle": "<副标题，可空>",
    "audience": "<面向谁，如：计算机专业大三学生>",
    "purpose": "<用途，如：课堂技术分享>",
    "duration_min": 10,
    "page_count": 10,
    "language": "zh-CN"
  },
  "pages": [
    {
      "index": 1,
      "role": "cover | overview | section | content | summary | next",
      "title": "……",
      "objective": "这一页要让观众得到什么（一句话）",
      "core_text": ["要点一", "要点二", "要点三"],
      "layout": "版式结构，如：左右对照 / 三卡并列 / 链路图 / 时间轴 / 仪表盘",
      "visual_elements": "画面里出现什么图形、怎么标注",
      "notes": "讲者备注 3–4 句"
    }
  ]
}
```

## 三、可选覆盖（仅当用户明确要求）

```json
{
  "theme_lock": {
    "accents": "主色 #1D4ED8，辅色 #F59E0B",
    "typography": { "title_px": 84, "body_px": 34 },
    "logo_rule": "右上角放品牌色块占位，不生成真实 Logo",
    "negative": ["不要卡通插画", "不要 3D 立体图表"]
  }
}
```

## 四、页数不够或用户没说

- 用户没说页数：`page_count` 留空（脚本默认 10）。
- 用户给的素材不足以填满页数：**不要注水**。信息不足的页把 `core_text` 写成 `【待补】…`，
  并在 `objective` 里写清"这一页需要用户补充什么"。
- 叙事骨架默认：封面 → 总览 → 内容页 → 总结 → 下一步；需要目录页时把某页 `role` 设为 `section`。

## 五、参考文件

用户给了 PDF/DOCX/MD 等参考材料时：

1. 先提取它的结构（章节、论点、数据、图表标题）；
2. 把材料里的**事实与数字原样搬进** `core_text`，不要改写数值；
3. 材料里的图用一句话描述进 `visual_elements`（例：`图 1 位置，展示 Q3 留存率下滑曲线`）；
4. 材料没覆盖但用户主题要求的部分，用 `【待补】` 占位。

## 六、自检（写文件前逐条过一遍）

- [ ] JSON 能被 `json.load` 解析（可以先 `python3 -c "import json;json.load(open('deck_spec.json'))"` 验证）
- [ ] `meta.page_count` 与 `pages` 长度一致（或都不写）
- [ ] 没有手写的 `theme_lock` / `global_style_block`（除非用户明确要求）
- [ ] 所有数字都能在用户材料里找到出处，否则是 `【待补】`
- [ ] 每页 `notes` 都是口语稿，不是正文复制
