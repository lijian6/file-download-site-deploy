#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sign_server.py - 给下载链接加有效期（阿里云 OSS 私有 Bucket + 现场签名）

原理
----
    浏览器  GET /dl/files/工具/OD.rar
              │
              ▼
    本服务（127.0.0.1:5099，只跑在内网）
              │  用 AccessKey 现场生成签名 URL（默认 300 秒有效）
              ▼
    302 Location: https://bucket.oss-cn-hangzhou.aliyuncs.com/files/...?OSSAccessKeyId=..&Expires=..&Signature=..
              │
              ▼
    浏览器直接去 OSS 下载（大文件流量不经过本服务器）

好处
----
  * Bucket 可以设成「私有」，文件不再对全网公开
  * 每条链接默认 5 分钟后失效，被人转发出去也过期了
  * 大文件流量不经过你的服务器，只多一次几百字节的 302
  * 前端零改动：只把 index.html 的 baseUrl 改成 /dl

依赖
----
  只需要 oss2（pip install oss2），不依赖 Flask 等框架。

用法
----
  export OSS_ACCESS_KEY_ID=你的AK
  export OSS_ACCESS_KEY_SECRET=你的SK

  python3 sign_server.py \
      --bucket my-bucket \
      --endpoint https://oss-cn-hangzhou.aliyuncs.com \
      --prefix files/ \
      --expires 300

  自测：
    curl -I http://127.0.0.1:5099/dl/files/test.zip
    curl http://127.0.0.1:5099/healthz
"""

import argparse
import os
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BUCKET = None
PREFIX = ""
EXPIRES = 300
REFERER_HOSTS = []
LOG_FILE = ""


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = "sign-server/1.0"

    def _send(self, code, body=b"", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _client_ip(self):
        return self.headers.get("X-Real-IP") or self.client_address[0]

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path in ("/healthz", "/health"):
            return self._send(200, b"ok")

        if not path.startswith("/dl/"):
            return self._send(404, "not found\r\n".encode())

        key = path[len("/dl/"):].lstrip("/")
        if not key:
            return self._send(400, "missing object key\r\n".encode())

        # --- 安全检查 ---
        if ".." in key.split("/") or "\\" in key:
            log("BLOCK traversal ip=%s key=%s" % (self._client_ip(), key))
            return self._send(403, "forbidden\r\n".encode())
        if PREFIX and not key.startswith(PREFIX):
            log("BLOCK prefix ip=%s key=%s" % (self._client_ip(), key))
            return self._send(403, "forbidden\r\n".encode())
        if REFERER_HOSTS:
            ref = self.headers.get("Referer", "")
            host = urllib.parse.urlsplit(ref).netloc if ref else ""
            if host and host not in REFERER_HOSTS:
                log("BLOCK referer ip=%s host=%s" % (self._client_ip(), host))
                return self._send(403, "forbidden: referer\r\n".encode())

        # --- 现场签名 ---
        try:
            url = BUCKET.sign_url("GET", key, EXPIRES, slash_safe=True)
        except Exception as e:  # noqa: BLE001
            log("SIGN FAIL ip=%s key=%s err=%s" % (self._client_ip(), key, e))
            return self._send(500, "sign failed\r\n".encode())

        log("302 ip=%s key=%s ttl=%ds" % (self._client_ip(), key, EXPIRES))
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # 用自定义 log 替代默认的 stderr 噪音


def main():
    global BUCKET, PREFIX, EXPIRES, REFERER_HOSTS, LOG_FILE

    ap = argparse.ArgumentParser(description="OSS 私有 Bucket 的时效下载跳转服务")
    ap.add_argument("--bucket", required=True, help="Bucket 名称")
    ap.add_argument("--endpoint", required=True,
                    help="外网 Endpoint，不带 bucket 名，如 https://oss-cn-hangzhou.aliyuncs.com")
    ap.add_argument("--prefix", default="",
                    help="只允许该前缀下的对象，如 files/（建议填，防止越权下载整个 Bucket）")
    ap.add_argument("--expires", type=int, default=300,
                    help="签名有效期（秒），默认 300，官方上限 32400")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址，默认仅本机")
    ap.add_argument("--port", type=int, default=5099, help="监听端口，默认 5099")
    ap.add_argument("--allow-referer", action="append", default=[],
                    help="允许的 Referer 主机名，可重复；不填则不校验 Referer")
    ap.add_argument("--log", default="", help="日志文件路径，留空只输出到控制台")
    args = ap.parse_args()

    if not 1 <= args.expires <= 32400:
        ap.error("--expires 必须在 1 ~ 32400 秒之间（阿里云官方上限 9 小时）")

    try:
        import oss2
    except ImportError:
        print("[ERROR] 缺少 oss2，请先安装： %s -m pip install oss2" % sys.executable)
        return 2

    ak = os.environ.get("OSS_ACCESS_KEY_ID")
    sk = os.environ.get("OSS_ACCESS_KEY_SECRET")
    if not (ak and sk):
        print("[ERROR] 缺少密钥：请设置环境变量 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET")
        return 2

    PREFIX = args.prefix.lstrip("/")
    EXPIRES = args.expires
    REFERER_HOSTS = list(args.allow_referer)
    LOG_FILE = args.log

    BUCKET = oss2.Bucket(oss2.Auth(ak, sk), args.endpoint, args.bucket)

    log("starting on http://%s:%d  bucket=%s prefix=%r ttl=%ds referer=%s" % (
        args.host, args.port, args.bucket, PREFIX, EXPIRES,
        REFERER_HOSTS or "off"))

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
