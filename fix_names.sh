#!/usr/bin/env bash
# ---------------------------------------------------------------
# Linux launcher for fix_names.py (same Python auto-detection as scan.sh)
# Usage:
#   bash fix_names.sh /www/wwwroot/your-site             # preview only
#   bash fix_names.sh /www/wwwroot/your-site --apply      # really rename
#   bash fix_names.sh /www/wwwroot/your-site --rollback rename-plan-xxx.json
# Put all four files in the SAME folder (e.g. /root/):
#   scan.py scan.sh fix_names.py fix_names.sh
# ---------------------------------------------------------------
set -u

ROOT="${1:-}"
if [[ -z "$ROOT" ]]; then
    echo "Usage:  bash fix_names.sh /www/wwwroot/your-site [--apply | --rollback plan.json]"
    echo ""
    echo "默认只预览，不会改任何文件。"
    exit 1
fi
shift
EXTRA=("$@")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/fix_names.py"
if [[ ! -f "$TARGET" ]]; then
    echo "[ERROR] 同目录下找不到 fix_names.py：$TARGET"
    exit 1
fi

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
    echo "[ERROR] 没找到可用的 Python 3，请把下面命令的输出贴回来："
    echo '  cat /etc/os-release; ls -l /www/server/panel/pyenv/bin/python*; which python3 python'
    exit 1
fi

echo "[fix] Python : $PY ($("$PY" -V 2>&1))"
echo "[fix] 站点根 : $ROOT"
echo ""
"$PY" "$TARGET" "$ROOT" "${EXTRA[@]}"
RC=$?
if [[ $RC -eq 0 ]]; then
    echo ""
    echo "[OK] 完成。记得重新生成列表： bash $SCRIPT_DIR/scan.sh $ROOT"
fi
exit "$RC"
