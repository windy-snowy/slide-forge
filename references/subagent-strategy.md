# 子代理加速策略

**默认不使用子代理。** 只有用户明确说"用子代理模式 / 并行加速 / subagents / 多代理跑"时才启用
（`--subagents`）。启用后按下面的策略把墙钟时间压到最短。

## 一、先分清"哪一步值得并行"

| 阶段 | 并行手段 | 为什么不用子代理 |
| --- | --- | --- |
| 规格与提示词 | 无（本来就快） | —— |
| 逐页生图 | **进程内并发**：`deck.py gen --concurrency 3` | 每页只是一次 HTTP 调用 + 本地 16:9 适配；派 LLM 子代理纯属浪费 token 和时间 |
| 质量闸门 | **进程内并发**（`qa.py`） | 同上 |
| 元素版页面重建 | **子代理**（每页一个 worker） | 这一步真的需要 LLM 逐页做对象决策，只有它能并行 |

## 二、元素版并行调度

### 并发度 K

```
K = min(--page-worker-concurrency, 6, page_jobs.json.max_concurrent_pages, 剩余页数)
```

默认 3。取值理由：单页 asset separation 会打 3–8 次 `editppt image` 调用，K=3 时峰值约
20+ 并发请求，多数中转站会开始 429；K=6 只在后端明确宽松时使用。

### 无栅栏流水线（关键）

```
派 K 个 worker  ──┐
                  ├─ 谁先返回 → run record → 立刻补派下一个 pending 页
                  │                              （不留空槽）
                  └─ 重复直到没有 pending 页
```

不要用"整批派完再整批收"的栅栏式调度：那会让 K 个槽位在每轮末尾空转，浪费 `K-1` 个页面时长。

### 限流自适应

- 命中 429/超时：把 K 降到 2，对**该页**重试一次；不要把已经跑着的 worker 杀掉。
- 连续两轮 429：`--edit-quality low` 降档，减少每页图像调用。
- 同一页的 worker 慢 ≠ 失败：活跃租约不能 reset、不能重启（上游规则）。

## 三、降低单页成本的四个开关

1. **效率附录**：`editable_run.py prompt` 会自动把
   `prompts/page-worker-efficiency-annex.md` 追加到 worker prompt，约束它"原生形状优先、
   资产合并 ≤2 张 sheet、页内图像任务串行"。
2. **一次 prepare**：OCR hints 只跑一次，所有 worker 复用；不要每页单独 prepare。
3. **模型分档**：结构类资产用低档质量，只对细节资产提档；`--edit-model` 与阶段 2 的
   生图模型解耦，可以把阶段 2 用高档、阶段 3 用低档。
4. **共享风格契约**：把 `风格锁定与每页提示词.md` 放在 run 根目录，worker prompt 用绝对路径
   引用它，避免每个 worker 重新推导主题。

## 四、失败处理

| 情况 | 处置 |
| --- | --- |
| `run record` 校验失败 | `send_message` 给**原 worker**，只修受影响的产物，然后重新 validate + record |
| worker 终止/失败/归档 | `editppt run reset <run> --page <id> --agent-id <id> --confirm-lost` 后重新派 |
| worker 慢但仍在工作 | 什么都不做，等它；`run next` 返回 `wait` 就等 |
| 预算超限 | 停止补派新页，保留已完成页，报告已花成本与剩余页 |

## 五、并行下的记账

父 agent 每 `record` 一页就把该页 `pages/page_NNN/imagegen-jobs.json` 的成本累加进
`qa/usage.json` 的 `editable` 段；全部完成后汇报：

```
元素版：N 页，K=3 流水线，墙钟 X 分钟，图像任务 M 次，累计成本 C
```

实测数据（3 页小样、单页 run 串行 vs K=3 流水线）写进 README 的对比表。

## 六、页数 = 1 时

不需要子代理，也不需要合并：直接
`editable_run.py prepare --spec <spec>`（单页 run）→ `prompt --local` → `dispatch --local`
→ 主 agent 重建 → `record` → `finalize`。产物就是最终的 `<title>-元素版.pptx`。
