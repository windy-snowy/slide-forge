#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slide-forge 图片质量闸门（qa）。

对每一页生成图做可复现的自动检测：

  硬性（不合格 → fail，建议重抽）
    * 文件存在、体积合理
    * 最小宽度、宽高比接近 16:9
    * 非空白（灰度标准差 + 非背景像素占比）
    * 跨页重复（dHash 汉明距离）
  软性（不合格 → warn，交人判断）
    * 中文文本保真度：用飞桨 OCR 回读页面文字，与 spec 里的 core_text 比对（difflib 相似度）

OCR 分三级降级，并在报告里显式标注，绝不伪装通过：
    paddleocr-vl（有 token，能读到文字）
    builtin-ink （只能读几何，无文字）
    null        （连 editppt 都不可用）
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

SCHEMA_VERSION = 1

PUNCT = "，。；：、！？（）【】《》〈〉“”‘’·—…,.!?;:()[]{}<>\"'`~@#$%^&*_+=|\\/ \t\n\r\u3000"

EDITPPT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".editppt", "config.yaml")

DEFAULT_THRESHOLDS = {
    "min_width": 1536,
    "aspect": 16 / 9,
    "aspect_tolerance": 0.02,
    "min_bytes": 20 * 1024,
    "min_std": 8.0,
    "min_nonbg_ratio": 0.015,
    "min_dhash_distance": 6,
    "min_text_ratio": 0.85,
    "min_line_hit_ratio": 0.9,
    "min_ocr_coverage": 0.6,
}


# --------------------------------------------------------------------------- #
# 基础图像指标
# --------------------------------------------------------------------------- #
def image_stats(path: str) -> dict:
    from PIL import Image
    import numpy as np

    image = Image.open(path)
    width, height = image.size
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    small = np.asarray(image.convert("RGB").resize((160, 90)), dtype=np.float32)
    flat = small.reshape(-1, 3)
    quantized = (flat // 16).astype(np.int32)
    keys = quantized[:, 0] * 4096 + quantized[:, 1] * 64 + quantized[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    dominant = values[int(np.argmax(counts))]
    dominant_rgb = np.array([(dominant // 4096) * 16, ((dominant // 64) % 64) * 16, (dominant % 64) * 16])
    distance = np.abs(flat - dominant_rgb).sum(axis=1)
    return {
        "width": width,
        "height": height,
        "aspect": round(width / height, 5) if height else 0.0,
        "std": round(float(gray.std()), 2),
        "nonbg_ratio": round(float((distance > 60).mean()), 4),
    }


def dhash(path: str, size: int = 8) -> int:
    from PIL import Image
    import numpy as np

    image = Image.open(path).convert("L").resize((size + 1, size), Image.LANCZOS)
    pixels = np.asarray(image, dtype=np.int16)
    bits = (pixels[:, 1:] > pixels[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #
def paddle_token() -> str:
    """PADDLE_OCR_TOKEN 环境变量，其次 ~/.editppt/config.yaml。"""
    token = os.environ.get("PADDLE_OCR_TOKEN", "").strip()
    if token:
        return token
    try:
        with open(EDITPPT_CONFIG_PATH, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if line.startswith("PADDLE_OCR_TOKEN:"):
                    return line.split(":", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _runtime_dir() -> tuple[str | None, str | None]:
    """(runtime 目录, 解释器)。复用 merge_pages 的上游定位逻辑。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import merge_pages as mp
        runtime, _, _ = mp.guard()
        return runtime, mp._editppt_python()
    except Exception:  # noqa: BLE001
        return None, None


def ocr_lines(image_path: str, work_dir: str | None = None, timeout: int = 300,
              retries: int = 2) -> tuple:
    """返回 (lines, backend, note)。lines 形如 [{"text":..., "box_px":[...]}]。

    1) 有 token 且有上游 runtime → 调 paddle_text_hints.py（真正的文字识别，失败重试）
    2) 否则回退 editppt page hints（只有几何，没有文字）
    3) 都不可用 → ([], None, 原因)
    """
    tmp = work_dir or tempfile.mkdtemp(prefix="slideforge-ocr-")
    os.makedirs(tmp, exist_ok=True)
    note = ""
    try:
        source = os.path.join(tmp, "source.png")
        if os.path.abspath(image_path) != os.path.abspath(source):
            shutil.copy(image_path, source)
        token = paddle_token()
        runtime, interpreter = _runtime_dir()
        if token and runtime and os.path.isfile(os.path.join(runtime, "paddle_text_hints.py")):
            for _ in range(max(1, retries)):
                proc = subprocess.run(
                    [interpreter or sys.executable, os.path.join(runtime, "paddle_text_hints.py"), tmp,
                     "--token", token, "--out", "paddle_hints.json", "--overlay", "",
                     "--timeout", str(timeout)],
                    capture_output=True, text=True, timeout=timeout + 60)
                hint_path = os.path.join(tmp, "paddle_hints.json")
                if proc.returncode == 0 and os.path.isfile(hint_path):
                    with open(hint_path, encoding="utf-8") as fh:
                        payload = json.load(fh)
                    lines = payload.get("lines") or []
                    if lines:
                        return lines, payload.get("backend"), ""
                    note = "paddleocr 返回 0 行文字"
                else:
                    note = (proc.stderr or proc.stdout or "paddle_text_hints 失败").strip()[-200:]
            note = f"paddleocr 连续 {retries} 次未取到文字：{note}"
        elif not token:
            note = "未配置 PADDLE_OCR_TOKEN（环境变量或 ~/.editppt/config.yaml）"
        elif not runtime:
            note = "找不到 image-to-editable-ppt 的 runtime（无法调用 paddle_text_hints.py）"
        if shutil.which("editppt"):
            proc = subprocess.run(
                ["editppt", "page", "hints", tmp, "--out", "text_hints.json", "--overlay", ""],
                capture_output=True, text=True, timeout=timeout)
            hint_path = os.path.join(tmp, "text_hints.json")
            if proc.returncode == 0 and os.path.isfile(hint_path):
                with open(hint_path, encoding="utf-8") as fh:
                    payload = json.load(fh)
                return [], payload.get("backend"), note or "已回退到几何检测"
        return [], None, note or "editppt 不可用"
    except Exception as exc:  # noqa: BLE001
        return [], None, f"{type(exc).__name__}: {exc}"
    finally:
        if work_dir is None:
            shutil.rmtree(tmp, ignore_errors=True)


def ocr_lines_banded(image_path: str, bands: int = 4, overlap: float = 0.12,
                      timeout: int = 300) -> tuple:
    """整页 OCR 分段失败时的兜底：按横向条带切开分别识别再合并。

    实测：整页识别会漏掉卡片里的文字（VL 模型的分段把卡片当成了图），
    但把卡片区域裁出来能 100% 读对；放大整页则无效。所以用条带切分。
    """
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return [], None
    try:
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
        width, height = image.size
        step = height / max(1, bands)
        merged, seen, backend = [], set(), None
        for index in range(bands):
            top = max(0, int(index * step - height * overlap))
            bottom = min(height, int((index + 1) * step + height * overlap))
            crop_dir = tempfile.mkdtemp(prefix="slideforge-band-")
            crop_path = os.path.join(crop_dir, "band.png")
            image.crop((0, top, width, bottom)).save(crop_path)
            lines, band_backend, _note = ocr_lines(crop_path, timeout=timeout)
            backend = backend or band_backend
            for line in lines:
                text = (line.get("text") or "").strip()
                if text and text not in seen:
                    seen.add(text)
                    merged.append({"text": text, "band": index})
            shutil.rmtree(crop_dir, ignore_errors=True)
        return merged, backend
    except Exception:  # noqa: BLE001
        return [], None


# --------------------------------------------------------------------------- #
# 文本保真度
# --------------------------------------------------------------------------- #
def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"\s+", "", text)
    return "".join(ch for ch in text if ch not in PUNCT)


def text_fidelity(expected: list, observed: list, line_hit: float = 0.6) -> dict:
    """把期望文字逐行与 OCR 结果做模糊比对。"""
    observed_norm = [normalize_text(item) for item in observed if normalize_text(item)]
    details, weighted, total_weight, hits = [], 0.0, 0, 0
    for line in expected:
        target = normalize_text(line)
        if not target:
            continue
        best = 0.0
        for candidate in observed_norm:
            if target in candidate:
                best = 1.0
                break
            best = max(best, difflib.SequenceMatcher(None, target, candidate).ratio())
        details.append({"expected": line, "best_ratio": round(best, 3)})
        weight = max(len(target), 1)
        weighted += best * weight
        total_weight += weight
        hits += 1 if best >= line_hit else 0
    count = len(details)
    return {
        "mean_ratio": round(weighted / total_weight, 3) if total_weight else None,
        "line_hit_ratio": round(hits / count, 3) if count else None,
        "lines": details,
    }


# --------------------------------------------------------------------------- #
# 逐页测量与判定
# --------------------------------------------------------------------------- #
def probe_page(page: dict, path: str, use_ocr: bool, timeout: int = 300,
               band_retry: bool = True, retry_below_hits: float = 0.9) -> dict:
    expected = [str(t).strip() for t in (page.get("core_text") or []) if str(t).strip()]
    info = {"index": page.get("index"), "title": page.get("title"), "path": path,
            "exists": os.path.isfile(path),
            "bytes": os.path.getsize(path) if os.path.isfile(path) else 0,
            "expected_lines": len(expected),
            "ocr_backend": None, "ocr_lines": 0}
    if not info["exists"]:
        return info
    try:
        info.update(image_stats(path))
        info["dhash"] = dhash(path)
    except Exception as exc:  # noqa: BLE001
        info["probe_error"] = f"{type(exc).__name__}: {exc}"
        return info
    if use_ocr:
        lines, backend, note = ocr_lines(path, timeout=timeout)
        info["ocr_backend"] = backend
        info["ocr_note"] = note
        observed = [line.get("text", "") for line in lines if line.get("text")]
        info["ocr_lines"] = len(observed)
        expected_texts = [str(t) for t in (page.get("core_text") or []) if str(t).strip()]
        if observed:
            info.update(text_fidelity(expected_texts, observed))
        # 行命中率不达标时，先怀疑整页分段失败，用条带重试一次
        # （实测：整页会漏掉卡片里的文字，条带切分能读回来；只在即将报警时才付出这次额外 OCR 调用）
        if band_retry and expected_texts and (info.get("line_hit_ratio") or 0) < retry_below_hits:
            band_lines, band_backend = ocr_lines_banded(path, timeout=timeout)
            extra = [l["text"] for l in band_lines if l.get("text") and l["text"] not in observed]
            if extra:
                merged = observed + extra
                info["ocr_retry"] = "banded"
                info["ocr_backend"] = band_backend or backend
                info["ocr_lines"] = len(merged)
                info.update(text_fidelity(expected_texts, merged))
    return info


def judge_page(info: dict, thresholds: dict, digests: dict) -> dict:
    issues, warnings = [], []
    if not info["exists"]:
        issues.append("文件不存在")
    elif info.get("probe_error"):
        issues.append(f"图像读取失败：{info['probe_error']}")
    else:
        if info["bytes"] < thresholds["min_bytes"]:
            issues.append(f"文件过小（{info['bytes']} 字节），疑似空图或损坏")
        if info["width"] < thresholds["min_width"]:
            issues.append(f"宽度不足 {thresholds['min_width']}px（实际 {info['width']}）")
        if abs(info["aspect"] - thresholds["aspect"]) > thresholds["aspect_tolerance"]:
            issues.append(f"宽高比偏离 16:9（实际 {info['aspect']}）")
        if info["std"] < thresholds["min_std"]:
            issues.append(f"画面接近纯色/空白（灰度标准差 {info['std']}）")
        if info["nonbg_ratio"] < thresholds["min_nonbg_ratio"]:
            issues.append(f"有效内容过少（非背景像素占比 {info['nonbg_ratio']}）")
        digest = info.get("dhash")
        if digest is not None:
            for other_index, other in digests.items():
                if other_index == info["index"]:
                    continue
                distance = hamming(digest, other)
                if distance < thresholds["min_dhash_distance"]:
                    issues.append(f"与第 {other_index} 页几乎相同（汉明距离 {distance}）")
                    info["duplicate_of"] = other_index
                    break
            digests[info["index"]] = digest
        if thresholds.get("ocr_used", True):
            expected_lines = info.get("expected_lines") or 0
            observed = info.get("ocr_lines") or 0
            hits = info.get("line_hit_ratio") or 0
            mean = info.get("mean_ratio")
            info["ocr_coverage"] = round(observed / expected_lines, 2) if expected_lines else 1.0
            if not observed:
                warnings.append("OCR 未返回可用文字，跳过文本保真度检测（仅几何检测）"
                                + (f"：{info['ocr_note']}" if info.get("ocr_note") else ""))
            elif expected_lines and hits == 0:
                # 一行都没匹配上：多半是整页分段失败（文字其实在），也可能是文字确实缺失 —— 必须说清楚
                warnings.append(f"OCR 检出 {observed} 行但没有一行匹配核心文字"
                                + (f"（已做过条带重试）" if info.get("ocr_retry") else "")
                                + "：可能是分段/检出错位，也可能是文字确实缺失 —— 请人工看图确认"
                                + (f"，匹配率 {mean}" if mean is not None else ""))
            elif mean is not None and mean < thresholds["min_text_ratio"]:
                if hits >= thresholds["min_line_hit_ratio"]:
                    warnings.append(f"每行都检出了，但字符匹配率偏低（{mean} < "
                                    f"{thresholds['min_text_ratio']}）—— 常见于 OCR 漏读个别字或标点差异，"
                                    f"建议人工扫一眼即可")
                else:
                    warnings.append(f"文本匹配率偏低（{mean} < {thresholds['min_text_ratio']}），"
                                    f"可能有错字/乱码/漏字")
    info["status"] = "fail" if issues else ("warn" if warnings else "pass")
    info["issues"] = issues
    info["warnings"] = warnings
    return info


def evaluate(pages: list, image_paths: dict, thresholds: dict | None = None,
             use_ocr: bool = True, out_dir: str | None = None, concurrency: int = 3,
             ocr_timeout: int = 300) -> dict:
    merged = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    merged["ocr_used"] = bool(use_ocr)
    jobs = [(page, image_paths.get(page["index"], "")) for page in pages]
    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, len(jobs) or 1))) as pool:
        probed = list(pool.map(lambda job: probe_page(job[0], job[1], use_ocr, ocr_timeout), jobs))
    digests: dict = {}
    results = [judge_page(info, merged, digests) for info in probed]
    fails = [r for r in results if r["status"] == "fail"]
    warns = [r for r in results if r["status"] == "warn"]
    backends = sorted({r.get("ocr_backend") for r in results if r.get("ocr_backend")})
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(time.time() - started, 1),
        "thresholds": merged,
        "ocr_used": bool(use_ocr),
        "ocr_backends": backends,
        "pages": results,
        "summary": {
            "total": len(results),
            "pass": len(results) - len(fails) - len(warns),
            "warn": len(warns),
            "fail": len(fails),
            "failed_pages": [r["index"] for r in fails],
            "warned_pages": [r["index"] for r in warns],
            "all_pass": not fails and not warns,
            "gate_ok": not fails,
        },
    }
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "qa_report.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    return report


# --------------------------------------------------------------------------- #
# 总览图
# --------------------------------------------------------------------------- #
CJK_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msyh.ttc",
]


def _label_font(size: int = 20):
    """总览图标签含中文，默认位图字体会渲染成豆腐块，所以优先加载 CJK 字体。"""
    from PIL import ImageFont
    for path in CJK_FONT_CANDIDATES:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def contact_sheet(image_paths: dict, out_path: str, cols: int = 4,
                  thumb_width: int = 640, labels: dict | None = None) -> str | None:
    try:
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001
        return None
    items = [(index, image_paths[index]) for index in sorted(image_paths)
             if os.path.isfile(image_paths[index])]
    if not items:
        return None
    thumbs = []
    for index, path in items:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        ratio = thumb_width / image.width
        thumb = image.resize((thumb_width, max(1, int(image.height * ratio))), Image.LANCZOS)
        thumbs.append((index, thumb))
    font = _label_font(20)
    cell_w = thumb_width + 16
    cell_h = max(t.height for _, t in thumbs) + 46
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cell_w * cols, cell_h * rows), (18, 20, 26))
    draw = ImageDraw.Draw(sheet)
    for position, (index, thumb) in enumerate(thumbs):
        row, col = divmod(position, cols)
        x, y = col * cell_w + 8, row * cell_h + 8
        sheet.paste(thumb, (x, y))
        text = f"P{index:02d}"
        if labels and labels.get(index):
            text += f"  {labels[index][:20]}"
        draw.text((x + 4, y + thumb.height + 8), text, fill=(226, 232, 240), font=font)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if out_path.lower().endswith((".jpg", ".jpeg")):
        sheet.save(out_path, quality=90)
    else:
        sheet.save(out_path)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(json.dumps(image_stats(sys.argv[1]), ensure_ascii=False, indent=2))
    else:
        print("用法: python3 qa.py <image.png>")
