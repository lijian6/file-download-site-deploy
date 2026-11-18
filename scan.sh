#!/usr/bin/env bash
# ---------------------------------------------------------------
# Linux launcher for scan.py (Baota Linux panel / any Linux server)
# Usage:  bash scan.sh /www/wwwroot/your-site
# Auto-detects Python 3 across PATH and Baota's bundled pyenv.
# Put scan.sh and scan.py in the SAME folder (e.g. /root/).
# ---------------------------------------------------------------
set -u

SITE="${1:-}"
if [[ -z "$SITE" ]]; then
    echo "Usage:  bash scan.sh /www/wwwroot/your-site"
    echo "Example: bash scan.sh /www/wwwroot/files.tmp"
    echo ""
    echo "站点根目录 = index.html 所在的目录。"
    echo "宝塔面板查看路径：网站 -> 你的站点 -> 设置 -> 基本 / 根目录。"
    exit 1
fi

if [[ ! -f "$SITE/index.html" ]]; then
    echo "[WARN] 未找到 $SITE/index.html ，请确认这是网站根目录"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCAN="$SCRIPT_DIR/scan.py"
if [[ ! -f "$SCAN" ]]; then
    echo "[ERROR] 同目录下找不到 scan.py：$SCAN"
    echo "请把 scan.py 和 scan.sh 一起上传到同一个目录（例如 /root/）"
    exit 1
fi

# 按优先级探测 Python 3；宝塔 Linux 面板自带 pyenv Python
CANDIDATES=(
    python3
    python
    /www/server/panel/pyenv/bin/python
    /usr/bin/python3
    /usr/local/bin/python3
    /usr/bin/python
)
PY=""
for c in "${CANDIDATES[@]}"; do
    if [[ "$c" == /* ]]; then
        p="$c"
        [[ -x "$p" ]] || continue
    else
        p="$(command -v "$c" 2>/dev/null)" || continue
        [[ -n "$p" ]] || continue
    fi
    if "$p" -c 'import sys;sys.exit(0 if sys.version_info[0]>=3 else 1)' >/dev/null 2>&1; then
        PY="$p"
        break
    fi
done

if [[ -z "$PY" ]]; then
    echo "[ERROR] 服务器上没找到可用的 Python 3，已尝试："
    printf '  %s\n' "${CANDIDATES[@]}"
    echo "请把下面这条诊断命令的输出贴回来："
    echo '  cat /etc/os-release; ls -l /www/server/panel/pyenv/bin/python*; which python3 python'
    exit 1
fi

echo "[scan] Python : $PY ($("$PY" -V 2>&1))"
echo "[scan] 站点根 : $SITE"
echo ""
"$PY" "$SCAN" "$SITE"
RC=$?
echo ""
if [[ $RC -eq 0 ]]; then
    echo "[OK] list.json 已生成，浏览器按 Ctrl+F5 强制刷新即可"
else
    echo "[FAILED] 退出码 $RC，请把上面的输出整段贴回来"
fi
exit "$RC"
