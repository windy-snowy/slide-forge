#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slide-forge 第三阶段编排：把「图片版」转成「元素版」（委托 image-to-editable-ppt）。

两种模式（页面重建规则全程以上游 image-to-editable-ppt 的 SKILL.md 为准）：

  默认 · 无子代理（single-page-runs）
    N 个单页 run：`editppt prepare <page.png> --job-dir parts/pNN`
    → 每个 run 用 `dispatch --local` 由主 agent 本地重建 → `record` → `finalize`
    → merge_pages.py 用上游构建器合并成一份多页 PPTX。
    依据：上游 `--local` 只允许单页 run（record_page_dispatch.py:55），
    而上游禁止主 agent 重建多页 run，所以逐页单 run + 合并是唯一合规路径。

  子代理（multi-page-run）
    单次 `editppt prepare <图片版.pptx>` 建多页 run → DSH subagent 并行派 page worker
    → record → finalize，得到上游原生单文件多页 PPTX（更快）。

本脚本只做「编排」：准备 run、生成 worker prompt、转发 editppt 命令、合并与校验；
不重写上游任何页面决策规则。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import merge_pages as mp  # noqa: E402
import spec_model as sm  # noqa: E402

ANNEX_PATH = os.path.join(os.path.dirname(HERE), "prompts", "page-worker-efficiency-annex.md")
PLAN_NAME = "plan.json"


# --------------------------------------------------------------------------- #
# 基础
# --------------------------------------------------------------------------- #
def run_cmd(command: list, cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print("+ " + " ".join(str(part) for part in command), flush=True)
    proc = subprocess.run([str(part) for part in command], cwd=cwd, capture_output=True, text=True)
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.returncode != 0 and proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)
    if check and proc.returncode != 0:
        raise SystemExit(f"命令失败（{proc.returncode}）：{' '.join(str(p) for p in command)}")
    return proc


def run_dir_of(args) -> str:
    if getattr(args, "run", None):
        return os.path.abspath(args.run)
    if getattr(args, "spec", None):
        return os.path.dirname(os.path.abspath(args.spec))
    raise SystemExit("需要 --run 或 --spec")


def load_spec(run_dir: str) -> dict:
    path = os.path.join(run_dir, "deck_spec.json")
    if not os.path.isfile(path):
        raise SystemExit(f"找不到 {path}")
    return sm.load_spec(path)


def load_plan(run_dir: str) -> dict:
    path = os.path.join(run_dir, "editable", PLAN_NAME)
    if not os.path.isfile(path):
        raise SystemExit(f"还没 prepare：{path} 不存在")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_plan(run_dir: str, plan: dict) -> str:
    directory = os.path.join(run_dir, "editable")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, PLAN_NAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)
    return path


def image_pptx(run_dir: str, spec: dict) -> str:
    return os.path.join(run_dir, "out", f"{spec['meta']['title']}-图片版.pptx")


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def cmd_doctor(args) -> int:
    runtime, label, _ = mp.guard()
    skill_dir, tried = mp.find_skill_dir()
    report = {
        "editppt": shutil.which("editppt"),
        "upstream_builder": runtime,
        "upstream_builder_source": label,
        "upstream_skill_dir": skill_dir,
        "upstream_skill_dir_tried": [str(item) for item in tried][-4:],
        "merge_available": bool(runtime),
    }
    if skill_dir:
        report["read_first"] = [os.path.join(skill_dir, "SKILL.md"),
                                os.path.join(skill_dir, "references", "page-decision-tree.md"),
                                os.path.join(skill_dir, "references", "manifest-schema.md"),
                                os.path.join(skill_dir, "references", "cli-helper.md")]
        report["note"] = ("如果 `skill` 工具里没有 image-to-editable-ppt，就直接读上面的文件并照此执行；"
                          "本技能的脚本只负责编排。")
    if shutil.which("editppt"):
        proc = subprocess.run(["editppt", "doctor"], capture_output=True, text=True, timeout=180)
        report["editppt_doctor"] = (proc.stdout or proc.stderr).strip().splitlines()
    if skill_dir:
        builder = os.path.join(skill_dir, "scripts", "build-page-worker-prompt.py")
        report["worker_prompt_builder"] = builder if os.path.isfile(builder) else None
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = bool(report["editppt"]) and bool(skill_dir)
    if not runtime:
        print("⚠ 合并适配器不可用：默认模式将只能逐页交付 page.pptx，"
              "或改用 --subagents 模式。", file=sys.stderr)
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# prepare
# --------------------------------------------------------------------------- #
def _apply_edit_settings(edit_model: str | None, edit_quality: str | None) -> dict:
    settings = {}
    if edit_model:
        run_cmd(["editppt", "config", "--model", edit_model])
        settings["model"] = edit_model
    if edit_quality:
        settings["quality"] = edit_quality
    return settings


def cmd_prepare(args) -> int:
    run_dir = run_dir_of(args)
    spec = load_spec(run_dir)
    pages = spec["pages"]
    if args.pages:
        wanted = {int(x) for x in args.pages.split(",")}
        pages = [p for p in pages if p["index"] in wanted]
    settings = _apply_edit_settings(args.edit_model, args.edit_quality)
    editable_dir = os.path.join(run_dir, "editable")
    os.makedirs(editable_dir, exist_ok=True)

    if args.subagents:
        deck_pptx = image_pptx(run_dir, spec)
        if not os.path.isfile(deck_pptx):
            raise SystemExit(f"找不到图片版 PPTX：{deck_pptx}（先跑 deck.py pptx）")
        concurrency = args.page_worker_concurrency or 3
        run_dir_out = os.path.join(editable_dir, "run")
        run_cmd(["editppt", "prepare", deck_pptx, "--job-dir", run_dir_out,
                 "--max-concurrent-pages", str(concurrency)])
        plan = {
            "mode": "multi-page-run",
            "run": run_dir_out,
            "concurrency": min(6, concurrency),
            "notes_source": deck_pptx,
            "edit_settings": settings,
            "next": f"python3 {os.path.join(HERE, 'editable_run.py')} next --run {run_dir_out}",
        }
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print("\n子代理模式：并行派 page worker（并发 "
              f"{plan['concurrency']}），保持槽位满载、谁先回谁先 record。")
    else:
        parts_dir = os.path.join(editable_dir, "parts")
        os.makedirs(parts_dir, exist_ok=True)
        parts = {}
        for page in pages:
            image = os.path.join(run_dir, "images", f"page-{page['index']:02d}.png")
            if not os.path.isfile(image):
                raise SystemExit(f"缺页图：{image}")
            part_dir = os.path.join(parts_dir, f"p{page['index']:02d}")
            run_cmd(["editppt", "prepare", image, "--job-dir", part_dir])
            parts[str(page["index"])] = part_dir
        plan = {
            "mode": "single-page-runs",
            "parts": parts,
            "parts_dir": parts_dir,
            "merge_out": os.path.join(run_dir, "out", f"{spec['meta']['title']}-元素版.pptx"),
            "edit_settings": settings,
            "notes_source": os.path.join(run_dir, "deck_spec.json"),
        }
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    path = save_plan(run_dir, plan)
    print(f"\n计划已写入：{path}")
    if not args.subagents:
        print(f"逐页流程：{os.path.join(HERE, 'editable_run.py')} prompt --run "
              f"{run_dir}/editable/parts/p01 --page <page_id>")
    return 0


# --------------------------------------------------------------------------- #
# 转发上游命令
# --------------------------------------------------------------------------- #
def cmd_next(args) -> int:
    run_cmd(["editppt", "run", "next", run_dir_of(args)])
    return 0


def cmd_status(args) -> int:
    run_cmd(["editppt", "run", "status", run_dir_of(args)], check=False)
    return 0


def cmd_prompt(args) -> int:
    skill_dir, _ = mp.find_skill_dir()
    if not skill_dir:
        raise SystemExit("找不到 image-to-editable-ppt 技能目录（需要 scripts/build-page-worker-prompt.py）")
    builder = os.path.join(skill_dir, "scripts", "build-page-worker-prompt.py")
    run = os.path.abspath(args.run)
    out = args.out or os.path.join(run, "pages", args.page, "worker-prompt.md")
    out = os.path.abspath(out)
    run_cmd([sys.executable, builder, run, "--page", args.page, "--out", out])

    annex = []
    if os.path.isfile(ANNEX_PATH):
        with open(ANNEX_PATH, encoding="utf-8") as fh:
            annex.append(fh.read().strip())
    if args.efficiency_annex and annex:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write("\n\n---\n\n" + "\n\n".join(annex) + "\n")
        print(f"已追加效率附录：{ANNEX_PATH}")
    print(json.dumps({"prompt_file": out,
                      "dispatch": f"editppt run dispatch {run} --page {args.page} "
                                  f"--agent-id <id> --prompt-file {out}"
                                  + (" --local" if args.local else "")},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_dispatch(args) -> int:
    command = ["editppt", "run", "dispatch", os.path.abspath(args.run), "--page", args.page,
               "--agent-id", args.agent_id]
    if args.prompt_file:
        command += ["--prompt-file", os.path.abspath(args.prompt_file)]
    if args.local:
        command.append("--local")
    run_cmd(command)
    return 0


def cmd_record(args) -> int:
    run_cmd(["editppt", "run", "record", os.path.abspath(args.run), "--page", args.page,
             "--agent-id", args.agent_id], check=False)
    return 0


def cmd_finalize(args) -> int:
    run_cmd(["editppt", "run", "finalize", os.path.abspath(args.run)], check=False)
    return 0


def cmd_reset(args) -> int:
    command = ["editppt", "run", "reset", os.path.abspath(args.run), "--page", args.page]
    if args.agent_id:
        command += ["--agent-id", args.agent_id]
    if args.confirm_lost:
        command.append("--confirm-lost")
    run_cmd(command, check=False)
    return 0


# --------------------------------------------------------------------------- #
# merge（默认模式收尾）
# --------------------------------------------------------------------------- #
def cmd_merge(args) -> int:
    run_dir = run_dir_of(args)
    plan = load_plan(run_dir)
    if plan.get("mode") != "single-page-runs":
        print("当前是子代理模式（multi-page-run）：请用 `editppt run finalize` 完成，无需合并。",
              file=sys.stderr)
        return 2
    parts_dir = args.parts or plan["parts_dir"]
    out = args.out or plan["merge_out"]
    parts = mp.list_parts(parts_dir)
    if not parts:
        print(f"✗ {parts_dir} 里没有已重建的单页 run", file=sys.stderr)
        return 2
    spec = load_spec(run_dir)
    merged_dir = os.path.join(run_dir, "editable", "merged")
    result = mp.build_and_validate(parts, spec, merged_dir, out,
                                   source=os.path.join(run_dir, "deck_spec.json"),
                                   dry_run=args.dry_run)
    print(json.dumps({k: v for k, v in result.items() if k != "validation_report"},
                     ensure_ascii=False, indent=2))
    if not result["ok"]:
        print("✗ 合并未通过：" + str(result.get("reason")), file=sys.stderr)
        print("降级：逐页交付 " + ", ".join(
            os.path.join(p["page_dir"], "page.pptx") for p in parts), file=sys.stderr)
        return 1
    print(f"✓ 元素版：{out}（{result['pages']} 页，备注 {result['notes']} 条，"
          f"validation={(result.get('validation_report') or {}).get('passed')}）")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="editable_run.py", description="元素版流程编排（委托 image-to-editable-ppt）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="检查 editppt / 上游技能目录 / 合并适配器")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("prepare", help="准备元素版 run（单页 run 集合 或 多页 run）")
    p.add_argument("--spec")
    p.add_argument("--run")
    p.add_argument("--subagents", action="store_true", help="使用子代理模式（多页 run + 并行 page worker）")
    p.add_argument("--pages", help="只处理部分页，如 1,2,3")
    p.add_argument("--edit-model", help="写进 editppt 配置的资产分离用生图模型")
    p.add_argument("--edit-quality", help="写进 worker prompt 的质量档位建议")
    p.add_argument("--page-worker-concurrency", type=int, default=3)
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("next", help="转发 editppt run next")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("status", help="转发 editppt run status")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("prompt", help="生成 page worker prompt（可追加效率附录）")
    p.add_argument("--run", required=True, help="该页所在的 run 目录")
    p.add_argument("--page", required=True)
    p.add_argument("--out")
    p.add_argument("--local", action="store_true", help="单页 run 的本地重建模式")
    p.add_argument("--no-efficiency-annex", dest="efficiency_annex", action="store_false",
                   help="不追加效率附录")
    p.set_defaults(func=cmd_prompt, efficiency_annex=True)

    p = sub.add_parser("dispatch", help="转发 editppt run dispatch")
    p.add_argument("--run", required=True)
    p.add_argument("--page", required=True)
    p.add_argument("--agent-id", required=True)
    p.add_argument("--prompt-file")
    p.add_argument("--local", action="store_true")
    p.set_defaults(func=cmd_dispatch)

    p = sub.add_parser("record", help="转发 editppt run record")
    p.add_argument("--run", required=True)
    p.add_argument("--page", required=True)
    p.add_argument("--agent-id", default="main")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("finalize", help="转发 editppt run finalize")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_finalize)

    p = sub.add_parser("reset", help="转发 editppt run reset")
    p.add_argument("--run", required=True)
    p.add_argument("--page", required=True)
    p.add_argument("--agent-id")
    p.add_argument("--confirm-lost", action="store_true")
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("merge", help="默认模式：把单页 run 合并成一份多页元素版 PPTX")
    p.add_argument("--spec")
    p.add_argument("--run")
    p.add_argument("--parts")
    p.add_argument("--out")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_merge)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
