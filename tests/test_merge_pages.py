#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_pages 的单元测试：单页 run 发现、合并清单生成、备注注入、上游定位与降级。"""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import merge_pages as mp  # noqa: E402


def fake_part(root, part, page_dir_name="page_001", text="标题"):
    """造一个最小可用的单页 run 产物目录。"""
    page_dir = os.path.join(root, part, "pages", page_dir_name)
    os.makedirs(page_dir, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "slide": {"width": 13.333, "height": 7.5, "background": "#05060A", "size_mode": "wide"},
        "content_box": {"left": 0, "top": 0, "width": 13.333, "height": 7.5, "fit": "contain"},
        "source": {"path": "source.png", "width_px": 1536, "height_px": 864},
        "text_boxes": [{"text": text, "box_px": [100, 100, 400, 80], "font_size": 32.0,
                        "font": "Microsoft YaHei", "color": "FFFFFF", "z_index": 5}],
        "shapes": [], "images": [], "tables": [],
    }
    with open(os.path.join(page_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False)
    with open(os.path.join(page_dir, "page.pptx"), "wb") as fh:
        fh.write(b"fake")
    with open(os.path.join(page_dir, "source.png"), "wb") as fh:
        fh.write(b"fake")
    return page_dir


class TestListParts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sf-merge-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_discovers_sorted_parts(self):
        for part in ("p03", "p01", "p02"):
            fake_part(self.tmp, part)
        parts = mp.list_parts(self.tmp)
        self.assertEqual([p["part"] for p in parts], ["p01", "p02", "p03"])

    def test_ignores_dirs_without_manifest(self):
        fake_part(self.tmp, "p01")
        os.makedirs(os.path.join(self.tmp, "p02", "pages", "page_001"), exist_ok=True)
        self.assertEqual(len(mp.list_parts(self.tmp)), 1)

    def test_rejects_multi_page_part(self):
        fake_part(self.tmp, "p01")
        fake_part(self.tmp, "p01", page_dir_name="page_002")
        with self.assertRaises(SystemExit):
            mp.list_parts(self.tmp)

    def test_empty_dir(self):
        self.assertEqual(mp.list_parts(self.tmp), [])


class TestBuildMerged(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sf-merged-")
        self.parts_root = os.path.join(self.tmp, "parts")
        fake_part(self.parts_root, "p01", text="第一页")
        fake_part(self.parts_root, "p02", text="第二页")
        self.spec = {"pages": [{"index": 1, "title": "A", "notes": "讲第一页"},
                               {"index": 2, "title": "B", "notes": "讲第二页"}]}
        self.merged_dir = os.path.join(self.tmp, "merged")
        self.pptx = os.path.join(self.tmp, "out.pptx")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deck_manifest_shape(self):
        result = mp.build_merged(mp.list_parts(self.parts_root), self.spec, self.merged_dir,
                                 self.pptx, source="/tmp/spec.json")
        with open(result["deck_manifest"], encoding="utf-8") as fh:
            deck = json.load(fh)
        self.assertEqual(deck["page_count"], 2)
        self.assertEqual(deck["job_dir"], os.path.abspath(self.merged_dir))
        self.assertEqual(deck["notes_manifest"], "notes_manifest.json")
        self.assertEqual(deck["output"], os.path.abspath(self.pptx))
        self.assertEqual([p["manifest"] for p in deck["pages"]],
                         ["pages/page_001/manifest.json", "pages/page_002/manifest.json"])
        self.assertEqual(deck["merge"]["sources"], ["p01", "p02"])

    def test_page_dirs_resolve_to_real_manifests(self):
        result = mp.build_merged(mp.list_parts(self.parts_root), self.spec, self.merged_dir,
                                 self.pptx)
        with open(result["deck_manifest"], encoding="utf-8") as fh:
            deck = json.load(fh)
        root = deck["job_dir"]
        for page in deck["pages"]:
            path = os.path.join(root, page["manifest"])
            self.assertTrue(os.path.isfile(path), f"manifest 未解析：{path}")
        self.assertEqual(result["pages"], 2)

    def test_notes_manifest_indexed(self):
        result = mp.build_merged(mp.list_parts(self.parts_root), self.spec, self.merged_dir,
                                 self.pptx)
        with open(result["notes_manifest"], encoding="utf-8") as fh:
            notes = json.load(fh)
        self.assertEqual([n["page_index"] for n in notes["notes"]], [1, 2])
        self.assertEqual(notes["notes"][0]["text"], "讲第一页")
        self.assertEqual(result["notes"], 2)

    def test_notes_skipped_when_empty(self):
        result = mp.build_merged(mp.list_parts(self.parts_root), {"pages": []}, self.merged_dir,
                                 self.pptx)
        with open(result["notes_manifest"], encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["notes"], [])

    def test_rebuild_replaces_previous_links(self):
        parts = mp.list_parts(self.parts_root)
        mp.build_merged(parts, self.spec, self.merged_dir, self.pptx)
        mp.build_merged(parts[:1], self.spec, self.merged_dir, self.pptx)
        with open(os.path.join(self.merged_dir, "deck_manifest.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["page_count"], 1)
        self.assertFalse(os.path.exists(os.path.join(self.merged_dir, "pages", "page_002")))

    def test_build_and_validate_degrades_when_runtime_missing(self):
        original = mp._find_runtime
        mp._find_runtime = lambda: (None, None, [])
        try:
            result = mp.build_and_validate(mp.list_parts(self.parts_root), self.spec,
                                           self.merged_dir, self.pptx)
        finally:
            mp._find_runtime = original
        self.assertFalse(result["ok"])
        self.assertIn("降级方案", result["reason"])
        # 合并清单仍然写出来了，便于人工接管
        self.assertTrue(os.path.isfile(result["deck_manifest"]))


class TestLocators(unittest.TestCase):
    def test_guard_shape(self):
        runtime, label, tried = mp.guard()
        self.assertIsInstance(tried, list)
        if runtime:
            self.assertTrue(os.path.isfile(os.path.join(runtime, "build_pptx_from_manifest.py")))
            self.assertTrue(os.path.isfile(os.path.join(runtime, "validate_pptx.py")))

    def test_find_skill_dir_shape(self):
        skill_dir, tried = mp.find_skill_dir()
        self.assertIsInstance(tried, list)
        if skill_dir:
            self.assertTrue(os.path.isfile(os.path.join(skill_dir, "SKILL.md")))


if __name__ == "__main__":
    unittest.main()
