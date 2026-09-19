#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能契约测试：SKILL.md frontmatter、资源索引、文档内引用的文件都存在。

这些断言防止"文档里写了、文件却没建"这类只在用户点开时才会暴露的问题。
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def read(relative):
    with open(os.path.join(ROOT, relative), encoding="utf-8") as fh:
        return fh.read()


class TestSkillFrontmatter(unittest.TestCase):
    def test_frontmatter_present(self):
        text = read("SKILL.md")
        self.assertTrue(text.startswith("---\n"), "SKILL.md 必须以 frontmatter 开头")
        block = text.split("---", 2)[1]
        self.assertIn("name: slide-forge", block)
        self.assertRegex(block, r"description:\s*\S{20,}")

    def test_name_is_kebab_case(self):
        block = read("SKILL.md").split("---", 2)[1]
        name = re.search(r"name:\s*(\S+)", block).group(1)
        self.assertRegex(name, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class TestResourceIndex(unittest.TestCase):
    def test_every_referenced_resource_exists(self):
        text = read("SKILL.md")
        refs = set(re.findall(r"`((?:scripts|references|prompts|docs)/[A-Za-z0-9_./\-]+)`", text))
        self.assertTrue(refs, "SKILL.md 的资源索引不应为空")
        missing = [ref for ref in sorted(refs) if not os.path.isfile(os.path.join(ROOT, ref))]
        self.assertEqual(missing, [], f"SKILL.md 引用了不存在的文件：{missing}")

    def test_presets_directory_glob_exists(self):
        self.assertTrue(os.path.isdir(os.path.join(ROOT, "references", "presets")))


class TestDocsLinks(unittest.TestCase):
    def test_relative_markdown_links_resolve(self):
        missing = []
        for relative in ("SKILL.md", "README.md", "README.en.md", "docs/workflow.md",
                         "docs/faq.md", "docs/PUBLISH-TO-GITHUB.md",
                         "references/editable-pipeline.md", "references/subagent-strategy.md",
                         "examples/transformer-glass/README.md"):
            text = read(relative)
            base = os.path.dirname(os.path.join(ROOT, relative))
            for link in re.findall(r"\[[^\]]+\]\(([^)#][^)]*)\)", text):
                if link.startswith(("http", "mailto", "#")) or "<" in link:
                    continue
                if not os.path.exists(os.path.normpath(os.path.join(base, link))):
                    missing.append(f"{relative} -> {link}")
        self.assertEqual(missing, [], f"失效的相对链接：{missing}")


class TestExample(unittest.TestCase):
    def test_example_spec_is_valid_and_consistent(self):
        import json
        spec = json.loads(read("examples/transformer-glass/deck_spec.json"))
        self.assertEqual(spec["schema_version"], 1)
        self.assertEqual(len(spec["pages"]), spec["meta"]["page_count"])
        for index, page in enumerate(spec["pages"], 1):
            self.assertEqual(page["index"], index)
            self.assertTrue(page["core_text"])
            self.assertTrue(page["notes"])

    def test_example_assets_exist(self):
        for index in range(1, 11):
            path = os.path.join(ROOT, "examples", "transformer-glass", "images", f"p{index:02d}.jpg")
            self.assertTrue(os.path.isfile(path), f"缺示例图 {path}")


class TestNoSecretsInTrackedText(unittest.TestCase):
    def test_source_tree_has_no_hardcoded_keys(self):
        pattern = re.compile(r"sk-[A-Za-z0-9_\-]{16,}")
        offenders = []
        for base, _dirs, files in os.walk(ROOT):
            if ".git" in base.split(os.sep):
                continue
            for name in files:
                if not name.endswith((".py", ".md", ".json", ".sh", ".yml")):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    if pattern.search(fh.read()):
                        offenders.append(os.path.relpath(path, ROOT))
        self.assertEqual(offenders, [], f"疑似硬编码密钥：{offenders}")


if __name__ == "__main__":
    unittest.main()
