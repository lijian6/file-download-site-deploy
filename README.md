# 文件下载站 · 部署工具集

基于 [down_52pojie_cn](https://github.com/ganlvtech/down_52pojie_cn) 搭建的自建文件下载站，配套一套在 Linux（宝塔面板 / Nginx）上部署、维护、扩展的脚本与文档。

原项目是一个纯静态 Vue 单页应用，本身只负责「读一份 `list.json` 渲染文件表格」。本工具集解决的是把它落到真实服务器上会遇到的具体问题：列表数据怎么生成、中文文件名为什么乱码、怎么接对象存储、下载链接怎么控制时效、部署完怎么自查。

## 特性

- **双数据源**：本地目录扫描，或阿里云 OSS / 腾讯云 COS 对象存储，输出同一份 `list.json`
- **中文文件名乱码修复**：识别并还原宝塔解压 ZIP 造成的 CP866 乱码，只改名、不删除、可回滚
- **下载链接时效控制**：私有 Bucket + 302 现场签名，签名服务只监听 `127.0.0.1`，大文件流量不经过服务器
- **跨平台**：Python 脚本除对象存储 SDK 外只用标准库；Linux / Windows 启动器都会自动探测解释器，不要求 `python3` 在 PATH 里
- **部署自检**：一条命令检查目录结构、前端配置、列表合法性、HTTP 状态、乱码残留
- **完整文档**：一份跟做版部署 SOP，一份事后查阅的运维手册

## 快速开始

**首次部署**请照 [`从零部署-详细步骤.md`](./从零部署-详细步骤.md) 走，每一步都有验证命令和出错提示。

**日常维护**（放文件、改标题、排查故障、接对象存储）看 [`文件下载站-部署与维护手册.md`](./文件下载站-部署与维护手册.md)。

最短路径：

```bash
# 站点包解压到网站根目录后，生成文件列表
bash /root/scan.sh /www/wwwroot/your-site

# 部署完做一次自检
bash /root/check_deploy.sh /www/wwwroot/your-site 8080 your.ip
```

## 脚本一览

| 脚本 | 用途 | 用法 |
|---|---|---|
| `scan.py` / `scan.sh` / `scan.bat` | 扫描本地目录生成 `list.json`，自带校验 | `bash scan.sh <站点根目录>` |
| `scan_bucket.py` / `scan_bucket.sh` | 从对象存储（OSS / COS）列举对象生成 `list.json` | `bash scan_bucket.sh --provider oss --bucket ... --endpoint ...` |
| `oss_sync.sh` | 阿里云 OSS 一键同步，改顶部 4 行即可 | `bash oss_sync.sh` |
| `fix_names.py` / `fix_names.sh` | 修复 ZIP 解压导致的文件名乱码，默认预览 | `bash fix_names.sh <根目录> [--apply] [--rollback plan.json]` |
| `sign_server.py` | 私有 Bucket 的时效下载跳转服务（302 现场签名） | 由 systemd 托管，见 `sign-server.service` |
| `start-sign-server.sh` | 签名服务启动脚本，改顶部 4 行配置 | `bash start-sign-server.sh` |
| `build_site.py` | 从官方 dist 包重建定制站点包 | `python build_site.py --src ./dist/dist --out ./out` |
| `check_deploy.sh` | 部署自检，只读不改动 | `bash check_deploy.sh <根目录> [端口] [公网IP]` |

配置片段：

| 文件 | 用途 |
|---|---|
| `nginx-dl-location.conf` | Nginx 的 `/dl/` 反向代理片段（配合 `sign_server.py`） |
| `sign-server.service` | systemd 单元文件 |
| `web.config` | IIS 的 MIME 映射（仅 Windows/IIS 需要，Linux 不要用） |
| `objects-demo.json` | 离线对象清单示例，用于不连真实 Bucket 时验证逻辑 |

## 依赖

- **Python 3.6+**（脚本均为标准库实现，`scan.py` / `fix_names.py` / `sign_server.py` 无第三方依赖）
- 对象存储功能另需：阿里云 `oss2`，或腾讯云 `cos-python-sdk-v5`
- Web 服务器：Nginx（推荐）或 IIS

```bash
python3 -m pip install oss2          # 阿里云 OSS
python3 -m pip install cos-python-sdk-v5   # 腾讯云 COS
```

## 注意事项

- `build_site.py` 需要一个官方源码包：从 [Releases](https://github.com/ganlvtech/down_52pojie_cn/releases) 下载 `v2.1.3` 的 `dist.zip`，解压到 `./dist/dist`（本仓库不重复分发第三方构建产物）
- 文档中的服务器地址、域名均为占位示例（形如 `你的服务器IP`、`example.com`），请替换成自己的
- 密钥请通过环境变量或 `chmod 600` 的凭据文件传递，不要写进脚本
- 对象存储若使用「公共读」，链接永久有效且无法撤回；需要时效控制请走 `sign_server.py`

## 许可

本仓库的脚本与文档采用 MIT 许可。

前端代码来自 [ganlvtech/down_52pojie_cn](https://github.com/ganlvtech/down_52pojie_cn)，Copyright (c) 2018 Ganlv，同样以 MIT 许可发布。
