#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 N 个「单页 run」的元素版产物合并成一份多页 PPTX（无子代理模式的收尾步骤）。

背景（已读上游源码核实）：
  * `editppt run dispatch --local` 只允许 run 恰好只有一页
    （cli/editppt/runtime/record_page_dispatch.py:55）；
  * 上游 SKILL.md 禁止主 agent 逐页重建「多页 run」。
因此默认（无子代理）模式走：N 个单页 run 各自合法重建 → 本脚本合并。

合并不写 PPTX XML、也不搬 python-pptx 的 slide，而是复用上游自带构建器：
  build_pptx_from_manifest.py --deck-manifest <merged>/deck_manifest.json --out <pptx>
它按 deck_manifest["job_dir"] 为根、按 pages[].manifest 相对路径读取每页 manifest，
资产按各 manifest 所在目录解析（build_pptx_from_manifest.py:742-767），
notes 按 notes_manifest.json 的 page_index 对齐页序（:729-756）。
所以我们只需要：合并清单 + 备注清单 + 软链到各单页目录。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

SCHEMA_VERSION = 1

SKILL_ROOT_ENV = ("SLIDEFORGE_I2E_SKILL_ROOT", "IMAGE_TO_EDITABLE_PPT_SKILL_ROOT")
SKILL_ROOT_CANDIDATES = [
    "~/.dsh/skills/image-to-editable-ppt",
    "~/.claude/skills/image-to-editable-ppt",
    "~/.agents/skills/image-to-editable-ppt",
    "~/.config/dsh/skills/image-to-editable-ppt",
    "~/.codex/skills/image-to-editable-ppt",
]


# --------------------------------------------------------------------------- #
# 上游定位与版本守卫
# --------------------------------------------------------------------------- #
def _editppt_python() -> str | None:
    """从 editppt 启动脚本的 shebang 找到它自己的解释器，用于 import 定位源码。"""
    shim = shutil.which("editppt")
    if not shim:
        return None
    try:
        with open(shim, encoding="utf-8", errors="ignore") as fh:
            first = fh.readline().strip()
        if first.startswith("#!"):
            return first[2:].strip().split()[0]
    except OSError:
        pass
    return None


def find_skill_root() -> tuple[str | None, list]:
    """返回 (skill_root, 尝试记录)。优先用 editppt 自身的安装位置，其次常见技能目录。"""
    tried = []
    runtime, label, attempts = _find_runtime()
    tried.extend(attempts)
    if runtime:
        # 反推回技能根：<root>/cli/editppt/runtime
        root = os.path.dirname(os.path.dirname(os.path.dirname(runtime)))
        return root, tried
    return None, tried


def _candidate_runtimes() -> list:
    """按优先级列出候选 runtime 目录：(来源说明, 目录)。"""
    candidates = []
    for key in SKILL_ROOT_ENV:
        value = os.environ.get(key)
        if value:
            candidates.append((f"env:{key}", os.path.expanduser(value)))
    python = _editppt_python()
    if python:
        try:
            proc = subprocess.run(
                [python, "-c", "import editppt, os; print(os.path.dirname(editppt.__file__))"],
                capture_output=True, text=True, timeout=60)
            if proc.returncode == 0 and proc.stdout.strip():
                package = proc.stdout.strip()
                # 优先 CLI 实际加载的那份 runtime，保证与 `editppt run finalize` 一致
                candidates.append(("import:editppt", package))
                candidates.append(("install", os.path.dirname(os.path.dirname(package))))
        except Exception:  # noqa: BLE001
            pass
    for candidate in SKILL_ROOT_CANDIDATES:
        candidates.append(("candidate", os.path.expanduser(candidate)))
    return candidates


def _find_runtime() -> tuple[str | None, str | None, list]:
    tried = []
    for label, path in _candidate_runtimes():
        for runtime in (os.path.join(path, "runtime"), os.path.join(path, "cli", "editppt", "runtime")):
            tried.append((label, runtime))
            if _runtime_dir_from(runtime):
                return runtime, label, tried
    return None, None, tried


def _runtime_dir_from(runtime: str) -> str | None:
    if os.path.isfile(os.path.join(runtime, "build_pptx_from_manifest.py")) and \
            os.path.isfile(os.path.join(runtime, "validate_pptx.py")):
        return runtime
    return None


def _runtime_dir(root: str) -> str | None:
    runtime = os.path.join(root, "cli", "editppt", "runtime")
    if os.path.isfile(os.path.join(runtime, "build_pptx_from_manifest.py")) and \
            os.path.isfile(os.path.join(runtime, "validate_pptx.py")):
        return runtime
    return None


def find_skill_dir() -> tuple[str | None, list]:
    """定位 image-to-editable-ppt 技能目录（需 SKILL.md + scripts/build-page-worker-prompt.py）。"""
    tried, candidates = [], []
    for key in SKILL_ROOT_ENV:
        value = os.environ.get(key)
        if value:
            candidates.append((f"env:{key}", os.path.expanduser(value)))
    for candidate in SKILL_ROOT_CANDIDATES:
        candidates.append(("candidate", os.path.expanduser(candidate)))
    for directory in sorted(glob.glob(os.path.join(os.path.expanduser("~"), "*", "skills",
                                                   "image-to-editable-ppt"))):
        candidates.append(("glob", directory))
    for label, path in candidates:
        tried.append((label, path))
        if os.path.isfile(os.path.join(path, "SKILL.md")) and \
                os.path.isfile(os.path.join(path, "scripts", "build-page-worker-prompt.py")):
            return path, tried
    return None, tried


def guard() -> tuple[str | None, str, list]:
    """返回 (runtime_dir, 说明, 尝试记录)。runtime_dir=None 表示需要降级。"""
    runtime, label, tried = _find_runtime()
    if runtime:
        return runtime, label or runtime, tried
    return None, "找不到可用的上游构建器（image-to-editable-ppt 的 build_pptx_from_manifest.py）", tried


# --------------------------------------------------------------------------- #
# 单页产物发现
# --------------------------------------------------------------------------- #
def list_parts(parts_dir: str) -> list:
    """按目录名排序收集 <parts>/<pNN>/pages/page_XXX。"""
    found = []
    for part_dir in sorted(glob.glob(os.path.join(parts_dir, "*"))):
        if not os.path.isdir(part_dir):
            continue
        page_dirs = sorted(glob.glob(os.path.join(part_dir, "pages", "page_*")))
        page_dirs = [d for d in page_dirs if os.path.isfile(os.path.join(d, "manifest.json"))]
        if not page_dirs:
            continue
        if len(page_dirs) > 1:
            raise SystemExit(f"{part_dir} 不是单页 run（含 {len(page_dirs)} 页），无法按单页合并")
        found.append({"part": os.path.basename(part_dir), "part_dir": part_dir,
                      "page_dir": page_dirs[0]})
    return found


# --------------------------------------------------------------------------- #
# 合并
# --------------------------------------------------------------------------- #
def build_merged(parts: list, spec: dict, merged_dir: str, pptx_out: str,
                 source: str = "") -> dict:
    os.makedirs(merged_dir, exist_ok=True)
    pages_root = os.path.join(merged_dir, "pages")
    os.makedirs(pages_root, exist_ok=True)
    # 清掉上一次合并留下的页链接/目录，避免残留页混进新清单
    for stale in glob.glob(os.path.join(pages_root, "page_*")):
        if os.path.islink(stale):
            os.unlink(stale)
        else:
            shutil.rmtree(stale, ignore_errors=True)
    pages, warnings = [], []

    for index, part in enumerate(parts, 1):
        link = os.path.join(pages_root, f"page_{index:03d}")
        if os.path.islink(link) or os.path.exists(link):
            if os.path.islink(link):
                os.unlink(link)
            else:
                shutil.rmtree(link, ignore_errors=True)
        target = os.path.relpath(part["page_dir"], pages_root)
        try:
            os.symlink(target, link)
        except OSError:
            shutil.copytree(part["page_dir"], link)
            warnings.append(f"page_{index:03d} 软链失败，已改为拷贝")
        pages.append({
            "page_index": index,
            "page_id": f"page_{index:03d}",
            "page_dir": f"pages/page_{index:03d}",
            "manifest": f"pages/page_{index:03d}/manifest.json",
            "source_image": f"pages/page_{index:03d}/source.png",
            "part": part["part"],
        })

    deck_spec_pages = spec.get("pages") or []
    notes = []
    for index, page in enumerate(deck_spec_pages, 1):
        text = page.get("notes") or ""
        if text:
            notes.append({"page_index": index, "text": text})
    notes_path = os.path.join(merged_dir, "notes_manifest.json")
    with open(notes_path, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": SCHEMA_VERSION, "source": source or "deck_spec.json",
                   "notes": notes}, fh, ensure_ascii=False, indent=2)

    deck_manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": os.path.basename(merged_dir) + "-merged",
        "input_type": "pages",
        "job_dir": os.path.abspath(merged_dir),
        "page_count": len(pages),
        "pages": pages,
        "notes_manifest": "notes_manifest.json",
        "output": os.path.abspath(pptx_out),
        "slide": {"width": 13.333, "height": 7.5, "size_mode": "wide"},
        "input": source or "slide-forge 单页 run 合集",
        "merge": {"mode": "single-page-runs", "merged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                        time.gmtime()),
                  "sources": [part["part"] for part in parts]},
    }
    manifest_path = os.path.join(merged_dir, "deck_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(deck_manifest, fh, ensure_ascii=False, indent=2)
    return {"deck_manifest": manifest_path, "notes_manifest": notes_path,
            "merged_dir": merged_dir, "pages": len(pages),
            "notes": len(notes), "warnings": warnings}


def build_and_validate(parts: list, spec: dict, merged_dir: str, pptx_out: str,
                       source: str = "", dry_run: bool = False) -> dict:
    result = build_merged(parts, spec, merged_dir, pptx_out, source)
    runtime, root, tried = guard()
    result["runtime_source"] = root
    result["runtime"] = runtime
    if not runtime:
        result["ok"] = False
        result["reason"] = (f"无法使用上游构建器合并：{root}。降级方案：逐个交付 "
                            f"pages/page_NNN/page.pptx，或改用 --subagents 模式。")
        result["tried"] = [str(item) for item in tried]
        return result
    if dry_run:
        result["ok"] = True
        result["dry_run"] = True
        return result

    builder = os.path.join(runtime, "build_pptx_from_manifest.py")
    validator = os.path.join(runtime, "validate_pptx.py")
    os.makedirs(os.path.dirname(os.path.abspath(pptx_out)), exist_ok=True)
    build = subprocess.run([sys.executable, builder, "--deck-manifest",
                            result["deck_manifest"], "--out", pptx_out],
                           capture_output=True, text=True)
    result["build_stdout"] = (build.stdout or "").strip()[-500:]
    if build.returncode != 0 or not os.path.isfile(pptx_out):
        result["ok"] = False
        result["reason"] = "上游构建器失败：" + ((build.stderr or build.stdout or "").strip()[-400:])
        return result

    validation_path = os.path.join(merged_dir, "validation.json")
    check = subprocess.run([sys.executable, validator, pptx_out, "--deck-manifest",
                            result["deck_manifest"], "--report", validation_path],
                           capture_output=True, text=True)
    result["validate_stdout"] = (check.stdout or "").strip()[-500:]
    result["validation"] = validation_path
    try:
        with open(validation_path, encoding="utf-8") as fh:
            report = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        result["ok"] = False
        result["reason"] = f"读取 validation.json 失败：{exc}"
        return result
    result["validation_report"] = report
    result["ok"] = bool(report.get("passed")) and check.returncode == 0
    if not result["ok"]:
        result["reason"] = ("上游校验未通过：" +
                            json.dumps({k: report.get(k) for k in
                                        ("slides", "expected_pages", "failed_page_validations",
                                         "page_contract_violations", "missing_parts", "warnings")},
                                       ensure_ascii=False)[:400])
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="合并单页 run 的元素版产物为一份多页 PPTX")
    parser.add_argument("--parts", help="包含 pNN/ 单页 run 的目录")
    parser.add_argument("--spec", help="deck_spec.json（提供讲者备注）")
    parser.add_argument("--out", help="输出的元素版 PPTX 路径")
    parser.add_argument("--merged-dir", help="合并工作目录（默认 <parts>/../merged）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true", help="只检查上游构建器是否可用")
    args = parser.parse_args()

    if args.check:
        runtime, root, tried = guard()
        print(json.dumps({"runtime_source": root, "runtime": runtime,
                          "ok": bool(runtime), "tried": [str(t) for t in tried]},
                         ensure_ascii=False, indent=2))
        return 0 if runtime else 1
    if not args.parts or not args.out:
        parser.error("--parts 与 --out 是必需参数（--check 除外）")

    runtime, root, tried = guard()
    if not runtime:
        print(f"✗ {root}", file=sys.stderr)
        for item in tried:
            print(f"  试过：{item}", file=sys.stderr)
        return 2

    parts = list_parts(os.path.abspath(args.parts))
    if not parts:
        print(f"✗ {args.parts} 里没有找到已重建的单页 run", file=sys.stderr)
        return 2
    spec = {}
    if args.spec and os.path.isfile(args.spec):
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
    merged_dir = args.merged_dir or os.path.join(os.path.dirname(os.path.abspath(args.parts)), "merged")
    result = build_and_validate(parts, spec, merged_dir, os.path.abspath(args.out),
                                source=args.spec or "", dry_run=args.dry_run)
    print(json.dumps({k: v for k, v in result.items() if k != "validation_report"},
                     ensure_ascii=False, indent=2))
    if not result["ok"]:
        print("✗ 合并失败：" + result.get("reason", ""), file=sys.stderr)
        return 1
    print(f"✓ 元素版：{args.out}（{result['pages']} 页，备注 {result['notes']} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
