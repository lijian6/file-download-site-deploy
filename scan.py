#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan.py - 生成 down_52pojie_cn (爱盘前端) 所需的 list.json

只依赖 Python 3 标准库，不需要 PHP / Composer / 第三方包。
输出格式与官方 php/scan.php 完全一致：
    {"name": "/", "children": [
        {"name": "目录", "children": [...], "description": "..."},
        {"name": "文件.zip", "size": 12345, "time": 1699999999, "description": "..."}
    ]}

用法：
    # 最简：扫描网站根目录，结果写到同目录 list.json
    python3 scan.py /www/wwwroot/1.2.3.4_8080

    # 完整参数
    python3 scan.py --root /www/wwwroot/站点 --output /www/wwwroot/站点/list.json \
                    --desc /www/wwwroot/站点/descriptions.json --exclude 临时目录 --exclude cache

    # 只看结果不写文件
    python3 scan.py /path/to/site --dry-run

建议把本脚本放在网站根目录之外（例如 /root/scan.py），避免被 Web 直接下载。
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

# 站点自身文件：不出现在下载列表里，也不暴露给访客
DEFAULT_EXCLUDE_NAMES = {
    "index.html", "index.htm", "list.json", "list.js", "list.yaml", "list.yml",
    "descriptions.json", "description.yml", "robots.txt", "favicon.ico",
    "404.html", ".htaccess", ".user.ini", "scan.py", "build_site.py", "scan.bat",
    "scan.ps1", "check.bat", "web.config", "LICENSE.txt",
    "down52-baota.zip", "site.zip",
}
DEFAULT_EXCLUDE_DIRS = {"assets", ".git", ".svn", "__pycache__", "node_modules"}


def log(msg):
    print("[scan] " + msg, flush=True)


def load_descriptions(path):
    """描述文件格式：{"相对路径": "描述文字", ...}，例如 {"工具": "常用工具", "工具/OD.zip": "调试器"}"""
    if not path:
        return {}
    if not os.path.isfile(path):
        log("描述文件不存在，跳过：%s" % path)
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("描述文件必须是 JSON 对象，例如 {\"工具\": \"常用工具\"}")
    log("已加载 %d 条描述" % len(data))
    return data


def scan_dir(abs_dir, rel_dir, excludes, desc_map, stats):
    """递归扫描一个目录，返回 children 列表。rel_dir 为相对网站根目录的路径，用 / 分隔。"""
    children = []
    try:
        names = os.listdir(abs_dir)
    except OSError as e:
        log("无法读取目录，已跳过：%s (%s)" % (abs_dir, e))
        return children

    names = [n for n in names if not n.startswith(".")]
    # 目录在前，同类按名称排序（中文按 Unicode 码点，稳定可复现）
    names.sort(key=lambda n: (not os.path.isdir(os.path.join(abs_dir, n)), n))

    for name in names:
        if name in DEFAULT_EXCLUDE_NAMES or name in excludes:
            continue
        if name in DEFAULT_EXCLUDE_DIRS and os.path.isdir(os.path.join(abs_dir, name)):
            continue

        abs_path = os.path.join(abs_dir, name)
        rel_path = (rel_dir + "/" + name).lstrip("/")

        if rel_path in excludes or ("/" + rel_path) in excludes:
            continue
        if abs_path == os.path.abspath(excludes.get("__output__", "")):
            continue

        try:
            st = os.stat(abs_path)
        except OSError as e:
            log("无法读取，已跳过：%s (%s)" % (rel_path, e))
            continue

        if os.path.isdir(abs_path):
            stats["dirs"] += 1
            item = {"name": name, "children": scan_dir(abs_path, rel_path, excludes, desc_map, stats)}
        elif os.path.isfile(abs_path):
            stats["files"] += 1
            stats["bytes"] += st.st_size
            item = {"name": name, "size": st.st_size, "time": int(st.st_mtime)}
        else:
            continue  # 软链接等非常规类型

        desc = desc_map.get(rel_path) or desc_map.get("/" + rel_path)
        if desc:
            item["description"] = str(desc)
        children.append(item)

    return children


def build_tree(root, excludes, desc_path):
    desc_map = load_descriptions(desc_path)
    stats = {"dirs": 0, "files": 0, "bytes": 0}
    children = scan_dir(root, "", excludes, desc_map, stats)
    return {"name": "/", "children": children}, stats


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f PB" % n


def verify(path):
    """回读校验：能被 JSON 解析、根节点正确、结构合法"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get("name") != "/" or not isinstance(data.get("children"), list):
        raise ValueError("生成结果结构不合法")

    def walk(children):
        n_file = n_dir = 0
        for it in children:
            if "children" in it:
                n_dir += 1
                a, b = walk(it["children"])
                n_file += a
                n_dir += b
            else:
                if "size" not in it or "time" not in it:
                    raise ValueError("文件节点缺少 size/time：%s" % it.get("name"))
                n_file += 1
        return n_file, n_dir

    f, d = walk(data["children"])
    size = os.path.getsize(path)
    log("校验通过：%d 个文件、%d 个目录，list.json 体积 %s" % (f, d, human(size)))
    if size > 5 * 1024 * 1024:
        log("警告：list.json 超过 5 MB，文件太多会导致首屏变慢，建议拆分目录或减少文件数")
    return data


def main():
    ap = argparse.ArgumentParser(description="生成爱盘前端所需的 list.json")
    ap.add_argument("root_pos", nargs="?", help="网站根目录（位置参数，等价于 --root）")
    ap.add_argument("--root", help="网站根目录，即 index.html 所在目录")
    ap.add_argument("--output", help="输出文件路径，默认 <root>/list.json")
    ap.add_argument("--desc", help="描述文件 JSON 路径，默认 <root>/descriptions.json（不存在则忽略）")
    ap.add_argument("--exclude", action="append", default=[], help="额外排除的文件/目录名或相对路径，可重复")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    args = ap.parse_args()

    root = args.root or args.root_pos
    if not root:
        ap.error("请指定网站根目录，例如：python3 scan.py /www/wwwroot/你的站点")
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        log("错误：目录不存在 -> %s" % root)
        return 2

    output = os.path.abspath(args.output) if args.output else os.path.join(root, "list.json")
    desc_path = args.desc if args.desc else os.path.join(root, "descriptions.json")

    excludes = {"__output__": output}
    for e in args.exclude:
        excludes[e.strip("/")] = True

    log("扫描根目录：%s" % root)
    log("输出到：%s" % output)
    extra = [k for k in excludes if k != "__output__"]
    log("排除：站点自身文件、以 . 开头的项、assets/ 目录%s" % (
        "，以及 " + ", ".join(extra) if extra else ""))

    started = time.time()
    tree, stats = build_tree(root, excludes, desc_path)
    log("扫描完成：%d 个文件、%d 个目录、合计 %s，耗时 %.2fs" % (
        stats["files"], stats["dirs"], human(stats["bytes"]), time.time() - started))

    if args.dry_run:
        log("dry-run 模式，未写文件")
        print(json.dumps(tree, ensure_ascii=False, indent=2)[:2000])
        return 0

    payload = json.dumps(tree, ensure_ascii=False, separators=(",", ":"))
    tmp = output + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
    os.replace(tmp, output)  # 原子替换，避免访客读到半截 JSON
    try:
        os.chmod(output, 0o644)
    except OSError:
        pass

    data = verify(output)
    preview = [c["name"] for c in data["children"][:8]]
    log("顶层条目：%s%s" % (", ".join(preview) if preview else "（空）",
                          " ..." if len(data["children"]) > 8 else ""))
    log("完成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log("现在刷新网页即可看到最新文件列表（Ctrl+F5 强制刷新）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
