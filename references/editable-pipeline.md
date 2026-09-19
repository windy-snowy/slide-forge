# 元素版流程契约（委托 image-to-editable-ppt）

slide-forge 只做编排。**页面重建的全部规则以 `image-to-editable-ppt` 的 `SKILL.md` 及其
`references/` 为准**；本文件只记录"为什么这样编排"和两条路径的接口。

## 一、必须遵守的上游约束（已读源码核实）

| 约束 | 出处 |
| --- | --- |
| `--local`（主 agent 本地重建）**只允许 run 恰好只有一页** | `cli/editppt/runtime/record_page_dispatch.py:55` |
| 多页输入必须派 page worker；无子代理能力时"停止并报告"，**禁止**降级为主 agent 重建多页 run | 上游 `SKILL.md` Entry Contract |
| 主 agent 不得写任何页面重建产物，除非单页本地模式已 `dispatch --local` 记录声明 | 上游 `SKILL.md` Entry Contract |
| 所有状态推进只能通过 `editppt` 命令，不得手写 run/page 状态 JSON | 上游 `SKILL.md` Entry Contract |
| 页内图像任务串行；前景资产必须来自真实图像编辑而非近似替代 | 上游 `SKILL.md` / `page-decision-tree.md` |

因此多页元素版只有两条合规路径。

## 二、默认路径：N 个单页 run + 合并

```
editppt prepare <page-01.png> --job-dir <run>/editable/parts/p01
   └─ run 恰好一页 → run next 返回 rebuild_page_locally
      → build-page-worker-prompt.py 生成 worker-prompt.md
      → editppt run dispatch ... --local        （记录主 agent 认领）
      → 主 agent 按 worker prompt 重建该页
      → editppt run record / editppt run finalize
… 重复 p02 … pNN
merge_pages.py  →  一份多页元素版 PPTX
```

### 合并为什么不需要写 XML

复用上游自带构建器：

```bash
python3 <runtime>/build_pptx_from_manifest.py --deck-manifest <merged>/deck_manifest.json --out <pptx>
python3 <runtime>/validate_pptx.py <pptx> --deck-manifest <merged>/deck_manifest.json --report <merged>/validation.json
```

- `page_entries_from_deck_manifest()` 以 `deck_manifest["job_dir"]` 为根，按 `pages[].manifest`
  相对路径读每页 manifest（`build_pptx_from_manifest.py:759-769`）；
- 图片资产按**各自 manifest 所在目录**解析（`:742-747`），所以给每页目录做软链即可；
- 讲者备注按 `notes_manifest.json` 的 `page_index` 对齐页序（`:729-756`）。

`merge_pages.py` 只做三件事：生成合并清单、生成备注清单、把 `merged/pages/page_NNN`
软链到 `parts/pNN/pages/page_001`（软链失败自动改拷贝）。

### 版本守卫与降级

`merge_pages.py` 会依次尝试：`SLIDEFORGE_I2E_SKILL_ROOT` 环境变量 → `editppt` 实际加载的
`editppt/runtime` → 常见技能目录（`~/.dsh/skills`、`~/.claude/skills`、`~/.agents/skills` …）。
优先用 **CLI 实际加载的那份 runtime**，保证与 `editppt run finalize` 行为一致。

找不到 `build_pptx_from_manifest.py` / `validate_pptx.py` 或校验 `passed != true` 时：

1. **不伪造成功**；
2. 逐页交付 `editable/parts/pNN/pages/page_001/page.pptx`；
3. 提示用户改用 `--subagents` 模式。

## 三、子代理路径：单次多页 run

```
editppt prepare <title>-图片版.pptx --job-dir <run>/editable/run --max-concurrent-pages K
   └─ run next 返回 dispatch_pages
      → 每页：build-page-worker-prompt.py → subagent 派 worker → run dispatch（记录真实派工）
      → worker 返回后 run record（失败用 send_message 让原 worker 只修受影响产物）
   └─ run next 返回 finalize 阶段 → editppt run finalize
```

用图片版 PPTX（而非 PNG 列表）作为输入的好处：上游会从 PPTX 抽取 `notes_manifest.json`，
**讲者备注自动保留**，不需要合并阶段再注入。

## 四、模式选择

| 条件 | 选择 |
| --- | --- |
| 用户说了"用子代理模式/并行加速" | `--subagents` |
| 其他任何情况（**默认**） | 单页 run + 合并 |
| 只有 1 页 | 两条路径等价，都走 `--local` |

## 五、验证清单

- [ ] 每个单页 run 都 `finalize` 成功（或子代理 run `finalize` 成功）
- [ ] `validation.json` 顶层 `passed: true`
- [ ] 合并后的 PPTX 幻灯片数 == 页数
- [ ] 讲者备注条数 == 有备注的页数
- [ ] 用 LibreOffice/PowerPoint 打开，文字能单独选中编辑（不是整页图片盖在上面）
- [ ] `manifest.json` 里 `text_inventory` 的关键文字都能在 PPT 里选中
