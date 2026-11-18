#!/usr/bin/env bash
# ---------------------------------------------------------------
# check_deploy.sh - 部署自检：一条命令查出哪一步没做对
#
# 用法：
#   bash /root/check_deploy.sh /www/wwwroot/你的站点
#   bash /root/check_deploy.sh /www/wwwroot/你的站点 8080
#   bash /root/check_deploy.sh /www/wwwroot/你的站点 8080 193.112.171.210
#
# 第三个参数是公网 IP，给了就额外检查「从外网能不能访问」。
# 只读检查，不改任何文件。
# ---------------------------------------------------------------
set -u

SITE="${1:-}"
PORT="${2:-8080}"
PUBIP="${3:-}"

PASS=0
FAIL=0
WARN=0
ok()   { echo "  [OK] $*"; PASS=$((PASS + 1)); }
bad()  { echo "  [!!] $*"; FAIL=$((FAIL + 1)); }
warn() { echo "  [??] $*"; WARN=$((WARN + 1)); }

if [[ -z "$SITE" ]]; then
    echo "用法: bash check_deploy.sh <站点根目录> [端口] [公网IP]"
    echo "例如: bash check_deploy.sh /www/wwwroot/files.tmp 8080 1.2.3.4"
    exit 1
fi
SITE="${SITE%/}"

# 找 Python
PY=""
for c in python3 python /www/server/panel/pyenv/bin/python /usr/bin/python3 /usr/local/bin/python3; do
    if [[ "$c" == /* ]]; then
        [[ -x "$c" ]] && PY="$c" && break
    else
        command -v "$c" >/dev/null 2>&1 && PY="$(command -v "$c")" && break
    fi
done

echo "=============================================="
echo " 部署自检"
echo " 站点根目录 : $SITE"
echo " 端口       : $PORT"
echo " 公网 IP    : ${PUBIP:-（未指定，跳过外网检查）}"
echo " Python     : ${PY:-未找到}"
echo "=============================================="
echo

echo "[1] 目录结构"
if [[ -d "$SITE" ]]; then
    ok "根目录存在"
else
    bad "根目录不存在：$SITE"
    echo
    echo "路径都找不到，后面的检查没有意义。先确认站点根目录："
    echo "  find /www/wwwroot -maxdepth 3 -name index.html"
    exit 1
fi

if [[ -f "$SITE/index.html" ]]; then
    ok "index.html 存在（$(wc -c < "$SITE/index.html") 字节）"
else
    bad "index.html 不存在，站点包没解压到位"
fi

if [[ -d "$SITE/assets/css" && -d "$SITE/assets/js" ]]; then
    ok "assets/css 与 assets/js 存在"
else
    bad "assets/ 不完整（可能是用了带 .fancyindex 的旧包）"
fi

if [[ -d "$SITE/files" ]]; then
    n=$(ls -A "$SITE/files" 2>/dev/null | wc -l)
    ok "files/ 目录存在，内有 $n 个条目"
else
    warn "还没有 files/ 目录（不影响使用，放文件时再建）"
fi

echo
echo "[2] index.html 前端配置"
if [[ -f "$SITE/index.html" ]]; then
    grep -q "jsonUrl: '/list.json'" "$SITE/index.html" && ok "jsonUrl 指向 /list.json" \
        || bad "jsonUrl 配置缺失（前端可能加载不到列表）"
    grep -q "routerMode: 'hash'" "$SITE/index.html" && ok "routerMode 为 hash（无需伪静态）" \
        || warn "routerMode 不是 hash，可能需要配伪静态"
    if grep -q "baseUrl: " "$SITE/index.html"; then
        b=$(grep -o "baseUrl: [^,]*" "$SITE/index.html" | head -1)
        ok "baseUrl 已配置：$b"
    else
        bad "baseUrl 配置缺失"
    fi
    grep -q "__BASE_URL__\|__TITLE__" "$SITE/index.html" && bad "存在未替换的模板占位符" \
        || ok "无遗留模板占位符"
else
    warn "index.html 缺失，跳过本组检查"
fi

echo
echo "[3] list.json 数据"
if [[ -f "$SITE/list.json" ]]; then
    sz=$(wc -c < "$SITE/list.json")
    ok "list.json 存在（$sz 字节）"
    if [[ -n "$PY" ]]; then
        "$PY" - "$SITE/list.json" <<'PYEOF'
import json, re, sys
p = sys.argv[1]
try:
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
except Exception as e:
    print("  [!!] list.json 无法解析：%s" % e)
    sys.exit(10)
if not isinstance(d, dict) or d.get("name") != "/" or not isinstance(d.get("children"), list):
    print("  [!!] list.json 结构不对，应为 {name:'/', children:[...]}")
    sys.exit(11)
f = dc = 0
def walk(cs):
    global f, dc
    for c in cs:
        if "children" in c:
            dc += 1
            walk(c["children"])
        else:
            f += 1
walk(d["children"])
if f == 0:
    print("  [??] list.json 里没有文件，站点会显示「没有文件」（放文件后重跑 scan.sh）")
else:
    print("  [OK] list.json 结构正确：%d 个文件 / %d 个目录" % (f, dc))
top = [c["name"] for c in d["children"]][:6]
print("       顶层条目：" + (", ".join(top) if top else "（空）"))
text = open(p, encoding="utf-8").read()
bad = re.findall(r"[\u0400-\u04FF\u2500-\u257F]", text)
if bad:
    print("  [!!] 检测到 CP866 乱码字符 %r，文件名被 ZIP 解压弄坏了" % bad[:5])
    print("       处理：bash /root/fix_names.sh %s  然后扫一次" % p.rsplit("/list.json", 1)[0])
    sys.exit(12)
else:
    print("  [OK] 未检测到乱码字符")
PYEOF
        rc=$?
        [[ $rc -eq 0 ]] && PASS=$((PASS + 2)) || FAIL=$((FAIL + 1))
    else
        warn "没有 Python，跳过 JSON 解析检查"
    fi
else
    bad "list.json 不存在（没跑 scan.sh，或输出到了别处）"
fi

echo
echo "[4] Web 服务"
if command -v ss >/dev/null 2>&1; then
    if ss -lnt 2>/dev/null | grep -q ":$PORT[[:space:]]"; then
        ok "有程序在监听 $PORT"
    else
        bad "没有程序监听 $PORT（Nginx 没起来，或 listen 还是 80）"
    fi
else
    warn "没有 ss 命令，跳过端口监听检查"
fi

if command -v curl >/dev/null 2>&1; then
    code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "http://127.0.0.1:$PORT/" 2>/dev/null || echo "000")
    if [[ "$code" == "200" ]]; then
        ok "本机首页 HTTP 200"
    else
        bad "本机首页返回 $code（期望 200）"
    fi

    jcode=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "http://127.0.0.1:$PORT/list.json" 2>/dev/null || echo "000")
    if [[ "$jcode" == "200" ]]; then
        ct=$(curl -s -I -m 5 "http://127.0.0.1:$PORT/list.json" 2>/dev/null | grep -i '^content-type' | tr -d '\r')
        ok "本机 list.json HTTP 200  ${ct:+($ct)}"
    else
        bad "本机 list.json 返回 $jcode（期望 200）"
    fi

    css=$(grep -o 'href="/assets/css/[^"]*"' "$SITE/index.html" 2>/dev/null | head -1 | sed 's/.*="//; s/"$//')
    if [[ -n "$css" ]]; then
        ccode=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "http://127.0.0.1:$PORT$css" 2>/dev/null || echo "000")
        [[ "$ccode" == "200" ]] && ok "样式文件 HTTP 200（$css）" || bad "样式文件返回 $ccode（$css）"
    fi

    if [[ -n "$PUBIP" ]]; then
        pcode=$(curl -s -o /dev/null -w "%{http_code}" -m 8 "http://$PUBIP:$PORT/" 2>/dev/null || echo "000")
        if [[ "$pcode" == "200" ]]; then
            ok "外网访问 HTTP 200（http://$PUBIP:$PORT/）"
        else
            bad "外网访问返回 $pcode —— 多半是安全组或宝塔防火墙没放行 $PORT"
        fi
    fi
else
    warn "没有 curl，跳过 HTTP 检查"
fi

echo
echo "[5] 工具脚本"
for f in scan.py scan.sh; do
    if [[ -f "/root/$f" ]]; then
        ok "/root/$f 就位"
    else
        warn "/root/$f 缺失（生成列表要用）"
    fi
done
if [[ -x "/root/scan.sh" ]]; then
    ok "/root/scan.sh 有执行权限"
else
    warn "/root/scan.sh 没有执行权限（bash 调用其实不需要，建议 chmod +x /root/*.sh）"
fi
for f in fix_names.sh check_deploy.sh; do
    [[ -f "/root/$f" ]] && ok "/root/$f 就位" || warn "/root/$f 未上传（可选，建议传）"
done

echo
echo "=============================================="
echo " 通过 $PASS 项 / 失败 $FAIL 项 / 警告 $WARN 项"
if [[ $FAIL -eq 0 ]]; then
    echo " 结论：关键项全部通过，站点可用。"
    [[ $WARN -gt 0 ]] && echo "       有警告项，按需处理即可。"
else
    echo " 结论：有 $FAIL 项失败，见上面带 [!!] 的条目。"
    echo "       排查思路见《文件下载站-部署与维护手册》第六章。"
fi
echo "=============================================="
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
