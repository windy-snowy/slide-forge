#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""spec_model 的单元测试：默认值填充、预设路由、页面骨架、渲染与提示词拼装。"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import spec_model as sm  # noqa: E402


class TestPresets(unittest.TestCase):
    def test_presets_load(self):
        presets = sm.load_presets()
        self.assertIn("aurora-glass", presets)
        self.assertIn("clean-corporate", presets)
        for name, data in presets.items():
            for key in ("label", "description", "keywords", "theme_lock", "global_style_block"):
                self.assertIn(key, data, f"{name} 缺 {key}")
            for key in ("canvas", "base", "accents", "surfaces", "lighting", "layout",
                        "typography", "visual_anchors", "chart_language", "logo_rule", "rhythm",
                        "negative"):
                self.assertIn(key, data["theme_lock"], f"{name}.theme_lock 缺 {key}")

    def test_route_by_keyword(self):
        self.assertEqual(sm.route_preset("给大学生讲 Transformer 的科技风 PPT")[0], "aurora-glass")
        self.assertEqual(sm.route_preset("论文答辩用的学术汇报")[0], "academic-paper")
        self.assertEqual(sm.route_preset("双十一营销活动策划")[0], "vivid-marketing")

    def test_route_fallback(self):
        self.assertEqual(sm.route_preset("随便一份材料")[0], sm.DEFAULT_PRESET)

    def test_explicit_preset_wins(self):
        self.assertEqual(sm.route_preset("科技风", "clean-corporate")[0], "clean-corporate")

    def test_unknown_preset_fails(self):
        with self.assertRaises(SystemExit):
            sm.route_preset("x", "no-such-preset")


class TestDefaults(unittest.TestCase):
    def test_page_count_default_is_ten(self):
        spec, applied = sm.fill_defaults(sm.new_spec("给我做个 PPT"))
        self.assertEqual(spec["meta"]["page_count"], 10)
        self.assertEqual(len(spec["pages"]), 10)
        self.assertTrue(any("page_count" in item for item in applied))

    def test_page_count_clamped(self):
        spec, _ = sm.fill_defaults(sm.new_spec("做个 PPT", page_count=99))
        self.assertEqual(spec["meta"]["page_count"], 40)
        spec, _ = sm.fill_defaults(sm.new_spec("做个 PPT", page_count=1))
        self.assertEqual(len(spec["pages"]), 3)

    def test_theme_lock_filled_from_preset(self):
        spec, _ = sm.fill_defaults(sm.new_spec("学术答辩", page_count=3))
        self.assertEqual(spec["preset"], "academic-paper")
        self.assertTrue(spec["theme_lock"]["base"])
        self.assertTrue(spec["theme_lock"]["negative"])
        self.assertTrue(spec["global_style_block"])

    def test_user_override_is_kept(self):
        raw = sm.new_spec("学术答辩", page_count=3)
        raw["theme_lock"] = {"accents": "主色 #123456"}
        spec, _ = sm.fill_defaults(raw)
        self.assertEqual(spec["theme_lock"]["accents"], "主色 #123456")
        self.assertTrue(spec["theme_lock"]["base"], "未覆盖的字段仍要被补齐")

    def test_every_page_gets_negative_and_notes(self):
        spec, _ = sm.fill_defaults(sm.new_spec("公司季度复盘汇报", page_count=6))
        for page in spec["pages"]:
            self.assertTrue(page["negative"])
            self.assertTrue(page["notes"])
            self.assertTrue(page["core_text"])
            self.assertTrue(page["style_hint"])

    def test_no_fabricated_content_in_skeleton(self):
        spec, _ = sm.fill_defaults(sm.new_spec("讲一个我还没想好的主题", page_count=8))
        body = " ".join(text for page in spec["pages"] for text in page["core_text"])
        self.assertIn("【待补】", body)


class TestSkeleton(unittest.TestCase):
    def test_roles_for_various_page_counts(self):
        self.assertEqual(sm.default_roles(1), ["cover"])
        self.assertEqual(sm.default_roles(2), ["cover", "summary"])
        self.assertEqual(sm.default_roles(3), ["cover", "overview", "summary"])
        self.assertEqual(sm.default_roles(4), ["cover", "overview", "content", "summary"])
        roles = sm.default_roles(10)
        self.assertEqual(len(roles), 10)
        self.assertEqual(roles[0], "cover")
        self.assertEqual(roles[-1], "next")

    def test_skeleton_length_matches(self):
        for n in (3, 4, 5, 7, 12):
            self.assertEqual(len(sm.skeleton_pages({"title": "T", "audience": "A",
                                                    "purpose": "P", "duration_min": n}, n)), n)


class TestRendering(unittest.TestCase):
    def setUp(self):
        self.spec, _ = sm.fill_defaults(sm.new_spec("给大学生讲 Transformer，科技风，3 页", page_count=3))

    def test_page_prompt_order(self):
        prompt = sm.page_prompt(self.spec, self.spec["pages"][0])
        self.assertTrue(prompt.startswith(self.spec["global_style_block"].strip()[:20]))
        self.assertIn(self.spec["content_box_rule"].strip()[:20], prompt)
        self.assertIn("页面标题：", prompt)
        self.assertIn("负向约束：", prompt)
        self.assertTrue(prompt.rstrip().endswith("画幅要求：16:9 横版整页幻灯片。"))

    def test_prompt_files_fields(self):
        block = sm.page_block(self.spec["pages"][0])
        for field in sm.PAGE_FIELDS:
            self.assertIn(field, block)

    def test_markdown_sections(self):
        markdown = sm.render_markdown(self.spec)
        for heading in ("## 一、风格锁定（Theme Lock v1）", "## 二、全局风格块",
                        "## 三、逐页提示词", "## 四、执行记录"):
            self.assertIn(heading, markdown)
        self.assertIn("| 维度 | 规格 |", markdown)
        self.assertEqual(markdown.count("### 第 "), 3)

    def test_markdown_escapes_pipes(self):
        spec, _ = sm.fill_defaults(sm.new_spec("测试", page_count=3))
        spec["theme_lock"]["base"] = "白 | 黑"
        self.assertIn("白 \\| 黑", sm.render_markdown(spec))


class TestBriefHints(unittest.TestCase):
    def test_page_count_from_brief(self):
        self.assertEqual(sm.parse_hints("给大学生讲 Transformer，10 页")["page_count"], 10)
        self.assertEqual(sm.parse_hints("做个 5 页的 PPT")["page_count"], 5)

    def test_duration_from_brief(self):
        self.assertEqual(sm.parse_hints("约 20 分钟的分享")["duration_min"], 20)

    def test_audience_from_brief(self):
        self.assertEqual(sm.parse_hints("给大学生讲 Transformer")["audience"], "大学生")

    def test_purpose_from_brief(self):
        self.assertEqual(sm.parse_hints("用于课堂分享")["purpose"], "课堂分享")

    def test_no_hints(self):
        self.assertEqual(sm.parse_hints("随便做一份"), {})

    def test_new_spec_applies_hints(self):
        spec = sm.new_spec("给大学生讲 Transformer，科技风，3 页，用于课堂分享，约 20 分钟")
        self.assertEqual(spec["meta"]["page_count"], 3)
        self.assertEqual(spec["meta"]["duration_min"], 20)
        self.assertEqual(spec["meta"]["audience"], "大学生")

    def test_explicit_override_beats_hint(self):
        spec = sm.new_spec("3 页的 PPT", page_count=7)
        self.assertEqual(spec["meta"]["page_count"], 7)

    def test_fill_defaults_keeps_hint(self):
        spec, _ = sm.fill_defaults(sm.new_spec("做 6 页的汇报 PPT"))
        self.assertEqual(spec["meta"]["page_count"], 6)
        self.assertEqual(len(spec["pages"]), 6)


class TestSlug(unittest.TestCase):
    def test_slug_from_cjk(self):
        self.assertTrue(sm.slugify("Transformer 玻璃拟态"))

    def test_slug_fallback(self):
        self.assertEqual(sm.slugify("", fallback="deck"), "deck")

    def test_slug_is_safe(self):
        slug = sm.slugify("A/B:C *D* 测试")
        self.assertNotIn("/", slug)
        self.assertNotIn(":", slug)
        self.assertNotIn(" ", slug)


if __name__ == "__main__":
    unittest.main()
