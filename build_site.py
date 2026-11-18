#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_site.py - 把 down_52pojie_cn 官方 v2.1.3 dist.zip 构建成「宝塔面板可直接上传」的站点包

做的改造：
  1. .fancyindex/ (隐藏目录) -> assets/，并改写所有资源引用
     宝塔的 Nginx 配置常拦截以 . 开头的路径，隐藏目录会导致 CSS/JS 404、页面白屏
  2. history + jsonp -> hash + json
     免伪静态配置、免 PHP、免 JSONP，宝塔建完站上传即用
  3. baseUrl = window.location.origin
     下载链接自动指向当前 IP:端口 / 域名，换域名不用改代码
  4. 移除 52pojie 品牌、导航外链、备案号、百度统计、论坛专用提示
  5. 附带示例目录 + 用 scan.py 生成真实 list.json，首次打开就有内容可点
  6. 自带校验：资源存在、无残留外链、list.json 可解析

用法：
    python3 build_site.py --src ./dist/dist --out ./out --title "我的文件库"
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#4d545d">
<meta name="description" content="__TITLE__ - 在线文件浏览与下载">
<title>__TITLE__</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="/assets/css/__CSS_FILE__">
</head>
<body>
<nav class="navbar navbar-expand-md navbar-dark no-select">
  <div class="container">
    <a class="navbar-brand" href="#/">__TITLE__</a>
    <button class="navbar-toggler" type="button" data-toggle="collapse" data-target="#navbarSupportedContent"
            aria-controls="navbarSupportedContent" aria-expanded="false" aria-label="切换导航">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="navbarSupportedContent">
      <ul class="navbar-nav mr-auto">
        <li class="nav-item"><a class="nav-link" href="#/">首页</a></li>
      </ul>
    </div>
  </div>
</nav>
<noscript>
  <div class="container">
    <div class="alert alert-danger"><strong>本站需要启用 JavaScript 才能显示文件列表。</strong></div>
  </div>
</noscript>
<div class="container">
  <div id="app"></div>
  <div id="main"><h1 class="current-path">__TITLE__</h1></div>
</div>
<div class="footer"><p class="copyright"><span>__TITLE__</span></p></div>
<script>
(function () {
  var ths = document.querySelectorAll('th');
  for (var i = 0; i < ths.length; ++i) { ths[i].style.width = ''; }
  window.addEventListener('DOMContentLoaded', function () {
    window.down52PojieCn = new Down52PojieCn({
      vueElement: '#app',
      routerMode: 'hash',
      baseUrl: __BASE_URL__,
      requestType: 'json',
      jsonUrl: '/list.json',
      cacheTime: 0
    });
  });
})();
</script>
<script src="/assets/js/__JS_FILE__"></script>
</body>
</html>
"""

EXAMPLE_README = """把这个目录删掉，换成你自己的文件和文件夹即可。

放好文件后，在服务器上重新生成列表：
    python3 /root/scan.py /www/wwwroot/你的站点目录

然后按 Ctrl+F5 强制刷新网页。

说明：
- 列表数据来自网站根目录下的 list.json，新增/删除文件后必须重新运行上面的命令
- 想给文件夹或文件加说明，在网站根目录建 descriptions.json，格式：
    {"工具": "常用工具合集", "工具/OD.zip": "动态调试器"}
- 站点自身的 index.html / assets / list.json 不会出现在下载列表里
- 项目前端来自 https://github.com/ganlvtech/down_52pojie_cn (MIT License)
"""

# 注意：站点包内所有"文件名/目录名"必须是纯 ASCII。
# 宝塔面板解压 ZIP 时可能按 CP866/CP437 解读 UTF-8 文件名，中文名会变成不可逆的乱码。
# 中文只出现在文件内容（descriptions.json、README.txt）里，那是 UTF-8 文本，不受影响。
DESC_EXAMPLE = {
    "sample": "示例目录，放好你自己的文件后可以删掉它",
    "sample/README.txt": "说明文档，可直接删除"
}


def log(m):
    print("[build] " + m, flush=True)


def find_assets(src):
    css_dir = os.path.join(src, ".fancyindex", "css")
    js_dir = os.path.join(src, ".fancyindex", "js")
    css = sorted(f for f in os.listdir(css_dir) if f.endswith(".css"))
    js = sorted(f for f in os.listdir(js_dir) if f.endswith(".js"))
    if not css or not js:
        raise RuntimeError("在 %s 下找不到 app.*.css / app.*.js，请确认 --src 指向解压后的 dist/ 目录" % src)
    return (os.path.join(css_dir, css[0]), css[0], os.path.join(js_dir, js[0]), js[0])


def main():
    ap = argparse.ArgumentParser(description="构建宝塔可用的爱盘站点包")
    ap.add_argument("--src", default="./dist/dist", help="官方 dist.zip 解压后的 dist/ 目录")
    ap.add_argument("--out", default="./out", help="输出目录")
    ap.add_argument("--title", default="我的文件库", help="站点标题（同时用于导航栏和页脚）")
    ap.add_argument("--base-url", default="",
                    help="文件下载地址前缀。留空=自动用当前站点域名；接对象存储时填 COS/OSS 公网域名，"
                         "例如 https://xxx.cos.ap-guangzhou.myqcloud.com")
    ap.add_argument("--zip", default="down52-baota.zip", help="最终 zip 文件名")
    ap.add_argument("--with-iis", action="store_true",
                    help="额外附带 web.config（仅 IIS / 宝塔 Windows 版需要；Linux+Nginx 不要加）")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.abspath(os.path.join(here, args.src)) if not os.path.isabs(args.src) else args.src
    out = os.path.abspath(os.path.join(here, args.out)) if not os.path.isabs(args.out) else args.out
    site = os.path.join(out, "site")
    tools = os.path.join(out, "tools")

    if not os.path.isfile(os.path.join(src, "index.html")):
        log("错误：找不到 %s" % os.path.join(src, "index.html"))
        return 2

    # 干净重建
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(site, "assets", "css"))
    os.makedirs(os.path.join(site, "assets", "js"))
    os.makedirs(tools)

    css_src, css_name, js_src, js_name = find_assets(src)
    shutil.copy2(css_src, os.path.join(site, "assets", "css", css_name))
    shutil.copy2(js_src, os.path.join(site, "assets", "js", js_name))
    log("资源：%s / %s" % (css_name, js_name))

    # 仅当显式 --with-iis 时才附带：IIS 默认无 .json MIME 会导致 /list.json 404.3
    # Linux + Nginx 默认已有 application/json，无需此文件
    web_cfg = os.path.join(here, "web.config")
    if args.with_iis and os.path.isfile(web_cfg):
        shutil.copy2(web_cfg, os.path.join(site, "web.config"))
        log("已附带 web.config（IIS 的 .json MIME 映射）")
    else:
        log("Linux/Nginx 模式：不含 web.config")

    if args.base_url:
        u = args.base_url.rstrip("/")
        if not u.startswith(("http://", "https://")) or any(c in u for c in "'\"\\\n\r"):
            ap.error("--base-url 必须是 http(s):// 开头的合法 URL，且不含引号")
        base_expr = "'" + u + "'"
        log("baseUrl 已固定为对象存储域名：%s" % u)
    else:
        base_expr = "window.location.origin"
        log("baseUrl 使用当前站点域名（自动适配）")

    html = (HTML_TEMPLATE
            .replace("__TITLE__", args.title)
            .replace("__BASE_URL__", base_expr)
            .replace("__CSS_FILE__", css_name)
            .replace("__JS_FILE__", js_name))
    with open(os.path.join(site, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    # 示例内容，保证首次打开就有东西可点
    demo = os.path.join(site, "sample")
    os.makedirs(demo)
    with open(os.path.join(demo, "README.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(EXAMPLE_README)
    with open(os.path.join(site, "descriptions.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(DESC_EXAMPLE, f, ensure_ascii=False, indent=2)

    # 工具脚本
    shutil.copy2(os.path.join(here, "scan.py"), os.path.join(tools, "scan.py"))  # 仅本地保留一份，不进站点包
    with open(os.path.join(site, "LICENSE.txt"), "w", encoding="utf-8") as f:
        f.write("前端代码来自 https://github.com/ganlvtech/down_52pojie_cn，MIT License。\n"
                "Copyright (c) 2018 Ganlv\n")

    # 用同一个 scan.py 生成真实 list.json（顺便验证生成器可用）
    log("调用 scan.py 生成 list.json ...")
    r = subprocess.run([sys.executable, os.path.join(tools, "scan.py"), site],
                       capture_output=True, text=True, encoding="utf-8")
    print(r.stdout.strip())
    if r.returncode != 0:
        log("scan.py 失败：\n" + (r.stderr or ""))
        return 3

    # ---------- 校验 ----------
    log("开始校验 ...")
    errors = []

    # 关键：ZIP 内禁止任何非 ASCII 文件名，否则宝塔解压必乱码
    for root, dirs, files in os.walk(site):
        for n in dirs + files:
            if any(ord(c) > 127 for c in n):
                errors.append("站点包内出现非 ASCII 文件名（宝塔解压 ZIP 会乱码）：" + n)
    if not errors:
        log("文件名检查通过：站点包内全部为纯 ASCII 文件名")
    required = [os.path.join("assets", "css", css_name),
                os.path.join("assets", "js", js_name),
                "index.html", "list.json"]
    if args.with_iis:
        required.append("web.config")
    for rel in required:
        if not os.path.isfile(os.path.join(site, rel)):
            errors.append("缺少文件：" + rel)

    for bad in ["down.52pojie.cn", "52pojie.cn", "hm.baidu.com", ".fancyindex", "fancyindex",
                "开源项目", "github.com/ganlvtech"]:
        if bad in html:
            errors.append("index.html 仍残留不该出现的内容：" + bad)

    for fname in re.findall(r'(?:href|src)="(/assets/[^"]+)"', html):
        if not os.path.isfile(os.path.join(site, fname.lstrip("/"))):
            errors.append("index.html 引用的资源不存在：" + fname)

    with open(os.path.join(site, "index.html"), encoding="utf-8") as f:
        final_html = f.read()
    for needed in ["routerMode: 'hash'", "requestType: 'json'", "jsonUrl: '/list.json'",
                   "baseUrl: "]:
        if needed not in final_html:
            errors.append("前端配置缺失：" + needed)
    if "__BASE_URL__" in final_html:
        errors.append("baseUrl 占位符未被替换")

    with open(os.path.join(site, "list.json"), encoding="utf-8") as f:
        tree = json.load(f)
    if tree.get("name") != "/" or not tree.get("children"):
        errors.append("list.json 内容为空或结构错误")

    if errors:
        for e in errors:
            log("校验失败 -> " + e)
        return 4
    log("校验通过：前端配置正确、无官方外链残留、资源齐全、list.json 有 %d 个顶层条目" % len(tree["children"]))

    # ---------- 打包 ----------
    # zip 根 = 网站根目录：宝塔里上传后直接解压即可，不需要再挪动一层目录
    # scan.py 故意不进包：放在网站根目录会被浏览器直接下载到源码
    zip_path = os.path.join(here, args.zip)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, dirs, files in os.walk(site):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                full = os.path.join(root, name)
                z.write(full, os.path.relpath(full, site).replace(os.sep, "/"))
    log("打包完成：%s (%.1f KB)" % (zip_path, os.path.getsize(zip_path) / 1024.0))
    log("zip 解压后即为网站根目录内容：")
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            log("  " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
