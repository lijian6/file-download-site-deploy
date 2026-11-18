#!/usr/bin/env bash
# ---------------------------------------------------------------
# Linux launcher for scan_bucket.py - 参数全部原样透传
# 与 scan.py / scan.sh / fix_names.py 放在同一目录（例如 /root/）
#
# 腾讯云 COS:
#   bash /root/scan_bucket.sh --provider cos --bucket my-1250000000 \
#        --region ap-guangzhou --prefix files/ \
#        --output /www/wwwroot/your-site/list.json
# 阿里云 OSS:
#   bash /root/scan_bucket.sh --provider oss --bucket my-bucket \
#        --endpoint https://oss-cn-hangzhou.aliyuncs.com --prefix files/ \
#        --output /www/wwwroot/your-site/list.json
# ---------------------------------------------------------------
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/scan_bucket.py"
if [[ ! -f "$TARGET" ]]; then
    echo "[ERROR] 同目录下找不到 scan_bucket.py：$TARGET"
    exit 1
fi

CANDIDATES=(
    python3 python
    /www/server/panel/pyenv/bin/python
    /usr/bin/python3 /usr/local/bin/python3 /usr/bin/python
)
PY=""
for c in "${CANDIDATES[@]}"; do
    if [[ "$c" == /* ]]; then
        p="$c"; [[ -x "$p" ]] || continue
    else
        p="$(command -v "$c" 2>/dev/null)" || continue
        [[ -n "$p" ]] || continue
    fi
    if "$p" -c 'import sys;sys.exit(0 if sys.version_info[0]>=3 else 1)' >/dev/null 2>&1; then
        PY="$p"; break
    fi
done

if [[ -z "$PY" ]]; then
    echo "[ERROR] 没找到可用的 Python 3，请把下面命令的输出贴回来："
    echo '  cat /etc/os-release; ls -l /www/server/panel/pyenv/bin/python*; which python3 python'
    exit 1
fi

echo "[bucket] Python : $PY ($("$PY" -V 2>&1))"
"$PY" "$TARGET" "$@"
exit $?
