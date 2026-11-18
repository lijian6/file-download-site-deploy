#!/usr/bin/env bash
# ---------------------------------------------------------------
# 阿里云 OSS 一键同步文件列表（生成 list.json）
#
# 首次使用：
#   1) 改下面 4 行配置（也可以用同名环境变量覆盖）
#   2) 密钥放 /root/.oss_credentials，内容两行：
#        export OSS_ACCESS_KEY_ID="LTAI..."
#        export OSS_ACCESS_KEY_SECRET="..."
#      然后 chmod 600 /root/.oss_credentials
#      建议用 RAM 子账号，只授 oss:ListObjects 只读权限，不要用主账号密钥
#   3) 装 SDK： <探测到的python> -m pip install oss2
#   4) bash /root/oss_sync.sh
#
# 放进宝塔「计划任务」定时跑即可自动同步（增删文件后列表才会更新）
#
# 把 oss_sync.sh / scan_bucket.sh / scan_bucket.py 放同一目录（例如 /root/）
# ---------------------------------------------------------------
set -u

# ===== 只需改这 4 行 =====
OSS_BUCKET="${OSS_BUCKET:-your-bucket-name}"
OSS_ENDPOINT="${OSS_ENDPOINT:-https://oss-cn-hangzhou.aliyuncs.com}"
OSS_PREFIX="${OSS_PREFIX:-files/}"
SITE_ROOT="${SITE_ROOT:-/www/wwwroot/your-site}"
# ========================

# 仅供离线自检：指定一个 JSON 清单就不连 OSS
OSS_FROM_JSON="${OSS_FROM_JSON:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "$SCRIPT_DIR/scan_bucket.sh" || ! -f "$SCRIPT_DIR/scan_bucket.py" ]]; then
    echo "[ERROR] 请把 scan_bucket.sh 和 scan_bucket.py 放到与 oss_sync.sh 同一目录"
    exit 1
fi

# 找 Python（宝塔 Linux 面板自带 pyenv，PATH 里通常没有 python3）
PY=""
for c in python3 python /www/server/panel/pyenv/bin/python /usr/bin/python3 /usr/local/bin/python3; do
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
    echo "[ERROR] 没找到 Python 3。诊断： cat /etc/os-release; ls -l /www/server/panel/pyenv/bin/python*"
    exit 1
fi

if [[ -z "$OSS_FROM_JSON" ]]; then
    if [[ "$OSS_BUCKET" == "your-bucket-name" || "$SITE_ROOT" == "/www/wwwroot/your-site" ]]; then
        echo "[ERROR] 请先编辑 oss_sync.sh 顶部的 OSS_BUCKET 和 SITE_ROOT 两行"
        exit 1
    fi
    if [[ ! -d "$SITE_ROOT" ]]; then
        echo "[ERROR] 网站根目录不存在：$SITE_ROOT"
        exit 1
    fi

    # 密钥：优先环境变量，其次读取凭据文件
    if [[ -z "${OSS_ACCESS_KEY_ID:-}" && -f /root/.oss_credentials ]]; then
        . /root/.oss_credentials
    fi
    if [[ -z "${OSS_ACCESS_KEY_ID:-}" || -z "${OSS_ACCESS_KEY_SECRET:-}" ]]; then
        echo "[ERROR] 缺少 OSS 密钥。二选一："
        echo '  1) export OSS_ACCESS_KEY_ID=xxx; export OSS_ACCESS_KEY_SECRET=xxx'
        echo '  2) 建 /root/.oss_credentials（内容见脚本顶部注释），chmod 600'
        exit 1
    fi
    if ! "$PY" -c 'import oss2' >/dev/null 2>&1; then
        echo "[ERROR] 缺少 oss2 SDK，用这条安装： $PY -m pip install oss2"
        exit 1
    fi
    echo "[oss] Python   : $PY"
    echo "[oss] Bucket   : $OSS_BUCKET"
    echo "[oss] Endpoint : $OSS_ENDPOINT"
    echo "[oss] 前缀     : $OSS_PREFIX"
else
    echo "[oss] 离线自检模式：$OSS_FROM_JSON（不连接 OSS）"
fi
echo "[oss] 输出     : $SITE_ROOT/list.json"
echo ""

if [[ -n "$OSS_FROM_JSON" ]]; then
    ARGS=(--from-json "$OSS_FROM_JSON" --prefix "$OSS_PREFIX")
else
    ARGS=(--provider oss --bucket "$OSS_BUCKET" --endpoint "$OSS_ENDPOINT" --prefix "$OSS_PREFIX")
fi
ARGS+=(--output "$SITE_ROOT/list.json")

if [[ -f "$SITE_ROOT/descriptions.json" ]]; then
    ARGS+=(--desc "$SITE_ROOT/descriptions.json")
fi

bash "$SCRIPT_DIR/scan_bucket.sh" "${ARGS[@]}"
RC=$?
if [[ $RC -ne 0 ]]; then
    echo "[FAILED] 同步失败，退出码 $RC，请把上面的输出整段贴回来"
    exit "$RC"
fi

if [[ -s "$SITE_ROOT/list.json" ]]; then
    echo ""
    echo "[OK] list.json 已更新（$(wc -c < "$SITE_ROOT/list.json") 字节），浏览器 Ctrl+F5 刷新"
    echo "     记得 index.html 的 baseUrl 要指向 OSS 公网域名，否则文件会 404"
else
    echo "[FAILED] list.json 未生成或为空"
    exit 3
fi
