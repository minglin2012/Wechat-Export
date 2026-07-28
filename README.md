# 微信聊天记录导出工具 v3.0

一键导出微信 4.x 全部聊天记录。支持 HTML / CSV / Excel / PDF / TXT / JSON。

## 快速开始

```bash
cd d:\programming\wechat_export

# 1. 安装 Python 依赖（仅首次）
pip install openpyxl fpdf2

# 2. 获取密钥（需要关闭→重启微信）
python export.py key

# 3. 预览所有会话
python export.py list --data-dir=D:\Users\Lenovo\Documents\xwechat_files

# 4. 编辑 export_config.json 配置过滤规则

# 5. 导出全部
python export.py export --data-dir=D:\Users\Lenovo\Documents\xwechat_files

# 6. 或只导出特定联系人
python export.py export --whitelist "张三,李四" --images
```

## 子命令

| 命令 | 说明 | 示例 |
|---|---|---|
| `export` | 导出聊天记录（默认） | `python export.py export -f xlsx --images` |
| `list` | 列出所有会话预览过滤 | `python export.py list` |
| `key` | 获取/查看数据库密钥 | `python export.py key --force` |

## export 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `-f, --format` | html | html / csv / xlsx / pdf / txt / json |
| `-o, --output` | 桌面/wx_export | 输出目录 |
| `-l, --limit` | 0（全部） | 每个会话最多导出条数 |
| `--images` | off | 导出图片消息（需要 image_key.json） |
| `--whitelist` | | 逗号分隔，只导出这些 wxid/显示名 |
| `--blacklist` | | 逗号分隔，跳过这些 wxid/显示名 |
| `--skip-groups` | off | 跳过群聊 |
| `--no-skip-official` | off | 不跳过公众号 |
| `--config` | export_config.json | 过滤配置文件路径 |
| `--data-dir` | 自动检测 | 微信数据目录路径 |
| `--rekey` | off | 强制重新获取密钥 |

## 过滤配置 (export_config.json)

```json
{
  "blacklist": {
    "wxids": [],
    "names": ["微信团队"],
    "keywords": ["通知", "广告"],
    "skip_groups": true,
    "skip_official": true
  },
  "whitelist": {
    "wxids": [],
    "names": [],
    "keywords": ["张三"]
  }
}
```

- 白名单非空时，**只导出**白名单中的会话
- `keywords`：显示名包含该词即匹配（不区分大小写）
- `skip_groups`：跳过 wxid 以 `@chatroom` 结尾的群聊
- `skip_official`：跳过公众号和服务号

## 构建发布包

### 本地构建

```bash
# 1. 安装构建依赖
pip install pyinstaller openpyxl fpdf2

# 2. 下载大文件（首次约 5-10 分钟，需联网）
python setup_deps.py

# 3. 打包
python build.py
```

`setup_deps.py` 自动下载：
- Electron 运行时（~260 MB，npm install electron）
- Node.js 运行时（~30 MB，官方下载）
- ffmpeg（~30 MB，可选，失败不影响基本功能）

### GitHub Actions 自动构建

推送 tag 或手动触发 Workflow 即可自动构建 + 发布 Release。

```bash
git tag v1.0.0
git push --tags
```

输出在 `dist/WeChatExport/`，双击 `启动.bat` 或命令行：

```bash
cd dist\WeChatExport
WeChatExport.exe export --data-dir=...
```

---

## 架构说明

程序需要跨越三个技术层次：

### 1. Windows 原生层（C/C++ DLL）— 必须
```
wx_key.dll  → 注入微信进程，Hook 内存中的 SetDBKey 调用，捕获数据库密钥
WCDB.dll    → 微信自带的加密数据库引擎（闭源，基于 SQLite 修改）
wcdb_api.dll→ 封装了读 WCDB 数据库的 C 函数接口
SDL2.dll    → WCDB 依赖库
msvcp140.dll→ Visual C++ 运行时（WCDB 编译依赖）
```

这些 DLL 是**微信自己的**或配套的，Python 无法直接调用 C/C++ DLL。

### 2. Node.js / Electron 桥接层 — 必须
```
get_key.js       → 用管理员权限加载 wx_key.dll，注入微信进程捕获密钥
wcdb_server.js   → 加载 WCDB.dll，启动本地 HTTP 服务供 Python 查询
koffi            → FFI 库，让 JavaScript 能调用 C/C++ 函数
fzstd            → 解压微信的 ZSTD 压缩消息格式
Electron 运行时   → WCDB 数据库引擎只能在 Electron 环境正常初始化
                   （裸 Node.js v24 返回 INIT_FAIL 错误码 -1006）
```

**为什么用 Node.js 而不是 Python ctypes？** Python ctypes 理论上也能调 DLL，但 WCDB 的 `wcdb_init()` 在 Python 进程里同样返回 -1006。WCDB 库内部检查了宿主进程环境，只接受 Electron 的 Chromium 沙箱环境。

### 3. Python 编排层 — 用户界面
```
export.py               → 命令行入口、流程控制
image_decoder.py        → AES-128-ECB + XOR 解密微信加密图片（.dat 文件）
decrypt_image.js        → Rust 原生模块备选图片解密方案
ffmpeg.exe              → HEVC 格式微信图片解码备选
html/csv/excel/pdf_exporter.py → 格式化输出
```

### 数据流
```
微信进程 (WeChat.exe)
  ↑ DLL 注入
wx_key.dll → get_key.js → key.txt（64位十六进制密钥）

xwechat_files/session.db（加密数据库）
  ↓ WCDB.dll + 密钥
wcdb_server.js（HTTP 服务 :随机端口）
  ↓ HTTP GET /sessions, /messages/{wxid}, /resolve_image/{md5}
export.py（Python）
  ↓ 
HTML/CSV/Excel/PDF/TXT 文件
```

### 依赖最小化

| 依赖 | 大小 | 可否移除？ |
|---|---|---|
| electron.exe | 212 MB | ❌ WCDB 必须 Electron 初始化 |
| WCDB.dll + SDK | 12 MB | ❌ 没有它读不了微信数据库 |
| wx_key.dll | 0.2 MB | ❌ 没有它拿不到密钥 |
| ffmpeg.exe | 83 MB | ⚠️ 仅导出 HEVC 图片时需要 |
| weflow-image.node | 0.3 MB | ⚠️ 仅图片解密备选方案 |
| koffi + fzstd | ~5 MB | ❌ JS 调用 DLL + ZSTD 解压 |
| node.exe | 91 MB | ❌ 运行 get_key.js 需要 |

总计 ~400 MB，其中 Electron（212 MB）和 node.exe（91 MB）占大头。这两个是 Chromium/V8 运行时，无法缩小。

## 目录结构

```
wechat_export/
├── export.py              ← 主程序（唯一入口）
├── export_config.json     ← 过滤配置
├── build.py               ← 打包脚本
├── electron/              ← Electron 运行时（WCDB 需要）
├── scripts/               ← JS 脚本 + npm 依赖
│   ├── get_key.js         ← 密钥捕获
│   ├── wcdb_server.js     ← WCDB HTTP 服务
│   ├── decrypt_image.js   ← 图片解密备选
│   ├── package.json
│   └── node_modules/
├── runtime/               ← 原生 DLL
│   ├── WCDB.dll / wcdb_api.dll / SDL2.dll
│   ├── wx_key.dll
│   ├── node.exe           ← 密钥捕获需要
│   └── msvcp140.dll / vcruntime140.dll
├── exporters/             ← Python 导出器
│   ├── html/csv/excel/pdf_exporter.py
│   ├── image_decoder.py
│   ├── media_resolver.py
│   └── packed_info_parser.py
└── resources/
    ├── bin/ffmpeg.exe
    └── native/weflow-image-native-win32-x64.node
```
