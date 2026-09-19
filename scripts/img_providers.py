#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slide-forge 生图后端抽象。

支持四种后端（都返回同一份结果结构，便于统一重试与记账）：

  openai-images      POST {base}/v1/images/generations        （gpt-image-1 / 1.5 / 2 / 2.5 等）
  chat-image         POST {base}/v1/chat/completions          （modalities=["image","text"] 的中转站）
  openrouter-images  POST {base}/api/v1/images                （google/gemini-*-image 等原生 16:9）
  editppt-cli        调用 `editppt image generate`            （复用 ~/.editppt 的配置与回退链）

密钥只从环境变量或 ~/.slideforge/config.json 读取，绝不写入仓库或产物。
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict

PROVIDERS = ("openai-images", "chat-image", "openrouter-images", "editppt-cli")

DEFAULT_BASE = {
    "openai-images": "https://api.openai.com",
    "chat-image": "https://api.openai.com",
    "openrouter-images": "https://openrouter.ai",
}
DEFAULT_MODEL = {
    "openai-images": "gpt-image-2",
    "chat-image": "gpt-image-2",
    "openrouter-images": "google/gemini-3.1-flash-image",
    "editppt-cli": "gpt-image-2",
}
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".slideforge", "config.json")
# 已经配好 editppt 的机器上可以直接复用它的密钥，不必再配一套
EDITPPT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".editppt", "config.yaml")
_EDITPPT_KEY_FIELDS = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "IMAGE_TO_EDITABLE_PPT_IMAGE_MODEL",
                       "PADDLE_OCR_TOKEN")


class ImageError(RuntimeError):
    pass


@dataclass
class ImageConfig:
    provider: str = "openai-images"
    model: str = "gpt-image-2"
    api_key: str = ""
    base_url: str = ""
    size: str = "1536x1024"
    quality: str = "medium"
    fit: str = "auto"
    aspect: str = "16:9"
    resolution: str = "2K"
    timeout: int = 600
    api_mode: str = "images"
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["api_key"] = "***" if self.api_key else ""
        return data


# --------------------------------------------------------------------------- #
# 配置解析
# --------------------------------------------------------------------------- #
def _config_file() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def editppt_config() -> dict:
    """容错读取 ~/.editppt/config.yaml（系统 python 可能没有 PyYAML，所以自己解析）。"""
    values = {}
    try:
        with open(EDITPPT_CONFIG_PATH, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                if key in _EDITPPT_KEY_FIELDS:
                    values[key] = value.strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return values


def resolve_config(backends: dict | None = None, overrides: dict | None = None,
                   provider: str | None = None, model: str | None = None) -> ImageConfig:
    """优先级：显式参数 > 环境变量 > spec.backends.image > ~/.slideforge/config.json
    > ~/.editppt/config.yaml（仅 OpenAI 兼容后端）> 内置默认。"""
    backends = backends or {}
    image = backends.get("image", {}) if isinstance(backends, dict) else {}
    overrides = {k: v for k, v in (overrides or {}).items() if v not in (None, "")}
    cfg_file = _config_file()
    openai_like = True

    name = (provider or overrides.get("provider") or os.environ.get("SLIDEFORGE_IMAGE_PROVIDER")
            or image.get("provider") or cfg_file.get("provider") or "openai-images")
    if name not in PROVIDERS:
        raise ImageError(f"未知生图后端：{name}；可用：{', '.join(PROVIDERS)}")
    openai_like = name in ("openai-images", "chat-image", "editppt-cli")
    editppt_cfg = editppt_config() if openai_like else {}

    def pick(env_keys, *values):
        for key in env_keys:
            if os.environ.get(key):
                return os.environ[key].strip()
        for value in values:
            if value:
                return value
        return ""

    resolved_model = (model or overrides.get("model") or os.environ.get("SLIDEFORGE_IMAGE_MODEL")
                      or image.get("model") or cfg_file.get("model")
                      or editppt_cfg.get("IMAGE_TO_EDITABLE_PPT_IMAGE_MODEL")
                      or DEFAULT_MODEL[name])
    base_url = pick(["SLIDEFORGE_IMAGE_BASE_URL", "OPENAI_BASE_URL"],
                    overrides.get("base_url"), image.get("base_url"), cfg_file.get("base_url"),
                    editppt_cfg.get("OPENAI_BASE_URL"))
    api_key = pick(["SLIDEFORGE_IMAGE_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"],
                   overrides.get("api_key"), image.get("api_key"), cfg_file.get("api_key"),
                   editppt_cfg.get("OPENAI_API_KEY") if openai_like else cfg_file.get("openrouter_api_key"))
    if not base_url:
        base_url = DEFAULT_BASE.get(name, DEFAULT_BASE["openai-images"])
    if name == "openrouter-images" and not api_key:
        api_key = pick(["OPENROUTER_API_KEY"], cfg_file.get("openrouter_api_key"))

    return ImageConfig(
        provider=name,
        model=resolved_model,
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        size=overrides.get("size") or image.get("size") or "1536x1024",
        quality=overrides.get("quality") or image.get("quality") or "medium",
        fit=overrides.get("fit") or image.get("fit") or "auto",
        aspect=overrides.get("aspect") or image.get("aspect") or "16:9",
        resolution=overrides.get("resolution") or image.get("resolution") or "2K",
        timeout=int(overrides.get("timeout") or image.get("timeout") or 600),
        api_mode=overrides.get("api_mode") or image.get("api_mode") or "images",
    )


def doctor_report() -> dict:
    """不联网的后端自检：只报告配置是否齐备。"""
    out = {"config_file": CONFIG_PATH, "config_file_exists": os.path.isfile(CONFIG_PATH),
           "editppt_config": EDITPPT_CONFIG_PATH,
           "editppt_config_exists": os.path.isfile(EDITPPT_CONFIG_PATH)}
    for name in PROVIDERS:
        try:
            cfg = resolve_config(provider=name)
        except ImageError as exc:
            out[name] = {"error": str(exc)}
            continue
        out[name] = {"model": cfg.model, "base_url": cfg.base_url,
                     "api_key_present": bool(cfg.api_key),
                     "ready": True if name == "editppt-cli" else bool(cfg.api_key)}
    out["env"] = {k: ("set" if os.environ.get(k) else "") for k in
                  ("SLIDEFORGE_IMAGE_API_KEY", "SLIDEFORGE_IMAGE_BASE_URL", "SLIDEFORGE_IMAGE_MODEL",
                   "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_API_KEY")}
    return out


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _url(cfg: ImageConfig, kind: str) -> str:
    base = cfg.base_url.rstrip("/")
    if kind == "openrouter":
        return base + "/images" if base.endswith("/v1") else base + "/api/v1/images"
    if kind == "chat":
        return base + "/chat/completions" if base.endswith("/v1") else base + "/v1/chat/completions"
    return base + "/images/generations" if base.endswith("/v1") else base + "/v1/images/generations"


def _post(url: str, api_key: str, body: dict, timeout: int = 600) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def extract_image(payload: dict) -> tuple[bytes | None, str | None]:
    """兼容 b64_json / url / chat.images 三种返回形态。"""
    if "choices" in payload:  # chat/completions
        message = payload["choices"][0].get("message", {})
        images = message.get("images") or []
        if not images:
            raise ImageError("chat 响应里没有图片：" + json.dumps(payload, ensure_ascii=False)[:200])
        url = images[0].get("image_url", {}).get("url", "")
        if url.startswith("data:"):
            return base64.b64decode(url.split(",", 1)[1]), None
        return None, url
    data = payload.get("data") or []
    if not data:
        raise ImageError("响应里没有图片：" + json.dumps(payload, ensure_ascii=False)[:200])
    item = data[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"]), None
    if item.get("url"):
        return None, item["url"]
    raise ImageError("未知返回字段：" + str(list(item.keys())))


def _download(url: str, timeout: int = 600) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def _cost_of(payload: dict) -> float | None:
    usage = payload.get("usage") or {}
    for key in ("total_cost", "cost", "total_cost_usd"):
        if usage.get(key) is not None:
            try:
                return float(usage[key])
            except (TypeError, ValueError):
                return None
    return None


# --------------------------------------------------------------------------- #
# 16:9 适配（移植自 glassdeck/gen_relay_slides.py 的已验证实现）
# --------------------------------------------------------------------------- #
def to_169(path: str, mode: str = "auto") -> tuple[int, int]:
    """把生成图适配成 16:9。auto=内容能进就裁切、否则模糊羽化补边；pad/crop/none 为强制模式。"""
    if mode == "none":
        from PIL import Image
        with Image.open(path) as opened:
            return opened.size
    from PIL import Image, ImageFilter
    import numpy as np

    with Image.open(path) as opened:
        image = opened.convert("RGB")
    width, height = image.size
    target_width = int(round(height * 16 / 9))
    if mode == "auto":
        gray = np.asarray(image.convert("L"), dtype=float)
        counts = (gray > 100).sum(axis=1)
        rows = np.where(counts > 6)[0]
        target_h = int(round(width / (16 / 9)))
        if len(rows) and (rows.max() - rows.min()) <= target_h - 16:
            center = (rows.min() + rows.max()) // 2
            y0 = int(min(max(center - target_h // 2, 0), height - target_h))
            out = image.crop((0, y0, width, y0 + target_h))
            out.save(path)
            return out.size
        mode = "pad"
    if mode == "crop":
        target_h = int(round(width / (16 / 9)))
        if height > target_h:
            top = int((height - target_h) / 2)
            image = image.crop((0, top, width, top + target_h))
        elif height < target_h:
            target_w = int(round(height * 16 / 9))
            left = int((width - target_w) / 2)
            image = image.crop((left, 0, left + target_w, height))
        image.save(path)
        return image.size
    # pad：整图放大模糊做底 + 羽化过渡，无缝补到 16:9（不丢任何内容）
    if target_width <= width:
        target_h = int(round(width / (16 / 9)))
        top = int((height - target_h) / 2)
        image = image.crop((0, top, width, top + target_h))
        image.save(path)
        return image.size
    background = image.resize((target_width, height), Image.LANCZOS).filter(ImageFilter.GaussianBlur(70))
    canvas = background.copy()
    feather = 110
    alpha = np.ones((height, width), np.float32)
    alpha[:, :feather] = np.linspace(0, 1, feather) ** 1.4
    alpha[:, -feather:] = np.linspace(1, 0, feather) ** 1.4
    canvas.paste(image, ((target_width - width) // 2, 0),
                 Image.fromarray((alpha * 255).astype(np.uint8)))
    array = np.asarray(canvas, dtype=np.float32)
    xs = np.arange(target_width)
    weight = np.clip((np.abs(xs - target_width / 2) - width / 2 + 140) / 420, 0, 1)[None, :, None]
    canvas = Image.fromarray((array * (1 - 0.22 * weight)).astype(np.uint8))
    canvas.save(path)
    return canvas.size


# --------------------------------------------------------------------------- #
# 生成
# --------------------------------------------------------------------------- #
def build_request(cfg: ImageConfig, prompt: str) -> dict:
    """返回 {url, body}，供真实调用与 dry-run 展示共用。"""
    if cfg.provider == "openai-images":
        return {"url": _url(cfg, "images"),
                "body": {"model": cfg.model, "prompt": prompt, "size": cfg.size,
                         "quality": cfg.quality, "n": 1}}
    if cfg.provider == "chat-image":
        return {"url": _url(cfg, "chat"),
                "body": {"model": cfg.model, "modalities": ["image", "text"],
                         "messages": [{"role": "user", "content": prompt}]}}
    if cfg.provider == "openrouter-images":
        body = {"model": cfg.model, "prompt": prompt, "n": 1}
        if cfg.aspect:
            body["aspect_ratio"] = cfg.aspect
        if cfg.resolution:
            body["resolution"] = cfg.resolution
        return {"url": _url(cfg, "openrouter"), "body": body}
    return {"url": "editppt image generate", "body": {"model": cfg.model, "size": cfg.size,
                                                      "quality": cfg.quality}}


def generate(prompt: str, out_path: str, cfg: ImageConfig, force: bool = False,
             dry_run: bool = False, retries: int = 3, sleep: float = 2.0) -> dict:
    """生成一页图片。返回 {path, cost, elapsed, size, raw, skipped, error}。"""
    started = time.time()
    result = {"path": out_path, "cost": None, "elapsed": 0.0, "size": None,
              "skipped": False, "error": None, "provider": cfg.provider, "model": cfg.model}
    if os.path.exists(out_path) and not force:
        result["skipped"] = True
        result["size"] = _image_size(out_path)
        return result

    if cfg.provider == "editppt-cli":
        return _generate_via_cli(prompt, out_path, cfg, result, dry_run, started)

    request = build_request(cfg, prompt)
    if dry_run:
        result["elapsed"] = 0.0
        result["dry_run"] = {"url": request["url"], "body": request["body"]}
        return result
    if not cfg.api_key:
        raise ImageError(
            f"缺少 {cfg.provider} 的 API Key。请设置 SLIDEFORGE_IMAGE_API_KEY / OPENAI_API_KEY / "
            f"OPENROUTER_API_KEY，或写入 {CONFIG_PATH}（chmod 600）。")

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            payload = _post(request["url"], cfg.api_key, request["body"], cfg.timeout)
            blob, link = extract_image(payload)
            if blob is None:
                blob = _download(link, cfg.timeout)
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            with open(out_path, "wb") as fh:
                fh.write(blob)
            if cfg.fit != "none":
                result["size"] = to_169(out_path, cfg.fit)
            else:
                result["size"] = _image_size(out_path)
            result["cost"] = _cost_of(payload)
            result["elapsed"] = round(time.time() - started, 1)
            return result
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                message = json.loads(raw).get("error", {}).get("message", raw)
            except Exception:
                message = raw
            last_error = f"HTTP {exc.code}: {message[:300]}"
            if exc.code == 403 and "额度" in message:
                raise ImageError(f"账户余额不足：{message[:200]}")
            if exc.code in (408, 409, 425, 429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(5 * attempt)
                continue
            break
        except Exception as exc:  # noqa: BLE001 - 网络/解析错误统一重试
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(5 * attempt)
                continue
            break
    result["error"] = last_error
    result["elapsed"] = round(time.time() - started, 1)
    return result


def _generate_via_cli(prompt: str, out_path: str, cfg: ImageConfig, result: dict,
                      dry_run: bool, started: float) -> dict:
    if cfg.api_key:
        os.environ.setdefault("OPENAI_API_KEY", cfg.api_key)
    if cfg.base_url:
        os.environ.setdefault("OPENAI_BASE_URL", cfg.base_url)
    if dry_run:
        result["dry_run"] = {"command": ["editppt", "image", "generate", "--prompt-file", "<stdin>",
                                         "--model", cfg.model, "--size", cfg.size,
                                         "--quality", cfg.quality, "--out", out_path],
                             "prompt_chars": len(prompt)}
        return result
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write(prompt)
        prompt_file = fh.name
    command = ["editppt", "image", "generate", "--prompt-file", prompt_file,
               "--model", cfg.model, "--size", cfg.size, "--quality", cfg.quality,
               "--out", out_path, "--force"]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=cfg.timeout + 120)
    finally:
        try:
            os.unlink(prompt_file)
        except OSError:
            pass
    if proc.returncode != 0 or not os.path.exists(out_path):
        result["error"] = (proc.stderr or proc.stdout or "editppt image generate 失败").strip()[-400:]
        result["elapsed"] = round(time.time() - started, 1)
        return result
    if cfg.fit != "none":
        result["size"] = to_169(out_path, cfg.fit)
    else:
        result["size"] = _image_size(out_path)
    result["elapsed"] = round(time.time() - started, 1)
    return result


def _image_size(path: str):
    try:
        from PIL import Image
        with Image.open(path) as image:
            return list(image.size)
    except Exception:
        return None


if __name__ == "__main__":
    print(json.dumps(doctor_report(), ensure_ascii=False, indent=2))
    sys.exit(0)
