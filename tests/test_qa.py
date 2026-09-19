#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa 的单元测试：图像指标、dHash、文本保真度、闸门判定、总览图。"""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import qa as qa_mod  # noqa: E402

THRESHOLDS = dict(qa_mod.DEFAULT_THRESHOLDS)


def make_image(path, size=(1536, 864), color=(10, 14, 26), box=True, noise=True, seed=1):
    """造一张有真实熵的测试图（纯色图会小到触发 min_bytes 检查）。"""
    from PIL import Image, ImageDraw
    import numpy as np

    base = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    base[:, :] = color
    if noise:
        gradient = np.linspace(0, 60, size[0]).astype(np.int32)[None, :, None]
        base = np.clip(base.astype(np.int32) + gradient, 0, 255).astype(np.uint8)
        rng = np.random.default_rng(seed)
        base = np.clip(base.astype(np.int32) + rng.integers(0, 25, base.shape), 0, 255).astype(np.uint8)
    image = Image.fromarray(base)
    if box:
        draw = ImageDraw.Draw(image)
        draw.rectangle([60, 60, size[0] - 60, size[1] - 60], outline=(120, 160, 240), width=4)
        draw.rectangle([200, 200, size[0] - 200, 500], fill=(40, 60, 120))
    image.save(path)
    return path


class TestImageStats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sf-qa-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stats_on_16_9(self):
        path = make_image(os.path.join(self.tmp, "a.png"))
        stats = qa_mod.image_stats(path)
        self.assertEqual(stats["width"], 1536)
        self.assertEqual(stats["height"], 864)
        self.assertAlmostEqual(stats["aspect"], 16 / 9, places=3)
        self.assertGreater(stats["std"], THRESHOLDS["min_std"])
        self.assertGreater(stats["nonbg_ratio"], THRESHOLDS["min_nonbg_ratio"])

    def test_blank_image_detected(self):
        path = make_image(os.path.join(self.tmp, "blank.png"), color=(10, 14, 26), box=False,
                          noise=False)
        stats = qa_mod.image_stats(path)
        self.assertLess(stats["std"], THRESHOLDS["min_std"])

    def test_dhash_differs_for_different_images(self):
        first = qa_mod.dhash(make_image(os.path.join(self.tmp, "1.png")))
        second = qa_mod.dhash(make_image(os.path.join(self.tmp, "2.png"), color=(200, 220, 255),
                                         box=False, seed=99))
        self.assertGreater(qa_mod.hamming(first, second), THRESHOLDS["min_dhash_distance"])

    def test_dhash_same_for_same_image(self):
        path = make_image(os.path.join(self.tmp, "x.png"))
        self.assertEqual(qa_mod.hamming(qa_mod.dhash(path), qa_mod.dhash(path)), 0)


class TestTextFidelity(unittest.TestCase):
    def test_exact_match(self):
        expected = ["一图看懂 Transformer", "编码器 ×6"]
        result = qa_mod.text_fidelity(expected, expected)
        self.assertEqual(result["mean_ratio"], 1.0)
        self.assertEqual(result["line_hit_ratio"], 1.0)

    def test_whitespace_and_punct_ignored(self):
        result = qa_mod.text_fidelity(["共 3 页看懂"], ["共3页看懂。"])
        self.assertEqual(result["mean_ratio"], 1.0)

    def test_garbled_text_scores_low(self):
        result = qa_mod.text_fidelity(["缩放点积注意力"], ["锘挎斁鐐圭Н娉ㄦ剰鍔"])
        self.assertLess(result["mean_ratio"], THRESHOLDS["min_text_ratio"])

    def test_empty_expected_is_none(self):
        result = qa_mod.text_fidelity([], ["任意文字"])
        self.assertIsNone(result["mean_ratio"])
        self.assertIsNone(result["line_hit_ratio"])


class TestJudge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sf-judge-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _probe(self, name, size=(1536, 864), box=True, noise=True):
        path = make_image(os.path.join(self.tmp, name), size=size, box=box, noise=noise)
        thresholds = {**THRESHOLDS, "ocr_used": False}
        info = qa_mod.probe_page({"index": 1, "title": "T", "core_text": ["x"]}, path, use_ocr=False)
        return qa_mod.judge_page(info, thresholds, {})

    def test_good_page_passes(self):
        self.assertEqual(self._probe("good.png")["status"], "pass")

    def test_blank_page_fails(self):
        self.assertEqual(self._probe("blank.png", box=False, noise=False)["status"], "fail")

    def test_wrong_aspect_fails(self):
        self.assertEqual(self._probe("square.png", size=(1024, 1024))["status"], "fail")

    def test_too_small_fails(self):
        self.assertEqual(self._probe("small.png", size=(640, 360))["status"], "fail")

    def test_missing_file_fails(self):
        info = qa_mod.probe_page({"index": 1, "title": "T", "core_text": []},
                                 os.path.join(self.tmp, "nope.png"), use_ocr=False)
        judged = qa_mod.judge_page(info, {**THRESHOLDS, "ocr_used": False}, {})
        self.assertEqual(judged["status"], "fail")
        self.assertIn("文件不存在", judged["issues"])

    def test_duplicate_pages_fail(self):
        thresholds = {**THRESHOLDS, "ocr_used": False}
        digests = {}
        first = qa_mod.probe_page({"index": 1, "core_text": []},
                                  make_image(os.path.join(self.tmp, "d1.png")), use_ocr=False)
        second = qa_mod.probe_page({"index": 2, "core_text": []},
                                   make_image(os.path.join(self.tmp, "d2.png")), use_ocr=False)
        qa_mod.judge_page(first, thresholds, digests)
        judged = qa_mod.judge_page(second, thresholds, digests)
        self.assertEqual(judged["status"], "fail")
        self.assertTrue(any("几乎相同" in issue for issue in judged["issues"]))

    def test_ocr_missing_is_warn_not_fail(self):
        thresholds = {**THRESHOLDS, "ocr_used": True}
        info = qa_mod.probe_page({"index": 1, "core_text": ["x"]},
                                 make_image(os.path.join(self.tmp, "o.png")), use_ocr=False)
        info["ocr_lines"] = 0
        info["ocr_note"] = "未配置 PADDLE_OCR_TOKEN"
        judged = qa_mod.judge_page(info, thresholds, {})
        self.assertEqual(judged["status"], "warn")
        self.assertIn("PADDLE_OCR_TOKEN", judged["warnings"][0])

    def test_zero_hits_blames_detection_not_text(self):
        """回归：一行都没匹配上时，提示必须说"可能是分段/检出错位"，不能断言文字写错。"""
        thresholds = {**THRESHOLDS, "ocr_used": True}
        page = {"index": 1, "core_text": ["第一行", "第二行", "第三行", "第四行", "第五行"]}
        info = qa_mod.probe_page(page, make_image(os.path.join(self.tmp, "cov.png")), use_ocr=False)
        info.update({"ocr_lines": 2, "mean_ratio": 0.26, "line_hit_ratio": 0.0})
        judged = qa_mod.judge_page(info, thresholds, {})
        self.assertEqual(judged["status"], "warn")
        self.assertEqual(judged["ocr_coverage"], 0.4)
        self.assertIn("没有一行匹配核心文字", judged["warnings"][0])
        self.assertIn("请人工看图确认", judged["warnings"][0])

    def test_partial_hits_blames_text(self):
        thresholds = {**THRESHOLDS, "ocr_used": True}
        page = {"index": 1, "core_text": ["第一行", "第二行", "第三行"]}
        info = qa_mod.probe_page(page, make_image(os.path.join(self.tmp, "cov2.png")), use_ocr=False)
        info.update({"ocr_lines": 3, "mean_ratio": 0.2, "line_hit_ratio": 0.5})
        judged = qa_mod.judge_page(info, thresholds, {})
        self.assertIn("可能有错字/乱码/漏字", judged["warnings"][0])

    def test_all_lines_found_but_chars_low(self):
        thresholds = {**THRESHOLDS, "ocr_used": True}
        page = {"index": 1, "core_text": ["第一行", "第二行", "第三行"]}
        info = qa_mod.probe_page(page, make_image(os.path.join(self.tmp, "cov3.png")), use_ocr=False)
        info.update({"ocr_lines": 3, "mean_ratio": 0.7, "line_hit_ratio": 1.0})
        judged = qa_mod.judge_page(info, thresholds, {})
        self.assertIn("每行都检出了", judged["warnings"][0])

    def test_banded_retry_merges_missed_lines(self):
        """回归：整页 OCR 一行都没命中时，条带兜底应把漏掉的文字读回来。"""
        original_lines, original_banded = qa_mod.ocr_lines, qa_mod.ocr_lines_banded
        try:
            qa_mod.ocr_lines = lambda *a, **k: ([{"text": "标题"}, {"text": "底部按钮"}], "paddleocr-vl", "")
            qa_mod.ocr_lines_banded = lambda *a, **k: ([{"text": "第一行"}, {"text": "第二行"},
                                                       {"text": "第三行"}], "paddleocr-vl")
            page = {"index": 1, "core_text": ["第一行", "第二行", "第三行"]}
            info = qa_mod.probe_page(page, make_image(os.path.join(self.tmp, "band.png")), use_ocr=True)
        finally:
            qa_mod.ocr_lines, qa_mod.ocr_lines_banded = original_lines, original_banded
        self.assertEqual(info["ocr_retry"], "banded")
        self.assertEqual(info["ocr_lines"], 5)
        self.assertEqual(info["line_hit_ratio"], 1.0)
        self.assertEqual(info["mean_ratio"], 1.0)

    def test_band_retry_triggers_on_partial_hits(self):
        """行命中率不达标（漏检 1 行）时也要兜底，而不是只在 0 命中时。"""
        original_lines, original_banded = qa_mod.ocr_lines, qa_mod.ocr_lines_banded
        try:
            qa_mod.ocr_lines = lambda *a, **k: ([{"text": "樱花盛开的小路"},
                                                {"text": "夏日祭典的黄昏"}], "paddleocr-vl", "")
            qa_mod.ocr_lines_banded = lambda *a, **k: ([{"text": "纸飞机越过屋顶"}], "paddleocr-vl")
            page = {"index": 1, "core_text": ["樱花盛开的小路", "夏日祭典的黄昏", "纸飞机越过屋顶"]}
            info = qa_mod.probe_page(page, make_image(os.path.join(self.tmp, "band2.png")), use_ocr=True)
        finally:
            qa_mod.ocr_lines, qa_mod.ocr_lines_banded = original_lines, original_banded
        self.assertEqual(info.get("ocr_retry"), "banded")
        self.assertEqual(info["line_hit_ratio"], 1.0)

    def test_band_retry_skipped_when_min_disabled(self):
        original_lines, original_banded = qa_mod.ocr_lines, qa_mod.ocr_lines_banded
        try:
            qa_mod.ocr_lines = lambda *a, **k: ([{"text": "标题"}], "paddleocr-vl", "")
            qa_mod.ocr_lines_banded = lambda *a, **k: ([{"text": "第一行"}], "paddleocr-vl")
            page = {"index": 1, "core_text": ["第一行"]}
            info = qa_mod.probe_page(page, make_image(os.path.join(self.tmp, "nb.png")),
                                     use_ocr=True, band_retry=False)
        finally:
            qa_mod.ocr_lines, qa_mod.ocr_lines_banded = original_lines, original_banded
        self.assertNotIn("ocr_retry", info)
        self.assertEqual(info["ocr_lines"], 1)

    def test_low_text_ratio_is_warn(self):
        thresholds = {**THRESHOLDS, "ocr_used": True}
        info = qa_mod.probe_page({"index": 1, "core_text": ["x"]},
                                 make_image(os.path.join(self.tmp, "t.png")), use_ocr=False)
        info.update({"ocr_lines": 3, "mean_ratio": 0.2, "line_hit_ratio": 0.0})
        self.assertEqual(qa_mod.judge_page(info, thresholds, {})["status"], "warn")


class TestEvaluateAndSheet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sf-eval-")
        self.pages = [{"index": i, "title": f"第 {i} 页", "core_text": ["x"]} for i in (1, 2)]
        self.paths = {i: make_image(os.path.join(self.tmp, f"p{i}.png"),
                                    size=(1536, 864), box=i == 1) for i in (1, 2)}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_evaluate_without_ocr(self):
        report = qa_mod.evaluate(self.pages, self.paths, use_ocr=False,
                                 out_dir=os.path.join(self.tmp, "qa"))
        self.assertTrue(report["summary"]["gate_ok"])
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "qa", "qa_report.json")))
        with open(os.path.join(self.tmp, "qa", "qa_report.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["summary"]["total"], 2)

    def test_blank_page_makes_gate_fail(self):
        paths = dict(self.paths)
        paths[2] = make_image(os.path.join(self.tmp, "blank.png"), box=False, noise=False)
        report = qa_mod.evaluate(self.pages, paths, use_ocr=False)
        self.assertFalse(report["summary"]["gate_ok"])
        self.assertEqual(report["summary"]["failed_pages"], [2])

    def test_contact_sheet(self):
        out = qa_mod.contact_sheet(self.paths, os.path.join(self.tmp, "sheet.png"))
        self.assertTrue(out and os.path.isfile(out))

    def test_contact_sheet_empty(self):
        self.assertIsNone(qa_mod.contact_sheet({}, os.path.join(self.tmp, "none.png")))


class TestTokenResolution(unittest.TestCase):
    def test_env_token_wins(self):
        previous = os.environ.get("PADDLE_OCR_TOKEN")
        os.environ["PADDLE_OCR_TOKEN"] = "  abc  "
        try:
            self.assertEqual(qa_mod.paddle_token(), "abc")
        finally:
            if previous is None:
                os.environ.pop("PADDLE_OCR_TOKEN", None)
            else:
                os.environ["PADDLE_OCR_TOKEN"] = previous


if __name__ == "__main__":
    unittest.main()
