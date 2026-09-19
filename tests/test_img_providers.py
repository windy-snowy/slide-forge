#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""img_providers 的单元测试：URL 拼装、返回解析、配置优先级、16:9 适配。"""

import base64
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import img_providers as ip  # noqa: E402


class TestUrls(unittest.TestCase):
    def test_openai_with_v1(self):
        cfg = ip.ImageConfig(provider="openai-images", base_url="https://api.example.com/v1")
        self.assertEqual(ip._url(cfg, "images"), "https://api.example.com/v1/images/generations")

    def test_openai_without_v1(self):
        cfg = ip.ImageConfig(provider="openai-images", base_url="https://api.example.com")
        self.assertEqual(ip._url(cfg, "images"), "https://api.example.com/v1/images/generations")

    def test_chat_route(self):
        cfg = ip.ImageConfig(provider="chat-image", base_url="https://api.example.com/v1")
        self.assertEqual(ip._url(cfg, "chat"), "https://api.example.com/v1/chat/completions")

    def test_openrouter_route(self):
        cfg = ip.ImageConfig(provider="openrouter-images", base_url="https://openrouter.ai/api/v1")
        self.assertEqual(ip._url(cfg, "openrouter"), "https://openrouter.ai/api/v1/images")


class TestExtract(unittest.TestCase):
    def test_b64(self):
        blob = base64.b64encode(b"hello").decode()
        data, link = ip.extract_image({"data": [{"b64_json": blob}]})
        self.assertEqual(data, b"hello")
        self.assertIsNone(link)

    def test_url(self):
        data, link = ip.extract_image({"data": [{"url": "https://x/y.png"}]})
        self.assertIsNone(data)
        self.assertEqual(link, "https://x/y.png")

    def test_chat_images_data_uri(self):
        payload = {"choices": [{"message": {"images": [
            {"image_url": {"url": "data:image/png;base64," + base64.b64encode(b"z").decode()}}]}}]}
        data, link = ip.extract_image(payload)
        self.assertEqual(data, b"z")
        self.assertIsNone(link)

    def test_empty_response_raises(self):
        with self.assertRaises(ip.ImageError):
            ip.extract_image({"data": []})

    def test_unknown_fields_raises(self):
        with self.assertRaises(ip.ImageError):
            ip.extract_image({"data": [{"weird": 1}]})


class TestCost(unittest.TestCase):
    def test_cost_keys(self):
        self.assertEqual(ip._cost_of({"usage": {"total_cost": 0.12}}), 0.12)
        self.assertEqual(ip._cost_of({"usage": {"cost": "0.5"}}), 0.5)
        self.assertIsNone(ip._cost_of({"usage": {}}))


class TestBuildRequest(unittest.TestCase):
    def test_openai_body(self):
        cfg = ip.ImageConfig(provider="openai-images", model="gpt-image-2",
                             base_url="https://api.example.com/v1", size="1536x1024", quality="low")
        request = ip.build_request(cfg, "画一页 PPT")
        self.assertEqual(request["body"]["model"], "gpt-image-2")
        self.assertEqual(request["body"]["size"], "1536x1024")
        self.assertEqual(request["body"]["quality"], "low")
        self.assertEqual(request["body"]["n"], 1)

    def test_chat_body_has_modalities(self):
        cfg = ip.ImageConfig(provider="chat-image", model="m", base_url="https://a/v1")
        self.assertEqual(ip.build_request(cfg, "p")["body"]["modalities"], ["image", "text"])

    def test_openrouter_body_has_aspect(self):
        cfg = ip.ImageConfig(provider="openrouter-images", model="m",
                             base_url="https://openrouter.ai/api/v1", aspect="16:9", resolution="2K")
        body = ip.build_request(cfg, "p")["body"]
        self.assertEqual(body["aspect_ratio"], "16:9")
        self.assertEqual(body["resolution"], "2K")


class TestResolveConfig(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in
                      ("SLIDEFORGE_IMAGE_API_KEY", "SLIDEFORGE_IMAGE_BASE_URL",
                       "SLIDEFORGE_IMAGE_MODEL", "SLIDEFORGE_IMAGE_PROVIDER",
                       "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_API_KEY")}
        for key in self.saved:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_env_wins_over_spec(self):
        os.environ["SLIDEFORGE_IMAGE_API_KEY"] = "env-key"
        cfg = ip.resolve_config({"image": {"api_key": "spec-key", "provider": "openai-images"}})
        self.assertEqual(cfg.api_key, "env-key")

    def test_spec_used_when_no_env(self):
        cfg = ip.resolve_config({"image": {"provider": "chat-image", "model": "spec-model",
                                           "api_key": "spec-key", "base_url": "https://s/v1"}})
        self.assertEqual(cfg.provider, "chat-image")
        self.assertEqual(cfg.model, "spec-model")
        self.assertEqual(cfg.api_key, "spec-key")

    def test_unknown_provider_raises(self):
        with self.assertRaises(ip.ImageError):
            ip.resolve_config(provider="not-a-provider")

    def test_explicit_args_win(self):
        cfg = ip.resolve_config({"image": {"model": "spec-model"}}, provider="openrouter-images",
                                model="arg-model")
        self.assertEqual(cfg.provider, "openrouter-images")
        self.assertEqual(cfg.model, "arg-model")

    def test_doctor_report_shape(self):
        report = ip.doctor_report()
        for name in ip.PROVIDERS:
            self.assertIn(name, report)


class TestFit169(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sf-fit-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pad_mode_reaches_16_9(self):
        from PIL import Image, ImageDraw
        path = os.path.join(self.tmp, "tall.png")
        image = Image.new("RGB", (1500, 1400), (8, 10, 20))
        ImageDraw.Draw(image).rectangle([100, 100, 1400, 1300], fill=(40, 60, 120))
        image.save(path)
        width, height = ip.to_169(path, "pad")
        self.assertAlmostEqual(width / height, 16 / 9, places=2)

    def test_none_mode_keeps_size(self):
        from PIL import Image
        path = os.path.join(self.tmp, "keep.png")
        Image.new("RGB", (1024, 1024), (0, 0, 0)).save(path)
        self.assertEqual(tuple(ip.to_169(path, "none")), (1024, 1024))

    def test_crop_mode_reaches_16_9(self):
        from PIL import Image
        path = os.path.join(self.tmp, "crop.png")
        Image.new("RGB", (1600, 1600), (30, 30, 30)).save(path)
        width, height = ip.to_169(path, "crop")
        self.assertAlmostEqual(width / height, 16 / 9, places=2)


class TestDryRun(unittest.TestCase):
    def test_dry_run_does_not_write_or_call(self):
        cfg = ip.ImageConfig(provider="openai-images", model="gpt-image-2",
                             base_url="https://api.example.com/v1", api_key="k")
        target = os.path.join(tempfile.mkdtemp(prefix="sf-dry-"), "out.png")
        result = ip.generate("提示词", target, cfg, dry_run=True)
        self.assertIn("dry_run", result)
        self.assertFalse(os.path.exists(target))
        self.assertTrue(result["dry_run"]["url"].endswith("/images/generations"))

    def test_missing_key_raises(self):
        cfg = ip.ImageConfig(provider="openai-images", base_url="https://api.example.com/v1")
        target = os.path.join(tempfile.mkdtemp(prefix="sf-key-"), "out.png")
        with self.assertRaises(ip.ImageError):
            ip.generate("提示词", target, cfg)


class TestEditpptConfigFallback(unittest.TestCase):
    def test_parse_tolerates_missing_file(self):
        self.assertIsInstance(ip.editppt_config(), dict)


if __name__ == "__main__":
    unittest.main()
