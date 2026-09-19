#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slide-forge 规格模型（spec_model）。

职责：
  1. 加载 references/presets/*.json 风格预设；
  2. 把用户描述对应的 deck_spec 补全默认值（页数、风格、版式、负向约束、备注……）；
  3. 生成与「风格锁定与每页提示词.md」同构的提示词文档；
  4. 拼装逐页最终提示词（全局风格块 + 构图安全区 + 页块 + 画幅要求）。

只依赖 Python 标准库，保证在裸环境也能跑。
"""

from __future__ import annotations

import json
import os
import re
import unicodedata

SCHEMA_VERSION = 1
HERE = os.path.dirname(os.path.abspath(__file__))
PRESET_DIR = os.path.join(os.path.dirname(HERE), "references", "presets")

DEFAULT_PRESET = "clean-corporate"

# 主题锁定表的展示顺序与中文标签
THEME_ROWS = [
    ("canvas", "画布"),
    ("base", "基底"),
    ("accents", "强调色"),
    ("surfaces", "卡片 / 材质"),
    ("lighting", "光照"),
    ("layout", "版式"),
    ("typography", "字体"),
    ("visual_anchors", "视觉锚点"),
    ("chart_language", "图表语言"),
    ("logo_rule", "Logo 规则"),
    ("rhythm", "节奏变化"),
]

ROLE_LABEL = {
    "cover": "封面",
    "overview": "总览",
    "section": "章节",
    "content": "内容",
    "summary": "总结",
    "next": "下一步",
}

# 每页提示词块固定字段（与参考模板一致）
PAGE_FIELDS = ["页面标题", "页面目标", "核心文字", "版式结构", "视觉元素", "风格提示词", "Logo 规则", "负向约束"]

DEFAULT_CONTENT_BOX_RULE = (
    "【构图安全区（重要）】所有文字与图形必须集中在画面中间的 16:9 区域内，"
    "上下各留出至少 12% 的空白，任何元素都不得贴边；顶部大标题整行必须完整可见，"
    "所有中文逐字正确，不得出现错别字、伪汉字或乱码。"
)

DEFAULT_ASPECT = "16:9"
# gpt-image 系列没有原生 16:9，必须先出图再适配；原生支持 16:9 的模型走 aspect_ratio。
PROVIDER_DEFAULT_SIZE = {
    "openai-images": "1536x1024",
    "chat-image": "1536x1024",
    "editppt-cli": "1536x1024",
    "openrouter-images": "1K",
}


# --------------------------------------------------------------------------- #
# 预设
# --------------------------------------------------------------------------- #
def load_presets() -> dict:
    presets = {}
    if not os.path.isdir(PRESET_DIR):
        return presets
    for name in sorted(os.listdir(PRESET_DIR)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(PRESET_DIR, name), encoding="utf-8") as fh:
            data = json.load(fh)
        presets[data.get("name") or os.path.splitext(name)[0]] = data
    return presets


def route_preset(brief: str, preset: str | None = None) -> tuple[str, str]:
    """按关键词把描述路由到预设；返回 (preset_name, reason)。"""
    presets = load_presets()
    if preset:
        if preset in presets:
            return preset, "用户指定"
        raise SystemExit(f"未知风格预设：{preset}；可用：{', '.join(sorted(presets))}")
    text = (brief or "").lower()
    best, best_hits = None, 0
    for name, data in presets.items():
        hits = sum(1 for kw in data.get("keywords", []) if kw.lower() in text)
        if hits > best_hits:
            best, best_hits = name, hits
    if best:
        return best, f"按关键词命中 {best_hits} 个"
    return DEFAULT_PRESET, "未命中关键词，回退默认"


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def slugify(text: str, fallback: str = "deck", maxlen: int = 40) -> str:
    text = (text or "").strip()
    ascii_part = re.sub(r"[^0-9a-zA-Z]+", "-", unicodedata.normalize("NFKD", text)
                        .encode("ascii", "ignore").decode("ascii")).strip("-").lower()
    cjk = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    slug = ascii_part or cjk[:16] or fallback
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return (slug[:maxlen] or fallback)


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def default_roles(n: int) -> list:
    """默认叙事骨架：封面 + 总览 + 内容页 + 总结 + 下一步。"""
    if n <= 1:
        return ["cover"]
    if n == 2:
        return ["cover", "summary"]
    if n == 3:
        return ["cover", "overview", "summary"]
    if n == 4:
        return ["cover", "overview", "content", "summary"]
    return ["cover", "overview"] + ["content"] * (n - 4) + ["summary", "next"]


def skeleton_pages(meta: dict, n: int) -> list:
    """当用户没给页面清单时，自动生成一个可用的默认骨架（不虚构事实）。"""
    roles = default_roles(n)
    title = meta.get("title") or "【待补】主题"
    pages = []
    content_no = 0
    for idx, role in enumerate(roles, 1):
        if role == "cover":
            title_text = title
            objective = "让观众 3 秒内建立对主题的整体印象，并记住标题与用途。"
            body = [meta.get("subtitle") or "【待补】副标题",
                    f"{meta.get('audience')} · {meta.get('purpose')}",
                    f"共 {n} 页 · 约 {meta.get('duration_min')} 分钟"]
            layout = "封面（左侧标题区 + 右侧主题视觉 + 底部信息条）"
            visual = "右侧一个与主题相关的沉浸式视觉锚点；背景大面积留白，标题层级分明。"
        elif role == "overview":
            title_text = f"一图看懂：{title}"
            objective = "用一页交代整体结构，让观众知道接下来会看到什么。"
            body = ["【待补】整体结构", "【待补】关键结论", "【待补】阅读路径"]
            layout = "链路图 / 矩阵（左侧结构图 + 右侧三张说明卡）"
            visual = "一条从起点到终点的结构链路，节点用图形或卡片表示，配三条简短说明。"
        elif role == "content":
            content_no += 1
            title_text = f"要点 {content_no}：【待补】"
            objective = "讲清本页唯一的一个信息焦点，并给出支撑证据。"
            body = ["【待补】要点 1", "【待补】要点 2", "【待补】要点 3"]
            layout = "左右对照 或 三卡并列（按内容选择，与相邻页不同构）"
            visual = "一张能独立说明问题的图（示意 / 数据图 / 流程），配简短中文标注。"
        elif role == "summary":
            title_text = "三句话总结"
            objective = "把整场分享收束成观众可以带走的结论。"
            body = ["【待补】结论一", "【待补】结论二", "【待补】结论三"]
            layout = "三张总结卡 + 一条时间轴或一条主色带"
            visual = "三张并列卡片，每张一句话；底部一条水平轴线收束画面。"
        else:  # next
            title_text = "下一步"
            objective = "给出明确的下一步行动，让观众知道该做什么。"
            body = ["【待补】行动项一", "【待补】行动项二", "【待补】行动项三"]
            layout = "结束页（三项行动 + 一个醒目的行动按钮）"
            visual = "一条醒目的胶囊按钮或色块，突出下一步动作。"
        pages.append({
            "index": idx,
            "role": role,
            "title": title_text,
            "objective": objective,
            "core_text": body,
            "layout": layout,
            "visual_elements": visual,
            "style_hint": "",
            "logo_rule": "",
            "negative": [],
            "notes": _default_note(role, title),
        })
    return pages


def _default_note(role: str, title: str) -> str:
    if role == "cover":
        return f"开场：用一句话说明为什么要讲「{title}」，以及观众听完能带走什么。控制在 30 秒内。"
    if role == "overview":
        return "先给全景：这份内容分成几个部分、逻辑主线是什么，让观众建立地图感。"
    if role == "content":
        return "本页只讲一个焦点：先给结论，再给证据，最后用一句话回到主题。"
    if role == "summary":
        return "收束：把全篇归纳成三句话，逐句复述，不要引入新信息。"
    return "给出明确的下一步动作，并留出提问时间。"


def content_box_rule() -> str:
    return DEFAULT_CONTENT_BOX_RULE


# --------------------------------------------------------------------------- #
# 默认值填充
# --------------------------------------------------------------------------- #
def fill_defaults(spec: dict) -> tuple[dict, list]:
    """把缺失字段补成默认值。返回 (spec, 本次补上的字段说明列表)。"""
    spec = json.loads(json.dumps(spec or {}))  # deep copy
    applied: list = []

    version = spec.get("schema_version", SCHEMA_VERSION)
    if int(version) != SCHEMA_VERSION:
        raise SystemExit(f"不支持的 schema_version：{version}（本工具为 {SCHEMA_VERSION}）")
    spec["schema_version"] = SCHEMA_VERSION

    brief = spec.get("brief") or ""
    meta = spec.setdefault("meta", {})

    def d(key, value, label=None):
        if meta.get(key) in (None, "", [], {}):
            meta[key] = value
            applied.append(label or f"meta.{key}")

    d("title", "【待补】主题", "meta.title（从描述首句提取）")
    d("subtitle", "")
    d("language", _detect_language(brief), "meta.language")
    d("audience", "通用受众")
    d("purpose", "分享")
    try:
        n = int(meta.get("page_count") or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        n = 10
        applied.append("meta.page_count")
    n = max(3, min(40, n))
    meta["page_count"] = n
    d("duration_min", max(5, n))
    d("aspect", DEFAULT_ASPECT)
    d("resolution", "2K")
    d("speaker_notes", True)
    d("slug", slugify(meta.get("title") or brief), "meta.slug")
    if not meta.get("subtitle"):
        meta["subtitle"] = brief.strip().splitlines()[0][:40] if brief.strip() else ""

    # 风格预设
    preset_name, reason = route_preset(brief, spec.get("preset"))
    if not spec.get("preset"):
        applied.append(f"preset={preset_name}（{reason}）")
    spec["preset"] = preset_name
    presets = load_presets()
    preset = presets.get(preset_name)
    if preset is None:
        raise SystemExit(f"预设文件缺失：{preset_name}")

    # 主题锁定
    theme = spec.setdefault("theme_lock", {})
    for key in list(preset["theme_lock"].keys()):
        if theme.get(key) in (None, "", [], {}):
            theme[key] = preset["theme_lock"][key]
            applied.append(f"theme_lock.{key}")
    theme.setdefault("negative", preset["theme_lock"].get("negative", []))

    if not spec.get("global_style_block"):
        spec["global_style_block"] = preset["global_style_block"]
        applied.append("global_style_block")
    if not spec.get("content_box_rule"):
        spec["content_box_rule"] = content_box_rule()
        applied.append("content_box_rule")

    # 页面
    pages = spec.get("pages") or []
    if not pages:
        pages = skeleton_pages(meta, n)
        applied.append("pages（自动生成默认骨架）")
    if len(pages) != n:
        applied.append(f"meta.page_count 由 {n} 校正为 {len(pages)}（以 pages 为准）")
        meta["page_count"] = len(pages)
    n = meta["page_count"]

    negative_global = _as_list(theme.get("negative"))
    for i, page in enumerate(pages, 1):
        page.setdefault("index", i)
        page["index"] = i
        page.setdefault("role", "content")
        page.setdefault("title", f"第 {i} 页")
        page.setdefault("objective", "讲清本页唯一的信息焦点。")
        page["core_text"] = _as_list(page.get("core_text")) or ["【待补】要点 1", "【待补】要点 2"]
        page.setdefault("layout", "左右对照")
        page.setdefault("visual_elements", "一张能独立说明问题的图 + 简短中文标注。")
        if not page.get("style_hint"):
            page["style_hint"] = _style_hint(theme)
            applied.append(f"pages[{i}].style_hint")
        if not page.get("logo_rule"):
            page["logo_rule"] = theme.get("logo_rule", "右上角预留干净区域，不生成任何 Logo。")
            applied.append(f"pages[{i}].logo_rule")
        page["negative"] = _as_list(page.get("negative")) or list(negative_global)
        if not page.get("notes"):
            page["notes"] = _default_note(page["role"], meta.get("title", ""))
            applied.append(f"pages[{i}].notes")
    spec["pages"] = pages

    # 后端
    backends = spec.setdefault("backends", {})
    image = backends.setdefault("image", {})
    if not image.get("provider"):
        image["provider"] = os.environ.get("SLIDEFORGE_IMAGE_PROVIDER", "openai-images")
        applied.append("backends.image.provider")
    image.setdefault("model", os.environ.get("SLIDEFORGE_IMAGE_MODEL", "gpt-image-2"))
    image.setdefault("size", PROVIDER_DEFAULT_SIZE.get(image["provider"], "1536x1024"))
    image.setdefault("quality", "medium")
    image.setdefault("fit", "auto")
    image.setdefault("api_mode", "images")
    image.setdefault("concurrency", 3)
    ocr = backends.setdefault("ocr", {})
    ocr.setdefault("provider", "paddleocr-vl")

    spec["defaults_applied"] = applied
    return spec, applied


def _detect_language(brief: str) -> str:
    cjk = sum(1 for ch in brief or "" if "\u4e00" <= ch <= "\u9fff")
    return "zh-CN" if cjk >= 2 or not (brief or "").strip() else "en-US"


def _style_hint(theme: dict) -> str:
    base = theme.get("base", "").split("（")[0]
    accents = theme.get("accents", "").split("；")[0]
    return f"16:9 整页 PPT 图片；{base}基底；强调色：{accents}；中文清晰，层级专业，留白充足。"


# --------------------------------------------------------------------------- #
# 提示词拼装与渲染
# --------------------------------------------------------------------------- #
def page_block(page: dict) -> str:
    lines = [f"页面标题：{page['title']}",
             f"页面目标：{page.get('objective', '')}",
             "核心文字（必须清晰无误）："]
    lines += [f"- {t}" for t in _as_list(page.get("core_text"))]
    lines += [f"版式结构：{page.get('layout', '')}",
              f"视觉元素：{page.get('visual_elements', '')}",
              f"风格提示词：{page.get('style_hint', '')}",
              f"Logo 规则：{page.get('logo_rule', '')}"]
    negative = _as_list(page.get("negative"))
    if negative:
        lines.append("负向约束：" + "；".join(negative) + "。")
    return "\n".join(lines)


def page_prompt(spec: dict, page: dict) -> str:
    """最终投喂生图模型的完整提示词。"""
    return "\n\n".join([
        spec["global_style_block"].strip(),
        spec.get("content_box_rule", "").strip(),
        page_block(page).strip(),
        "画幅要求：16:9 横版整页幻灯片。",
    ])


def render_markdown(spec: dict) -> str:
    meta = spec["meta"]
    presets = load_presets()
    preset = presets.get(spec.get("preset"), {})
    n = len(spec["pages"])
    out = []
    out.append(f"# {meta['title']} · 风格锁定与每页提示词")
    out.append("")
    out.append(f"> 由 **slide-forge** 从一段自然语言描述推导：先锁定统一风格（Theme Lock · "
               f"`{spec['preset']}` / {preset.get('label', '')}），再逐页给出**可直接投喂生图模型的完整提示词**。")
    out.append(f"> 受众：{meta.get('audience')}　用途：{meta.get('purpose')}　页数：{n}　"
               f"画幅：{meta.get('aspect')}　时长：约 {meta.get('duration_min')} 分钟。")
    out.append("> 想要另一套视觉，改 `deck_spec.json` 的 `preset` 后重跑 `deck.py spec render` 即可。")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 一、风格锁定（Theme Lock v1）")
    out.append("")
    out.append("| 维度 | 规格 |")
    out.append("| --- | --- |")
    theme = spec.get("theme_lock", {})
    for key, label in THEME_ROWS:
        value = theme.get(key)
        if isinstance(value, dict):
            value = _format_typography(value)
        value = str(value or "").replace("|", "\\|")
        out.append(f"| {label} | {value} |")
    out.append("")
    negative = _as_list(theme.get("negative"))
    if negative:
        out.append("**全局负向约束**：" + "；".join(negative) + "。")
        out.append("")
    out.append("---")
    out.append("")
    out.append("## 二、全局风格块（每页提示词前都要先粘贴这段）")
    out.append("")
    out.append("```text")
    out.append(spec["global_style_block"].strip())
    out.append("```")
    out.append("")
    out.append("```text")
    out.append(spec.get("content_box_rule", "").strip())
    out.append("```")
    out.append("")
    out.append("---")
    out.append("")
    out.append(f"## 三、逐页提示词（{n} 页）")
    out.append("")
    for page in spec["pages"]:
        out.append(f"### 第 {page['index']} 页 · {page['title']}"
                   f"　`{ROLE_LABEL.get(page['role'], page['role'])}`")
        out.append("")
        out.append("```text")
        out.append(page_block(page))
        out.append("```")
        out.append("")
        if page.get("notes"):
            out.append(f"> 讲者备注：{page['notes']}")
            out.append("")
    out.append("---")
    out.append("")
    out.append("## 四、执行记录")
    out.append("")
    out.append("| 页 | 标题 | 出图 | 质量闸门 |")
    out.append("| --- | --- | --- | --- |")
    for page in spec["pages"]:
        out.append(f"| {page['index']} | {page['title']} | 待生成 | 待检测 |")
    out.append("")
    out.append("> 该表由 `deck.py gen` / `deck.py qa` 在运行后回写。")
    out.append("")
    return "\n".join(out)


def _format_typography(t: dict) -> str:
    return (f"{t.get('cjk_font', '')}；拉丁同族；标题 {t.get('title_px')}px、卡片标题 "
            f"{t.get('card_title_px')}px、正文 {t.get('body_px')}px、图注 {t.get('caption_px')}px；"
            f"字距 {t.get('letter_spacing', '0%')}；正文字号下限 {t.get('min_body_px', 22)}px")


# --------------------------------------------------------------------------- #
# 读写
# --------------------------------------------------------------------------- #
def load_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_spec(spec: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def parse_hints(brief: str) -> dict:
    """从描述里抠出显而易见的数字/受众，作为默认值之外的"优先默认"。

    复杂提取交给 prompts/extract-spec.md 由 LLM 完成；这里只做最保守的几条，
    让 `deck.py all "<一句话>"` 就能给出接近预期的结果。
    """
    hints = {}
    text = brief or ""
    match = re.search(r"(\d{1,2})\s*(?:页|张|pag(?:e|es)|slides?)", text, re.I)
    if match:
        hints["page_count"] = int(match.group(1))
    match = re.search(r"(\d{1,3})\s*(?:分钟|min(?:ute)?s?)", text, re.I)
    if match:
        hints["duration_min"] = int(match.group(1))
    match = re.search(r"(?:给|面向|针对)\s*([^，。；,;！!？?]{2,20}?)\s*(?:讲|做|分享|汇报|介绍|培训|看的?|用的?)", text)
    if match:
        hints["audience"] = match.group(1).strip()
    match = re.search(r"(?:用于|用途是|目的是|场景是)\s*([^，。；,;！!？?]{2,20})", text)
    if match:
        hints["purpose"] = match.group(1).strip()
    return hints


def new_spec(brief: str, **meta_overrides) -> dict:
    """从一段描述造一份最小 spec（其余交给 fill_defaults）。"""
    first = (brief or "").strip().splitlines()[0] if (brief or "").strip() else ""
    title = re.split(r"[，。；,;.!?！？]", first)[0][:40] or "【待补】主题"
    meta = {"title": title}
    for key, value in parse_hints(brief).items():
        meta[key] = value
    for key, value in meta_overrides.items():
        if value not in (None, ""):
            meta[key] = value
    return {"schema_version": SCHEMA_VERSION, "brief": brief.strip(), "meta": meta}


if __name__ == "__main__":  # 便于手工自测
    import sys
    spec, applied = fill_defaults(new_spec(sys.argv[1] if len(sys.argv) > 1 else "给大学生讲 Transformer 的科技风 PPT"))
    print(json.dumps({"preset": spec["preset"], "pages": len(spec["pages"]),
                      "defaults_applied": applied}, ensure_ascii=False, indent=2))
