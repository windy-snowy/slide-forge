#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slide-forge 主 CLI：从一段描述到「图片版 / 元素版」两份 PPT。

    python3 deck.py doctor
    python3 deck.py spec skeleton --brief "给大学生讲 Transformer，科技风，10 页"
    python3 deck.py spec render --spec <run>/deck_spec.json
    python3 deck.py gen  --spec <run>/deck_spec.json [--dry-run] [--concurrency 3]
    python3 deck.py qa   --spec <run>/deck_spec.json [--no-ocr]
    python3 deck.py pptx --spec <run>/deck_spec.json
    python3 deck.py editable --spec <run>/deck_spec.json [--subagents]
    python3 deck.py all  --brief "..." [--until qa]

运行目录默认 <cwd>/deck-runs/<时间戳>-<slug>/，可用 --out-root 指定。
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
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import img_providers as ip  # noqa: E402
import qa as qa_mod  # noqa: E402
import spec_model as sm  # noqa: E402

REINFORCE = ("【重抽强化约束】上一版不合格，请特别注意：顶部标题整行必须完整可见且逐字正确；"
             "所有中文不得出现错别字、伪汉字或乱码；文字与图形必须离画面边缘至少 12% 的空白；"
             "画面必须有清晰的信息焦点，不得出现大面积空白或重复元素。")


# --------------------------------------------------------------------------- #
# 运行目录
# --------------------------------------------------------------------------- #
class Run:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.spec_path = os.path.join(self.root, "deck_spec.json")
        self.prompts_dir = os.path.join(self.root, "prompts")
        self.images_dir = os.path.join(self.root, "images")
        self.qa_dir = os.path.join(self.root, "qa")
        self.out_dir = os.path.join(self.root, "out")
        self.editable_dir = os.path.join(self.root, "editable")
        self.md_path = os.path.join(self.root, "风格锁定与每页提示词.md")

    def ensure(self) -> None:
        for path in (self.root, self.prompts_dir, self.images_dir, self.qa_dir, self.out_dir):
            os.makedirs(path, exist_ok=True)

    def load_spec(self) -> dict:
        if not os.path.isfile(self.spec_path):
            raise SystemExit(f"找不到 spec：{self.spec_path}（先跑 spec render / spec skeleton）")
        return sm.load_spec(self.spec_path)

    def image_path(self, index: int) -> str:
        matches = glob.glob(os.path.join(self.images_dir, f"page-{index:02d}.*"))
        return matches[0] if matches else os.path.join(self.images_dir, f"page-{index:02d}.png")

    def image_map(self) -> dict:
        return {page["index"]: self.image_path(page["index"]) for page in self.load_spec()["pages"]}


def new_run_dir(out_root: str | None, slug: str) -> Run:
    root = out_root or os.path.join(os.getcwd(), "deck-runs")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run = Run(os.path.join(root, f"{stamp}-{slug}"))
    run.ensure()
    return run


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def cmd_doctor(args) -> int:
    report = {"python": sys.version.split()[0], "editppt": shutil.which("editppt"),
              "soffice": shutil.which("soffice"), "slide_forge": os.path.dirname(HERE)}
    missing = []
    for module, label in (("PIL", "Pillow"), ("numpy", "numpy"), ("pptx", "python-pptx")):
        try:
            __import__(module)
            report[label] = "ok"
        except Exception:  # noqa: BLE001
            report[label] = "MISSING"
            missing.append(label)
    report["presets"] = sorted(sm.load_presets())
    report["image_backends"] = ip.doctor_report()
    try:
        proc = subprocess.run(["editppt", "doctor"], capture_output=True, text=True, timeout=180)
        report["editppt_doctor"] = (proc.stdout or proc.stderr).strip().splitlines()
    except Exception as exc:  # noqa: BLE001
        report["editppt_doctor"] = [f"failed: {exc}"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if missing:
        print(f"\n缺少依赖：{', '.join(missing)}。装法：pip install " +
              " ".join(m.lower().replace("pillow", "Pillow") for m in missing), file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------- #
# spec
# --------------------------------------------------------------------------- #
def cmd_spec_skeleton(args) -> int:
    spec = sm.new_spec(args.brief, title=args.title, audience=args.audience, purpose=args.purpose,
                       page_count=args.pages, duration_min=args.duration, language=args.language)
    if args.preset:
        spec["preset"] = args.preset
    spec, applied = sm.fill_defaults(spec)
    out = args.out or os.path.join(os.getcwd(), "deck_spec.json")
    sm.save_spec(spec, out)
    print(f"已写出 {out}｜预设 {spec['preset']}｜{len(spec['pages'])} 页")
    print("默认值补齐：" + "，".join(applied[:12]) + ("…" if len(applied) > 12 else ""))
    return 0


def cmd_spec_render(args) -> int:
    run = Run(os.path.dirname(os.path.abspath(args.spec))) if args.out_dir is None else Run(args.out_dir)
    run.ensure()
    spec = sm.fill_defaults(sm.load_spec(args.spec))[0]
    sm.save_spec(spec, run.spec_path)
    with open(run.md_path, "w", encoding="utf-8") as fh:
        fh.write(sm.render_markdown(spec))
    for page in spec["pages"]:
        path = os.path.join(run.prompts_dir, f"page-{page['index']:02d}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(sm.page_prompt(spec, page) + "\n")
    print(f"运行目录：{run.root}")
    print(f"  deck_spec.json            {run.spec_path}")
    print(f"  风格锁定与每页提示词.md    {run.md_path}")
    print(f"  prompts/page-NN.md        {len(spec['pages'])} 个")
    if args.print_first:
        print("\n" + "=" * 72 + f"\n第 {spec['pages'][0]['index']} 页提示词：\n" + "=" * 72)
        print(sm.page_prompt(spec, spec["pages"][0]))
    return 0


# --------------------------------------------------------------------------- #
# gen
# --------------------------------------------------------------------------- #
def _prompt_for(run: Run, spec: dict, page: dict) -> str:
    path = os.path.join(run.prompts_dir, f"page-{page['index']:02d}.md")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    return sm.page_prompt(spec, page)


def cmd_gen(args) -> int:
    run = Run(args.out_dir)
    spec = run.load_spec()
    only = {int(x) for x in args.only.split(",")} if args.only else None
    pages = [p for p in spec["pages"] if only is None or p["index"] in only]
    if not pages:
        raise SystemExit("--only 没有匹配任何页")
    cfg = ip.resolve_config(spec.get("backends"), {
        "provider": args.provider, "model": args.image_model, "quality": args.quality,
        "size": args.size, "fit": args.fit, "base_url": args.base_url, "api_key": args.api_key,
        "concurrency": args.concurrency,
    })
    concurrency = max(1, int(args.concurrency or spec.get("backends", {}).get("image", {})
                            .get("concurrency", 3)))
    print(f"后端 {cfg.provider}｜模型 {cfg.model}｜尺寸 {cfg.size}｜质量 {cfg.quality}｜"
          f"16:9 适配 {cfg.fit}｜并发 {concurrency}"
          f"{'｜DRY-RUN（不调用 API）' if args.dry_run else ''}")

    if args.dry_run:
        for page in pages:
            print("=" * 72)
            print(f"[第 {page['index']} 页 · {page['title']}]")
            print("-" * 72)
            print(_prompt_for(run, spec, page))
        print("=" * 72)
        print(f"共 {len(pages)} 页，dry-run 未调用任何 API。")
        return 0

    jobs = [(page, run.image_path(page["index"])) for page in pages]

    def work(job):
        page, path = job
        prompt = _prompt_for(run, spec, page)
        attempts, record = 0, None
        while attempts < 2:
            attempts += 1
            record = ip.generate(prompt if attempts == 1 else prompt + "\n\n" + REINFORCE,
                                 path, cfg, force=args.force, sleep=args.sleep)
            record["attempts"] = attempts
            if not record.get("error"):
                break
        record["index"] = page["index"]
        record["title"] = page["title"]
        return record

    started = time.time()
    results, spent = [], 0.0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(work, job): job for job in jobs}
        for future in as_completed(futures):
            record = future.result()
            results.append(record)
            spent += float(record.get("cost") or 0)
            label = f"P{record['index']:02d} {record['title'][:18]}"
            if record.get("error"):
                print(f"✗ {label:<28} {record['elapsed']:>6}s  {record['error'][:120]}")
            else:
                mark = "跳过" if record.get("skipped") else "✓"
                print(f"{mark} {label:<28} {record['elapsed']:>6}s  {record.get('size')}  "
                      f"成本={record.get('cost') if record.get('cost') is not None else '未返回'}")
            if args.max_cost and spent >= args.max_cost:
                print(f"⚠ 已达到 --max-cost {args.max_cost}，剩余页不再重试。")
    results.sort(key=lambda item: item["index"])
    usage = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provider": cfg.provider, "model": cfg.model, "size": cfg.size, "quality": cfg.quality,
        "items": results,
        "total_cost": round(spent, 4),
        "total_elapsed": round(time.time() - started, 1),
    }
    usage_path = os.path.join(run.qa_dir, "usage.json")
    previous = {}
    if os.path.isfile(usage_path):
        try:
            with open(usage_path, encoding="utf-8") as fh:
                previous = json.load(fh)
        except Exception:  # noqa: BLE001
            previous = {}
    merged = {item["index"]: item for item in previous.get("items", [])}
    merged.update({item["index"]: item for item in results})
    usage["items"] = [merged[k] for k in sorted(merged)]
    usage["total_cost"] = round(sum(float(i.get("cost") or 0) for i in usage["items"]), 4)
    with open(usage_path, "w", encoding="utf-8") as fh:
        json.dump(usage, fh, ensure_ascii=False, indent=2)

    failed = [r["index"] for r in results if r.get("error")]
    print(f"\n完成 {len(results) - len(failed)}/{len(results)} 页｜累计成本 {usage['total_cost']}"
          f"｜耗时 {usage['total_elapsed']}s｜记账 {usage_path}")
    if failed:
        print("失败页：" + ", ".join(str(i) for i in failed) + "（可用 --only 重跑）")
        return 1
    return 0


# --------------------------------------------------------------------------- #
# qa
# --------------------------------------------------------------------------- #
def cmd_qa(args) -> int:
    run = Run(args.out_dir)
    spec = run.load_spec()
    report = qa_mod.evaluate(spec["pages"], run.image_map(), use_ocr=not args.no_ocr,
                             out_dir=run.qa_dir)
    sheet = qa_mod.contact_sheet(
        run.image_map(), os.path.join(run.qa_dir, "contact-sheet.png"),
        labels={p["index"]: p["title"] for p in spec["pages"]})
    if sheet:
        report["contact_sheet"] = sheet
        with open(os.path.join(run.qa_dir, "qa_report.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    for page in report["pages"]:
        flag = {"pass": "✓", "warn": "!", "fail": "✗"}[page["status"]]
        ratio = page.get("mean_ratio")
        print(f"{flag} P{page['index']:02d} {str(page.get('title'))[:16]:<18} "
              f"{page.get('width')}x{page.get('height')}  std={page.get('std')}  "
              f"文本={ratio if ratio is not None else 'n/a'}  "
              + ("；".join(page["issues"] + page["warnings"])[:90] if
                 page["issues"] or page["warnings"] else "OK"))
    summary = report["summary"]
    print(f"\n合计 {summary['total']} 页：通过 {summary['pass']}｜警告 {summary['warn']}｜"
          f"不合格 {summary['fail']}")
    if sheet:
        print(f"总览图：{sheet}")
    print(f"报告：{os.path.join(run.qa_dir, 'qa_report.json')}")
    if summary["fail"]:
        print("不合格页：" + ", ".join(str(i) for i in summary["failed_pages"]) +
              "（可 `gen --only` 重抽）")
        return 1
    return 0


# --------------------------------------------------------------------------- #
# pptx
# --------------------------------------------------------------------------- #
def cmd_pptx(args) -> int:
    from pptx import Presentation

    run = Run(args.out_dir)
    spec = run.load_spec()
    meta = spec["meta"]
    title = meta["title"]
    images = run.image_map()
    missing = [i for i, path in images.items() if not os.path.isfile(path)]
    if missing:
        raise SystemExit(f"缺图：{missing}；先跑 deck.py gen")

    presentation = Presentation()
    presentation.slide_width, presentation.slide_height = _inches(13.333), _inches(7.5)
    blank = presentation.slide_layouts[6]
    for page in spec["pages"]:
        slide = presentation.slides.add_slide(blank)
        slide.shapes.add_picture(images[page["index"]], 0, 0,
                                 width=presentation.slide_width, height=presentation.slide_height)
        if meta.get("speaker_notes", True):
            slide.notes_slide.notes_text_frame.text = page.get("notes", "")
    out_path = os.path.join(run.out_dir, f"{title}-图片版.pptx")
    presentation.save(out_path)
    print(f"图片版 PPTX：{out_path}（{len(spec['pages'])} 页，{os.path.getsize(out_path)//1024} KB）")

    want_pdf = getattr(args, "pdf", None)
    if want_pdf is None:
        want_pdf = not getattr(args, "no_pdf", False)
    if want_pdf:
        pdf = _export_pdf(out_path, run.out_dir)
        print(f"PDF：{pdf}" if pdf else "PDF 导出跳过（未找到 soffice）")
    print(f"下一步（元素版）：python3 {os.path.join(HERE, 'editable_run.py')} prepare "
          f"--spec {run.spec_path}")
    return 0


def _inches(value: float):
    from pptx.util import Inches
    return Inches(value)


def _export_pdf(pptx_path: str, out_dir: str) -> str | None:
    if not shutil.which("soffice"):
        return None
    try:
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", out_dir, pptx_path],
                       capture_output=True, text=True, timeout=600, check=True)
    except Exception:  # noqa: BLE001
        return None
    candidate = os.path.join(out_dir, os.path.splitext(os.path.basename(pptx_path))[0] + ".pdf")
    return candidate if os.path.isfile(candidate) else None


# --------------------------------------------------------------------------- #
# all
# --------------------------------------------------------------------------- #
STAGES = ["render", "gen", "qa", "pptx", "editable"]


def cmd_all(args) -> int:
    if args.spec:
        spec = sm.fill_defaults(sm.load_spec(args.spec))[0]
        run = Run(os.path.dirname(os.path.abspath(args.spec)))
    else:
        if not args.brief:
            raise SystemExit("需要 --brief 或 --spec")
        spec = sm.new_spec(args.brief, title=args.title, page_count=args.pages,
                           audience=args.audience, purpose=args.purpose)
        if args.preset:
            spec["preset"] = args.preset
        run = new_run_dir(args.out_root, sm.slugify(spec["meta"].get("title") or args.brief))
        spec = sm.fill_defaults(spec)[0]
        sm.save_spec(spec, run.spec_path)
    run.ensure()
    until = args.until or "pptx"
    if until not in STAGES:
        raise SystemExit(f"--until 只能是 {', '.join(STAGES)}")

    rc = cmd_spec_render(argparse.Namespace(spec=run.spec_path, out_dir=run.root,
                                            print_first=args.print_first))
    if rc or until == "render":
        return rc
    rc = cmd_gen(argparse.Namespace(out_dir=run.root, only=args.only, force=args.force,
                                    dry_run=args.dry_run, provider=args.provider,
                                    image_model=args.image_model, quality=args.quality,
                                    size=args.size, fit=args.fit, base_url=args.base_url,
                                    api_key=args.api_key, concurrency=args.concurrency,
                                    sleep=args.sleep, max_cost=args.max_cost))
    if rc or until == "gen" or args.dry_run:
        return rc
    rc = cmd_qa(argparse.Namespace(out_dir=run.root, no_ocr=args.no_ocr))
    if until == "qa":
        return rc
    if rc:
        print("\n⚠ 质量闸门未通过：先处理不合格页，再继续 pptx/editable。")
        return rc
    rc = cmd_pptx(argparse.Namespace(out_dir=run.root, pdf=not args.no_pdf))
    if rc or until == "pptx":
        return rc
    return cmd_editable(argparse.Namespace(out_dir=run.root, spec=run.spec_path,
                                           subagents=args.subagents,
                                           edit_model=args.edit_model,
                                           edit_quality=args.edit_quality,
                                           page_worker_concurrency=args.page_worker_concurrency))


# --------------------------------------------------------------------------- #
# editable（转发给 editable_run.py）
# --------------------------------------------------------------------------- #
def cmd_editable(args) -> int:
    command = [sys.executable, os.path.join(HERE, "editable_run.py"), "prepare",
               "--spec", args.spec or Run(args.out_dir).spec_path]
    for flag, value in (("--edit-model", getattr(args, "edit_model", None)),
                        ("--edit-quality", getattr(args, "edit_quality", None)),
                        ("--page-worker-concurrency", getattr(args, "page_worker_concurrency", None))):
        if value:
            command += [flag, str(value)]
    if getattr(args, "subagents", False):
        command.append("--subagents")
    proc = subprocess.run(command, text=True)
    return proc.returncode


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deck.py", description="slide-forge：一句话生成「图片版 / 元素版」PPT")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="环境自检（依赖 / 生图后端 / editppt / OCR）")
    p.set_defaults(func=cmd_doctor)

    spec = sub.add_parser("spec", help="规格：生成骨架 / 渲染提示词文档")
    spec_sub = spec.add_subparsers(dest="spec_command", required=True)
    p = spec_sub.add_parser("skeleton", help="从一段描述生成最小 deck_spec.json")
    p.add_argument("brief")
    p.add_argument("--out")
    p.add_argument("--pages", type=int)
    p.add_argument("--title")
    p.add_argument("--audience")
    p.add_argument("--purpose")
    p.add_argument("--duration", type=int)
    p.add_argument("--language")
    p.add_argument("--preset")
    p.set_defaults(func=cmd_spec_skeleton)

    p = spec_sub.add_parser("render", help="补默认值并渲染提示词文档与逐页提示词")
    p.add_argument("--spec", required=True)
    p.add_argument("--out-dir")
    p.add_argument("--print-first", action="store_true", help="打印第一页的最终提示词")
    p.set_defaults(func=cmd_spec_render)

    def add_gen_flags(p, require_out_dir=True):
        p.add_argument("--spec")
        p.add_argument("--out-dir", required=require_out_dir)
        p.add_argument("--only")
        p.add_argument("--force", action="store_true")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--provider", choices=ip.PROVIDERS)
        p.add_argument("--image-model")
        p.add_argument("--quality", choices=["low", "medium", "high", "auto", "xhigh", "max"])
        p.add_argument("--size")
        p.add_argument("--fit", choices=["auto", "pad", "crop", "none"])
        p.add_argument("--base-url")
        p.add_argument("--api-key")
        p.add_argument("--concurrency", type=int, default=3)
        p.add_argument("--sleep", type=float, default=1.0)
        p.add_argument("--max-cost", type=float)

    p = sub.add_parser("gen", help="逐页生成图片")
    add_gen_flags(p)
    p.set_defaults(func=cmd_gen)

    p = sub.add_parser("qa", help="逐页质量闸门 + 总览图")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--no-ocr", action="store_true")
    p.set_defaults(func=cmd_qa)

    p = sub.add_parser("pptx", help="组装图片版 PPTX（含讲者备注）与 PDF")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--no-pdf", action="store_true")
    p.set_defaults(func=cmd_pptx)

    p = sub.add_parser("editable", help="进入元素版流程（转发 editable_run.py）")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--spec")
    p.add_argument("--subagents", action="store_true")
    p.add_argument("--edit-model")
    p.add_argument("--edit-quality")
    p.add_argument("--page-worker-concurrency", type=int)
    p.set_defaults(func=cmd_editable)

    p = sub.add_parser("all", help="一条命令走完流程（可 --until 分阶段停下）")
    p.add_argument("brief", nargs="?")
    p.add_argument("--out-root")
    p.add_argument("--until", choices=STAGES, default="pptx")
    p.add_argument("--pages", type=int)
    p.add_argument("--title")
    p.add_argument("--audience")
    p.add_argument("--purpose")
    p.add_argument("--preset")
    p.add_argument("--print-first", action="store_true")
    p.add_argument("--no-ocr", action="store_true")
    p.add_argument("--no-pdf", action="store_true")
    p.add_argument("--subagents", action="store_true")
    p.add_argument("--edit-model")
    p.add_argument("--edit-quality")
    p.add_argument("--page-worker-concurrency", type=int)
    add_gen_flags(p, require_out_dir=False)
    p.set_defaults(func=cmd_all)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "out_dir", None) and args.command in {"gen", "qa", "pptx"}:
        Run(args.out_dir).ensure()
    try:
        return args.func(args)
    except BrokenPipeError:  # 管道被 head 截断时安静退出
        try:
            sys.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
