#!/usr/bin/env bash
# slide-forge 安装脚本：把本技能装到各 agent 的技能目录。
#
#   ./install.sh                      # 软链到 ~/.dsh/skills/slide-forge（DSH 默认）
#   ./install.sh --copy               # 复制而不是软链（Windows / 不支持软链时）
#   ./install.sh --target ~/.claude/skills
#   ./install.sh --uninstall
#
# 环境变量：DSH_HOME（默认 ~/.dsh）、AGENTS_HOME（默认 ~/.agents）
set -euo pipefail

NAME="slide-forge"
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="link"
TARGET=""
UNINSTALL=0
WITH_UPSTREAM=0

while [ $# -gt 0 ]; do
  case "$1" in
    --copy) MODE="copy" ;;
    --link) MODE="link" ;;
    --target) TARGET="${2:-}"; shift ;;
    --name) NAME="${2:-}"; shift ;;
    --with-upstream) WITH_UPSTREAM=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
  shift
done

if [ -z "$TARGET" ]; then
  TARGET="${DSH_HOME:-$HOME/.dsh}/skills"
fi
DEST="$TARGET/$NAME"

if [ "$UNINSTALL" = "1" ]; then
  if [ -L "$DEST" ]; then rm -f "$DEST"; echo "已移除软链 $DEST"
  elif [ -d "$DEST" ]; then rm -rf "$DEST"; echo "已删除目录 $DEST"
  else echo "没有找到 $DEST"; fi
  exit 0
fi

if [ ! -f "$SOURCE/SKILL.md" ]; then
  echo "✗ $SOURCE 下没有 SKILL.md，安装中止" >&2
  exit 2
fi

mkdir -p "$TARGET"
if [ -e "$DEST" ] || [ -L "$DEST" ]; then
  echo "已存在，先移除：$DEST"
  rm -rf "$DEST"
fi

if [ "$MODE" = "copy" ]; then
  mkdir -p "$DEST"
  for item in SKILL.md README.md README.en.md LICENSE CHANGELOG.md CONTRIBUTING.md \
              scripts prompts references docs tests examples assets install.sh; do
    [ -e "$SOURCE/$item" ] && cp -R "$SOURCE/$item" "$DEST/"
  done
  echo "✓ 已复制到 $DEST"
else
  ln -s "$SOURCE" "$DEST"
  echo "✓ 已软链 $DEST → $SOURCE"
fi

if [ "$WITH_UPSTREAM" = "1" ]; then
  for candidate in "$HOME/.dsh/skills/image-to-editable-ppt" "$HOME/.claude/skills/image-to-editable-ppt" \
                   "$HOME/.agents/skills/image-to-editable-ppt"; do
    if [ -f "$candidate/SKILL.md" ] && [ ! -e "$TARGET/image-to-editable-ppt" ]; then
      ln -s "$candidate" "$TARGET/image-to-editable-ppt"
      echo "✓ 同时链入了上游技能：$candidate"
      break
    fi
  done
fi

if [ ! -e "$TARGET/image-to-editable-ppt" ]; then
  echo
  echo "提示：本技能目录下没有 image-to-editable-ppt（元素版需要它）。"
  echo "     装法：npx -y skills@latest add ningzimu/image-to-editable-ppt-skill --skill image-to-editable-ppt --global"
  echo "     或用 ./install.sh --with-upstream 把已装好的那份链进来。"
fi

echo
echo "接下来："
echo "  1) 在新会话里让它出现（技能目录在会话开始时扫描）"
echo "  2) python3 $DEST/scripts/deck.py doctor"
echo "  3) 例：python3 $DEST/scripts/deck.py all \"给大学生讲 Transformer，科技风，10 页\" --until qa"
