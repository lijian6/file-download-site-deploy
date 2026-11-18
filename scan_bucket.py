#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_bucket.py - 从对象存储生成 down_52pojie_cn 前端所需的 list.json

与 scan.py 的区别：scan.py 扫服务器本地目录，本脚本列对象存储的 Bucket，
把扁平的 Object Key 还原成目录树，输出格式完全一致：
    {"name":"/","children":[{"name":"目录","children":[...]},
                            {"name":"文件.zip","size":123,"time":1730000000}]}

支持：
    COS  腾讯云对象存储   --provider cos
    OSS  阿里云对象存储   --provider oss
    JSON 离线清单         --from-json objects.json（无需 SDK，可用于测试/手工维护）

密钥优先从环境变量读取，避免出现在命令行历史里：
    COS: COS_SECRET_ID / COS_SECRET_KEY      也可 --secret-id / --secret-key
    OSS: OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET   也可 --access-key-id / --access-key-secret

示例：
  # 腾讯云 COS
  python3 scan_bucket.py --provider cos --bucket my-1250000000 \
      --region ap-guangzhou --prefix files/ --output /www/wwwroot/site/list.json

  # 阿里云 OSS
  python3 scan_bucket.py --provider oss --bucket my-bucket \
      --endpoint https://oss-cn-hangzhou.aliyuncs.com --prefix files/ \
      --output /www/wwwroot/site/list.json

  # 离线清单
  python3 scan_bucket.py --from-json objects.json --output ./list.json

注意：前端下载链接由 build_site.py 的 --base-url 决定，必须指向 Bucket 的
公网访问域名（或绑定的自定义域名），否则会拼成当前站点地址导致 404。
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# 对象存储里如果存在这些，属于站点自身文件，不展示
DEFAULT_EXCLUDE = {
    "index.html", "list.json", "list.js", "descriptions.json", "favicon.ico",
    "robots.txt", "404.html", "LICENSE.txt", "web.config",
}
EXCLUDE_PREFIXES = ("assets/", ".", "__pycache__/")


def log(m):
    print("[bucket] " + m, flush=True)


def to_epoch(value):
    """COS 返回 ISO8601 字符串，OSS 返回 Unix 秒整数"""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
            try:
                return int(datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                continue
    return int(time.time())


def list_cos(args):
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError:
        log("缺少腾讯云 COS SDK，请先安装：")
        log("  python3 -m pip install cos-python-sdk-v5")
        log("  （宝塔可用 /www/server/panel/pyenv/bin/python -m pip install cos-python-sdk-v5）")
        return None
    sid = args.secret_id or os.environ.get("COS_SECRET_ID")
    skey = args.secret_key or os.environ.get("COS_SECRET_KEY")
    if not (sid and skey):
        log("缺少 COS 密钥：请设置环境变量 COS_SECRET_ID / COS_SECRET_KEY，或用 --secret-id / --secret-key")
        return None
    client = CosS3Client(CosConfig(Region=args.region, SecretId=sid, SecretKey=skey))
    out, marker = [], ""
    while True:
        resp = client.list_objects(Bucket=args.bucket, Prefix=args.prefix,
                                   Marker=marker, MaxKeys=1000)
        for o in resp.get("Contents", []):
            out.append({"key": o["Key"], "size": int(o["Size"]),
                        "time": to_epoch(o.get("LastModified"))})
        if str(resp.get("IsTruncated", "false")).lower() == "true":
            marker = resp.get("NextMarker", "")
            if not marker:
                break
        else:
            break
    return out


def list_oss(args):
    try:
        import oss2
    except ImportError:
        log("缺少阿里云 OSS SDK，请先安装： python3 -m pip install oss2")
        return None
    ak = args.access_key_id or os.environ.get("OSS_ACCESS_KEY_ID")
    sk = args.access_key_secret or os.environ.get("OSS_ACCESS_KEY_SECRET")
    if not (ak and sk):
        log("缺少 OSS 密钥：请设置环境变量 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET")
        return None
    b = oss2.Bucket(oss2.Auth(ak, sk), args.endpoint, args.bucket)
    out = []
    for o in oss2.ObjectIterator(b, prefix=args.prefix):
        out.append({"key": o.key, "size": int(o.size), "time": to_epoch(o.last_modified)})
    return out


def load_desc(path):
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise ValueError("描述文件必须是 JSON 对象")
    log("已加载 %d 条描述" % len(d))
    return d


def insert(root, parts, size, mtime, desc):
    node = root
    for i, part in enumerate(parts):
        rel = "/".join(parts[:i + 1])
        if i == len(parts) - 1:
            item = {"name": part, "size": size, "time": mtime}
            if rel in desc:
                item["description"] = str(desc[rel])
            node["children"].append(item)
        else:
            nxt = next((c for c in node["children"]
                        if c["name"] == part and "children" in c), None)
            if nxt is None:
                nxt = {"name": part, "children": []}
                if rel in desc:
                    nxt["description"] = str(desc[rel])
                node["children"].append(nxt)
            node = nxt


def sort_tree(node):
    node["children"].sort(key=lambda c: ("children" not in c, c["name"]))
    for c in node["children"]:
        if "children" in c:
            sort_tree(c)


def build_tree(objects, prefix, desc, excludes, strip_prefix=False):
    root = {"name": "/", "children": []}
    skipped = 0
    for o in objects:
        key = o["key"]
        # 默认保留完整 Key：路径与 Bucket 中的对象一一对应，下载链接才不会少一层
        rel = key[len(prefix):] if (strip_prefix and prefix and key.startswith(prefix)) else key
        rel = rel.lstrip("/")
        if not rel or rel.endswith("/"):
            skipped += 1
            continue                       # 目录占位对象
        if rel in DEFAULT_EXCLUDE or rel in excludes:
            skipped += 1
            continue
        if any(rel.startswith(p) for p in EXCLUDE_PREFIXES):
            skipped += 1
            continue
        parts = rel.split("/")
        if any(p in DEFAULT_EXCLUDE or p.startswith(".") for p in parts[:-1]):
            skipped += 1
            continue
        insert(root, parts, o["size"], o["time"], desc)
    sort_tree(root)
    return root, skipped


def count(node):
    """兼容传入根节点 dict 或 children 列表"""
    children = node["children"] if isinstance(node, dict) else node
    f = d = b = 0
    for c in children:
        if "children" in c:
            d += 1
            a, bb, cc = count(c)
            f, d, b = f + a, d + bb, b + cc
        else:
            f += 1
            b += c.get("size", 0)
    return f, d, b


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return "%.1f %s" % (n, u)
        n /= 1024.0
    return "%.1f PB" % n


def main():
    ap = argparse.ArgumentParser(description="从对象存储生成 list.json")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--provider", choices=["cos", "oss"], help="对象存储厂商")
    src.add_argument("--from-json", help="离线对象清单 JSON：[{key,size,time}, ...]")
    ap.add_argument("--bucket", help="Bucket 名称")
    ap.add_argument("--region", default="ap-guangzhou", help="COS 地域，默认 ap-guangzhou")
    ap.add_argument("--endpoint", default="", help="OSS 外网 Endpoint")
    ap.add_argument("--prefix", default="", help="只列出该前缀下的对象，例如 files/（仅过滤，不改变路径）")
    ap.add_argument("--strip-prefix", action="store_true",
                    help="生成路径时去掉 --prefix 这一层；开启后 baseUrl 必须包含该前缀")
    ap.add_argument("--secret-id", default="", help="COS SecretId（建议用环境变量）")
    ap.add_argument("--secret-key", default="", help="COS SecretKey（建议用环境变量）")
    ap.add_argument("--access-key-id", default="", help="OSS AccessKeyId（建议用环境变量）")
    ap.add_argument("--access-key-secret", default="", help="OSS AccessKeySecret（建议用环境变量）")
    ap.add_argument("--output", default="./list.json", help="输出路径")
    ap.add_argument("--desc", default="", help="描述文件 descriptions.json 路径")
    ap.add_argument("--exclude", action="append", default=[], help="额外排除的对象相对路径，可重复")
    ap.add_argument("--dry-run", action="store_true", help="只打印统计，不写文件")
    args = ap.parse_args()

    started = time.time()
    if args.from_json:
        with open(args.from_json, "r", encoding="utf-8") as f:
            objects = json.load(f)
        if not isinstance(objects, list):
            ap.error("--from-json 必须是数组")
        objects = [{"key": o["key"], "size": int(o.get("size", 0)),
                    "time": to_epoch(o.get("time"))} for o in objects]
        log("离线清单：%s（%d 个对象）" % (args.from_json, len(objects)))
    elif args.provider == "cos":
        if not args.bucket:
            ap.error("COS 需要 --bucket")
        objects = list_cos(args)
    else:
        if not args.bucket or not args.endpoint:
            ap.error("OSS 需要 --bucket 和 --endpoint")
        objects = list_oss(args)
    if objects is None:
        return 2

    log("拉取到 %d 个对象，耗时 %.2fs" % (len(objects), time.time() - started))
    if args.strip_prefix and args.prefix:
        log("注意：已剥离前缀 %s，index.html 的 baseUrl 必须包含它，例如 https://域名/%s" % (
            args.prefix, args.prefix.strip("/")))
    desc = load_desc(args.desc)
    tree, skipped = build_tree(objects, args.prefix, desc, set(args.exclude), args.strip_prefix)
    f, d, b = count(tree["children"])
    log("生成 %d 个文件、%d 个目录、合计 %s，跳过 %d 个站点自身/占位对象" % (
        f, d, human(b), skipped))
    log("顶层条目：%s" % (", ".join(c["name"] for c in tree["children"][:8]) or "（空）"))

    if args.dry_run:
        print(json.dumps(tree, ensure_ascii=False, indent=2)[:2000])
        return 0

    payload = json.dumps(tree, ensure_ascii=False, separators=(",", ":"))
    out = os.path.abspath(args.output)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fobj:
        fobj.write(payload)
    os.replace(tmp, out)
    try:
        os.chmod(out, 0o644)
    except OSError:
        pass

    with open(out, "r", encoding="utf-8") as fobj:
        check = json.load(fobj)
    if check.get("name") != "/" or not isinstance(check.get("children"), list):
        log("校验失败：输出结构不合法")
        return 3
    f2, d2, _ = count(check["children"])
    log("校验通过：回读 %d 文件 / %d 目录，list.json %s" % (f2, d2, human(os.path.getsize(out))))
    log("完成。浏览器 Ctrl+F5 刷新；别忘了 index.html 的 baseUrl 要指向 Bucket 公网域名")
    return 0


if __name__ == "__main__":
    sys.exit(main())
