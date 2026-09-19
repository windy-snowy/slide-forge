# 生图后端与模型

## 一、四种后端

| `provider` | 协议 | 典型模型 | 原生 16:9 | 适用 |
| --- | --- | --- | --- | --- |
| `openai-images` | `POST {base}/v1/images/generations`，读 `data[0].b64_json` 或 `url` | `gpt-image-1`、`gpt-image-1.5`、`gpt-image-2`、`gpt-image-2.5` | ❌ | 官方 OpenAI 或兼容中转站（最常见） |
| `chat-image` | `POST {base}/v1/chat/completions` + `modalities:["image","text"]` | 各类多模态出图中转站 | 视模型 | 只暴露 chat 路由的中转站 |
| `openrouter-images` | `POST {base}/api/v1/images`，带 `aspect_ratio` | `google/gemini-3.1-flash-image`（Nano Banana 2）等 | ✅ | 想直接拿 16:9、少一次适配 |
| `editppt-cli` | 调用 `editppt image generate` | 由 `~/.editppt/config.yaml` 决定 | 视模型 | 已经配好 `editppt`、不想再配一套密钥 |

后端自动推断：显式 `--provider` > `SLIDEFORGE_IMAGE_PROVIDER` > `spec.backends.image.provider` >
`~/.slideforge/config.json` > 默认 `openai-images`。

## 二、密钥与地址

优先级：命令行参数 > 环境变量 > `~/.slideforge/config.json`（chmod 600）。

| 变量 | 作用 |
| --- | --- |
| `SLIDEFORGE_IMAGE_API_KEY` | 统一密钥（最高优先） |
| `SLIDEFORGE_IMAGE_BASE_URL` | 统一 base（如 `https://api.openai.com` 或中转站 `https://xxx/v1`） |
| `SLIDEFORGE_IMAGE_MODEL` | 统一模型名 |
| `SLIDEFORGE_IMAGE_PROVIDER` | 统一后端 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | 兼容 OpenAI 生态的通用写法 |
| `OPENROUTER_API_KEY` | OpenRouter |

`{base}` 末尾带不带 `/v1` 都能用，脚本会自动拼对路径。

`config.json` 示例：

```json
{ "provider": "openai-images", "api_key": "sk-...", "base_url": "https://api.openai.com/v1",
  "model": "gpt-image-2" }
```

## 三、参数

| 参数 | 说明 |
| --- | --- |
| `--image-model` | 模型名，直接透传 |
| `--size` | gpt-image 系列常用 `1024x1024` / `1536x1024` / `1024x1536`；`auto` 由服务端决定 |
| `--quality` | `low` / `medium` / `high` / `auto`（部分新模型还支持 `xhigh` / `max`） |
| `--fit` | `auto`（推荐）/ `pad` / `crop` / `none` |
| `--concurrency` | 进程内并发页数，默认 3；中转站限流明显就降到 2 |
| `--max-cost` | 累计成本上限（依据响应里的 `usage`，拿不到就不限制） |

## 四、成本与质量取舍（经验值）

| 档位 | 适用 |
| --- | --- |
| `--quality low` | 屏幕投影、内部分享、先跑小样确认构图与中文正确性 |
| `--quality medium` | 默认；正式分享 |
| `--quality high` | 大屏/印刷/关键页单独提档 |

小样先行是**最省钱的流程**：`gen --only 1,2,3 --quality low` → 看 contact sheet → 通过再全量。

## 五、16:9 适配细节

`img_providers.to_169(path, mode)`（移植自已验证的实现）：

- `auto`：先判断内容高度能否放进 16:9；能就**居中智能裁切**，不能就转 `pad`。
- `pad`：整图按 16:9 放大后高斯模糊做底，再把原图羽化贴到中间，两侧加暗角过渡——**内容零损失**。
- `crop`：强制居中裁切。
- `none`：不动。

## 六、常见错误

| 报错 | 原因与处置 |
| --- | --- |
| `缺少 <provider> 的 API Key` | 按上表配密钥 |
| `HTTP 401` | key 无效或 base 不匹配 |
| `HTTP 403 额度不足` | 账户余额不足，直接告知用户，**不要**反复重试 |
| `HTTP 429` | 限流；脚本会指数退避重试，持续出现就 `--concurrency 2` |
| `响应里没有图片` | 该模型不支持图片输出，换模型 |
| 返回外链而非 base64 | 脚本会自动下载外链；下载失败就看网络/代理 |
