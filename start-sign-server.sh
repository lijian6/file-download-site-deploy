#!/usr/bin/env bash
# ---------------------------------------------------------------
# sign_server 启动脚本（被 systemd 调用，也可手动执行调试）
# ============================================================
# ===== 只需改这 4 行 =====
BUCKET="你的bucket名"
ENDPOINT="https://oss-cn-hangzhou.aliyuncs.com"
PREFIX="files/"
EXPIRES="300"
# ===== 有效期单位秒：300=5分钟，900=15分钟，3600=1小时（官方上限 32400）=====
# ============================================================
set -u

# 载入密钥（复用 oss_sync.sh 用的同一个凭据文件）
if [ -f /root/.oss_credentials ]; then
    set -a
    . /root/.oss_credentials
    set +a
fi

if [ -z "${OSS_ACCESS_KEY_ID:-}" ] || [ -z "${OSS_ACCESS_KEY_SECRET:-}" ]; then
    echo "[ERROR] 缺少 OSS 密钥，请建 /root/.oss_credentials（内容见手册 7.3 节）" >&2
    exit 1
fi

# 找 Python（systemd 下 PATH 很干净，必须显式探测宝塔 pyenv）
PY=""
for c in /www/server/panel/pyenv/bin/python python3 python /usr/bin/python3 /usr/local/bin/python3; do
    if [ "${c:0:1}" = "/" ]; then
        [ -x "$c" ] && PY="$c" && break
    else
        command -v "$c" >/dev/null 2>&1 && PY="$(command -v "$c")" && break
    fi
done
if [ -z "$PY" ]; then
    echo "[ERROR] 找不到 Python 3" >&2
    exit 1
fi

if ! "$PY" -c 'import oss2' >/dev/null 2>&1; then
    echo "[ERROR] 缺少 oss2： $PY -m pip install oss2" >&2
    exit 1
fi

exec "$PY" /root/sign_server.py \
    --bucket "$BUCKET" \
    --endpoint "$ENDPOINT" \
    --prefix "$PREFIX" \
    --expires "$EXPIRES" \
    --host 127.0.0.1 \
    --port 5099 \
    --log /root/sign-server.log
