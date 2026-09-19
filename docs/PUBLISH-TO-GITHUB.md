# 如何把 slide-forge 上传到 GitHub

面向第一次发布开源仓库的人，按顺序复制粘贴即可。全文假设仓库目录是 `<repo>`：

```bash
cd "/root/autodl-tmp/DSH/work space/slide-forge"   # 换成你的实际路径
```

---

## 第 0 步 · 推送前自检（**别跳过**）

```bash
cd <repo>

# 1) 确认没有任何密钥会被提交
grep -rInE "sk-[A-Za-z0-9_-]{10,}|API_KEY[[:space:]]*[:=][[:space:]]*[\"']?[A-Za-z0-9]" \
  --include="*.py" --include="*.md" --include="*.json" --include="*.sh" --include="*.yml" . \
  | grep -v "SLIDEFORGE_IMAGE_API_KEY\|OPENAI_API_KEY\|OPENROUTER_API_KEY" || echo "✓ 没扫到硬编码密钥"

# 2) 确认运行产物没被跟踪（.gitignore 已排除 deck-runs/、*.pptx、密钥文件等）
git status --short

# 3) 确认大文件（示例图压到 1280px 以内再入库）
find . -path ./.git -prune -o -type f -size +2M -print
```

任何一步发现问题，先加进 `.gitignore` 或删掉，再继续。

---

## 第 0.5 步 · 确认能连上 GitHub，并换成你自己的提交身份

```bash
# 1) 连通性（HTTPS 200 且 ls-remote 有输出就说明通）
curl -sS -o /dev/null -w "github http=%{http_code}\n" https://github.com
git ls-remote https://github.com/octocat/Hello-World.git HEAD
# 走代理时才需要：
#   export HTTPS_PROXY=http://127.0.0.1:7890
#   git config --global http.proxy http://127.0.0.1:7890
```

```bash
# 2) 换成你自己的身份（否则每个 commit 都会署上别人的名字）
git config user.name  "你的名字"
git config user.email "你的邮箱"

# 3) 把已有的历史作者一起改掉（git 2.25 实测可用，文件不变）
git rebase --root --exec 'git commit --amend --no-edit --reset-author'
git log --format='%h %an <%ae> %s' | head -5      # 确认作者已变
git ls-files | wc -l                              # 确认文件数量没变
```

> 想干脆只留一条提交（新仓库更常见）：
> ```bash
> git checkout --orphan fresh
> git add -A
> git commit -m "feat: slide-forge v0.1.0 —— 一句话生成图片版 / 元素版 PPT"
> git branch -D main && git branch -m main
> ```

---

## 第 1 步 · 初始化本地仓库

```bash
cd <repo>

# git >= 2.28
git init -b main

# git 更老（如 2.25）不支持 -b，用这两行代替
# git init && git symbolic-ref HEAD refs/heads/main

# 第一次用 git 才需要配身份（会写进每个 commit）
git config user.name  "你的名字"
git config user.email "你的邮箱"

git add .
git commit -m "feat: slide-forge v0.1.0 —— 一句话生成图片版 / 元素版 PPT"
```

检查一遍要提交的内容：

```bash
git log --stat -1
git ls-files | head -50
```

---

## 第 2 步 · 在 GitHub 建一个**空**仓库

1. 打开 <https://github.com/new>；
2. **Repository name**：`slide-forge`；
3. **Description**：`用一句自然语言描述生成整套 PPT：图片版 + 元素版（DSH skill）`；
4. 可见性：Public（想分享就选公开）；
5. ⚠️ **不要**勾 "Add a README file"、不要选 .gitignore、不要选 license ——
   本地已经有了，勾了会导致首次推送冲突；
6. 点 **Create repository**。

---

## 第 3 步 · 选一种认证方式（三选一）

### 方式 A：HTTPS + Personal Access Token（最简单）

```bash
# 1. 打开 https://github.com/settings/tokens → Generate new token (classic)
#    勾选 scope：repo（私有仓库还要 workflow）
# 2. 复制生成的 token（只显示一次）

cd <repo>
git remote add origin https://github.com/<你的用户名>/slide-forge.git
git push -u origin main
# 提示 Username 时填 GitHub 用户名
# 提示 Password 时【粘贴 token】，不是账号密码
```

想免去每次输入：

```bash
git config --global credential.helper store     # 明文存 ~/.git-credentials，注意安全
# 或 macOS: git config --global credential.helper osxkeychain
# 或 Linux: git config --global credential.helper 'cache --timeout=3600'
```

### 方式 B：SSH（长期用推荐）

```bash
ssh-keygen -t ed25519 -C "你的邮箱"          # 一路回车即可
cat ~/.ssh/id_ed25519.pub                     # 复制这一整行

# 打开 https://github.com/settings/keys → New SSH key → 粘贴 → Add SSH key
ssh -T git@github.com                         # 看到 "Hi <用户名>!" 就成功

cd <repo>
git remote add origin git@github.com:<你的用户名>/slide-forge.git
git push -u origin main
```

### 方式 C：用 `gh` CLI（本机默认没装）

```bash
# 装：https://github.com/cli/cli#installation
# Debian/Ubuntu: sudo apt install gh   ／  macOS: brew install gh
gh auth login                                  # 选 HTTPS + 浏览器登录
cd <repo>
gh repo create slide-forge --public --source=. --remote=origin --push
```

一步到位，不用自己建仓库。

---

## 第 4 步 · 验证推送成功

```bash
git remote -v
git branch -vv            # 应显示 main 跟踪 origin/main
git ls-remote --heads origin
```

刷新 `https://github.com/<你的用户名>/slide-forge`，应该能看到文件列表和 README 渲染。

---

## 第 5 步 · 把仓库"装修"成可分享的样子

在仓库页面点 **⚙ Settings / 编辑**：

| 位置 | 建议 |
| --- | --- |
| About 描述 | `用一句自然语言生成整套 PPT：图片版（整页图）+ 元素版（对象级可编辑）。DSH skill，支持多种生图模型与飞桨 OCR。` |
| Website | 有文档站就填，没有可留空 |
| Topics | `dsh-skill` `dsh` `powerpoint` `pptx` `ai-agent` `image-generation` `gpt-image` `paddleocr` `slide-generator` `llm` |
| 勾选 | Issues、Discussions（想要社区反馈） |

**发首个 Release**：

```bash
cd <repo>
git tag -a v0.1.0 -m "slide-forge v0.1.0"
git push origin v0.1.0
```

然后 GitHub → Releases → **Draft a new release** → 选 `v0.1.0` → 写发布说明 → Publish。

**Badge**（README 顶部已经有）：

```markdown
[![CI](https://github.com/<用户名>/slide-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/<用户名>/slide-forge/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
```

---

## 第 6 步 · 后续更新流程

```bash
cd <repo>
git checkout -b feat/xxx
# …改代码…
git add -A && git commit -m "feat: xxx"
git push -u origin feat/xxx
# 去 GitHub 开 Pull Request → 合并回 main

# 打新版本
git checkout main && git pull
git tag -a v0.2.0 -m "slide-forge v0.2.0" && git push origin v0.2.0
```

---

## 第 7 步 · 别人怎么用你的仓库

```bash
git clone https://github.com/<用户名>/slide-forge.git ~/slide-forge
cd ~/slide-forge && ./install.sh                     # 软链到 ~/.dsh/skills/slide-forge
# 其他 agent：
#   ./install.sh --target ~/.claude/skills
#   ./install.sh --copy          # 不支持软链时
python3 ~/.dsh/skills/slide-forge/scripts/deck.py doctor
```

然后在对话里说："用 slide-forge 做一份 …… 的 PPT"。

---

## 第 8 步 · 用 `skills` CLI 安装（可选，附实测结论）

`npx -y skills@latest add <source>` 支持四种 source：**GitHub 仓库（`owner/repo`）、npm 包名、
HTTP(S) 上的 SKILL.md / 压缩包、以及本地路径**。它做的事是「把远程内容拉下来 → 找到 SKILL.md →
按 agent 目录安装」，所以：

- ✅ **本地路径现在就能装**（已实测，`--list` 能正确列出 `slide-forge`）：

  ```bash
  npx -y skills@latest add "$(pwd)" --list                 # 先看能发现哪些技能
  npx -y skills@latest add "$(pwd)" --skill slide-forge -a codebuddy --global
  ```

- ⏳ **`owner/repo` 写法要等推上 GitHub 之后**才有意义（没推就没有可拉取的地址）。
  > 实测：用 CLI 克隆一个**带几十 MB 展示素材**的仓库会撞上默认 300s 克隆超时
  > （`Clone timed out after 300s`）。本仓库 60 个文件 / 2.1MB，克隆很快；
  > 真遇到超时就 `SKILLS_CLONE_TIMEOUT_MS=600000`。
- ⚠️ **这个 CLI 不认识 DSH**：它支持的 agent 列表里有 `codebuddy`、`codex`、`claude`、`agents`
  等 50+，但**没有 `dsh`**，所以 `--global` 不会写进 `~/.dsh/skills`。要在 DSH 里用，选一条：

  1. **本仓库自带脚本**（最省事）：`git clone <你的仓库> && cd slide-forge && ./install.sh`
  2. 先装到它认识的目录，再软链给 DSH：
     ```bash
     npx -y skills@latest add <user>/slide-forge --skill slide-forge -a codebuddy --global
     ln -s ~/.codebuddy/skills/slide-forge "${DSH_HOME:-$HOME/.dsh}/skills/slide-forge"
     ```
     （本机实测 `DSH_HOME=/root/autodl-tmp/DSH/dsh-home`，所以真实目录是
     `/root/autodl-tmp/DSH/dsh-home/skills`；`./install.sh` 会自动用这个变量。）

本仓库的布局是**符合该 CLI 发现规则**的：它扫描仓库里任意 `SKILL.md`（大小写不敏感，排除
`node_modules/.git/dist/build/__pycache__`），根目录的 `SKILL.md` 也在优先列表里，只要求
frontmatter 有 `name` + `description` —— slide-forge 两者都有，且 `name` 是合法 kebab-case。

---

## 第 4.5 步 · 在 VS Code Remote / AutoDL 容器里推送（常见坑）

在 **VS Code Remote-SSH / AutoDL 容器**里推送时，可能遇到这种报错，而且**根本不弹密码提示**：

```
Missing or invalid credentials.
Error: connect ECONNREFUSED /tmp/vscode-git-xxxxxxxx.sock
remote: No anonymous write access.
fatal: Authentication failed for 'https://github.com/<user>/<repo>.git/'
```

原因：VS Code 往终端注入了 `GIT_ASKPASS` / `VSCODE_GIT_IPC_HANDLE`，让 git 走它的凭据助手；
一旦那个 socket 失效，git 既拿不到凭据、也不会回退到终端提示。**这不是 token 或仓库的问题。**

**修法 A：清掉 askpass，让 git 在终端里问（最快，用 PAT）**

```bash
unset GIT_ASKPASS SSH_ASKPASS VSCODE_GIT_IPC_HANDLE
export GIT_TERMINAL_PROMPT=1
git -c credential.helper= push -u origin main
# Username: <你的用户名>
# Password: 粘贴 PAT（输入时不显示）
```

**修法 B：改用 SSH（推荐，之后永不再输密钥）**

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C "<你的用户名>@users.noreply.github.com"
cat ~/.ssh/id_ed25519.pub          # 整行复制
# GitHub → Settings → SSH and GPG keys → New SSH key → 粘贴 → Add
ssh -T git@github.com              # 期望 "Hi <用户名>!"
git remote set-url origin git@github.com:<你的用户名>/<repo>.git
git push -u origin main
```

> `-N ""` 表示不设口令（省事）；想更安全就去掉它，并用 agent 记住口令：
> `eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519`
> 容器重置会丢 `~/.ssh`，长期使用建议把它放到数据盘再软链。

**修法 C（最后手段）：URL 里带 token**

```bash
git push https://<用户名>:<TOKEN>@github.com/<用户名>/<repo>.git main
```
token 会进 `~/.bash_history`（开头加空格可被 `HISTCONTROL=ignorespace` 忽略），事后请清理，
并且**不要**把带 token 的地址写进 `remote.origin.url`。

**推送前顺手清掉被 Ctrl+Z 挂起的任务：**

```bash
jobs          # 看到 [1]+ Stopped git push ... 就执行 kill %1
```

---

## 常见错误

| 现象 | 原因与解决 |
| --- | --- |
| `remote origin already exists` | `git remote set-url origin <新地址>` |
| `failed to push some refs (fetch first)` | 建仓库时勾了 README：`git pull --rebase origin main` 后再 push |
| `Support for password authentication was removed` | 必须用 PAT 或 SSH，不能用账号密码 |
| `Permission denied (publickey)` | SSH 公钥没加到 GitHub，或 `ssh -T git@github.com` 先测通 |
| `Missing or invalid credentials` + `ECONNREFUSED /tmp/vscode-git-*.sock` | VS Code 的 askpass 助手坏了：见「第 4.5 步」修法 A / B |
| `Clone timed out after 300s`（`skills` CLI） | 仓库太大或网慢：`SKILLS_CLONE_TIMEOUT_MS=600000`，或先手动 `git clone` 再把**本地路径**传给 `skills add` |
| `npx skills add` 找不到技能 | 确认仓库里有 `SKILL.md` 且 frontmatter 含 `name` + `description`；用 `--list` 先验证发现结果 |
| 推送了密钥 | **立刻**去服务商后台吊销并重新生成；然后用 `git filter-repo` 或 BFG 清理历史 |
| 文件太大被拒 | 把 `examples/` 里的图压到 1280px / <500KB，或改用 Git LFS |
| CI 红 | 先把 `python3 -m unittest discover -s tests` 在本地跑绿 |

---

## 安全清单（每次 push 前过一遍）

- [ ] `~/.editppt/config.yaml`、`~/.slideforge/config.json` 没有进仓库
- [ ] `deck-runs/`、`*.pptx`、生成的 PNG 没被跟踪
- [ ] `.env` 已被 `.gitignore` 覆盖
- [ ] 示例图里没有真实客户的敏感信息
- [ ] README 里的示例命令不含真实 token
- [ ] `git log -p | grep -i "sk-"` 无命中（历史也别漏）
