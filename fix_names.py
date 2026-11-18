#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_names.py - 修复「宝塔解压 ZIP 导致中文文件名乱码」

原理：ZIP 里的 UTF-8 文件名被解压工具按 CP866/CP437 之类的单字节代码页
解读，于是文件系统上存成了「чд║ф╛ЛцЦЗф╗╢」这种字符串。这是可逆的：
    乱码名.encode('cp866')  -> 原始 UTF-8 字节 -> .decode('utf-8') -> 正确中文

本脚本只做 rename，不删除、不覆盖任何文件，且默认 dry-run。

用法（在服务器上，与 scan.py 放同一目录）：
    # 1) 先看清单，不会改任何东西
    python3 /root/fix_names.py /www/wwwroot/你的站点目录

    # 2) 确认无误后真正改名
    python3 /root/fix_names.py /www/wwwroot/你的站点目录 --apply

    # 3) 万一改错了，用生成的清单原样回滚
    python3 /root/fix_names.py /www/wwwroot/你的站点目录 --rollback rename-plan-20261110-113500.json

    # 换编码（若 cp866 没识别出乱码，试 cp437 / gbk）
    python3 /root/fix_names.py /www/wwwroot/你的站点目录 --encoding cp437

改完记得重新生成列表： bash /root/scan.sh /www/wwwroot/你的站点目录
"""

import argparse
import json
import os
import sys
from datetime import datetime

# 站点自身文件都是纯 ASCII 名，不会被判定为乱码，无需特意排除


def log(m):
    print("[fix] " + m, flush=True)


def restore(name, enc):
    """把 mojibake 名字还原成正确中文；还原不了返回 None"""
    try:
        raw = name.encode(enc)
        fixed = raw.decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    if fixed == name:
        return None
    if any(ord(c) < 32 or ord(c) == 127 for c in fixed):
        return None
    # 还原结果至少要含一个非 ASCII 字符，否则多半是误判
    if all(ord(c) < 128 for c in fixed):
        return None
    return fixed


def collect(root, enc):
    """自底向上收集改名清单，保证父目录改名时子项已处理完"""
    plan = []
    for cur, dirs, files in os.walk(root, topdown=False):
        for name in dirs + files:
            fixed = restore(name, enc)
            if not fixed:
                continue
            old = os.path.join(cur, name)
            new = os.path.join(cur, fixed)
            rel_old = os.path.relpath(old, root)
            rel_new = os.path.relpath(new, root)
            conflict = "目标已存在，将跳过" if os.path.exists(new) else ""
            plan.append({"old": rel_old, "new": rel_new, "note": conflict})
    return plan


def save_plan(root, enc, plan, path):
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "root": os.path.abspath(root),
        "encoding": enc,
        "count": len(plan),
        "items": plan,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def apply_plan(root, plan, reverse=False):
    items = list(plan)
    # 正常改名：路径深的先做；回滚：路径浅的先做
    items.sort(key=lambda x: x["old"].count(os.sep), reverse=not reverse)
    done = skipped = failed = 0
    for it in items:
        old_rel, new_rel = (it["new"], it["old"]) if reverse else (it["old"], it["new"])
        old = os.path.join(root, old_rel)
        new = os.path.join(root, new_rel)
        if not os.path.exists(old):
            log("跳过（源不存在）：%s" % old_rel)
            skipped += 1
            continue
        if os.path.exists(new):
            log("跳过（目标已存在，拒绝覆盖）：%s" % new_rel)
            skipped += 1
            continue
        try:
            os.makedirs(os.path.dirname(new), exist_ok=True)
            os.rename(old, new)
            done += 1
        except OSError as e:
            log("失败：%s -> %s (%s)" % (old_rel, new_rel, e))
            failed += 1
    return done, skipped, failed


def main():
    ap = argparse.ArgumentParser(description="修复宝塔解压 ZIP 造成的中文文件名乱码")
    ap.add_argument("root", help="网站根目录（index.html 所在目录）")
    ap.add_argument("--encoding", default="cp866",
                    help="解压时被误用的代码页，默认 cp866；可选 cp437 / cp850 / gbk")
    ap.add_argument("--apply", action="store_true", help="真正执行改名（默认只预览）")
    ap.add_argument("--rollback", metavar="PLAN.json", help="按改名清单回滚")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        log("错误：目录不存在 -> %s" % root)
        return 2

    if args.rollback:
        with open(args.rollback, "r", encoding="utf-8") as f:
            payload = json.load(f)
        log("回滚清单：%s（%d 项，生成于 %s）" % (
            args.rollback, payload["count"], payload.get("generated_at", "?")))
        done, skipped, failed = apply_plan(root, payload["items"], reverse=True)
        log("回滚完成：成功 %d，跳过 %d，失败 %d" % (done, skipped, failed))
        return 0 if failed == 0 else 3

    plan = collect(root, args.encoding)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    plan_path = os.path.join(os.getcwd(), "rename-plan-%s.json" % stamp)

    log("网站根目录：%s" % root)
    log("还原编码：%s（乱码名.encode(编码) 再按 UTF-8 解码）" % args.encoding)
    log("发现可修复的乱码名：%d 个" % len(plan))
    if not plan:
        log("没有发现乱码文件名。若确实看到乱码，试试 --encoding cp437 或 --encoding gbk")
        return 0

    for i, it in enumerate(plan[:60], 1):
        log("  %2d. %s  ->  %s  %s" % (i, it["old"], it["new"], it["note"]))
    if len(plan) > 60:
        log("  ... 另有 %d 项，完整清单见 %s" % (len(plan) - 60, plan_path))

    save_plan(root, args.encoding, plan, plan_path)
    log("改名清单已保存：%s" % plan_path)

    if not args.apply:
        log("*** 预览模式，未改动任何文件 ***")
        log("确认上面清单无误后，加 --apply 才会真正改名；改错可用 --rollback 还原")
        return 0

    done, skipped, failed = apply_plan(root, plan)
    log("改名完成：成功 %d，跳过 %d，失败 %d" % (done, skipped, failed))
    if failed:
        log("有失败项，请勿删除改名清单，可用 --rollback 回滚")
        return 3
    log("接下来重新生成列表： bash /root/scan.sh %s" % root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
