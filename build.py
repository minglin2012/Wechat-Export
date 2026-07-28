#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""构建发布包 —— PyInstaller 打包为独立目录
本地:  python build.py       (需先确保 electron/, runtime/node.exe 等已就位)
CI:    由 GitHub Actions 调用  (依赖已自动下载)
"""

import os, sys, shutil, subprocess, glob

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist", "WeChatExport")


def run(cmd, **kw):
    print(f"  > {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kw)


def check_file(path, desc):
    if os.path.exists(path):
        print(f"  [OK] {desc}")
    else:
        print(f"  [MISSING] {desc} -> {path}")
        return False
    return True


def main():
    print("=" * 56)
    print("  微信聊天记录导出工具 - 构建发布包")
    print("=" * 56)

    # 预检关键文件
    print("\n[0] 检查依赖...")
    ok = True
    ok &= check_file(os.path.join(HERE, "electron", "electron.exe"), "electron.exe")
    ok &= check_file(os.path.join(HERE, "runtime", "node.exe"), "runtime/node.exe")
    ok &= check_file(os.path.join(HERE, "runtime", "WCDB.dll"), "WCDB.dll")
    ok &= check_file(os.path.join(HERE, "scripts", "node_modules", "koffi"), "koffi")
    ok &= check_file(os.path.join(HERE, "scripts", "node_modules", "fzstd"), "fzstd")
    # ffmpeg 可选
    ffmpeg = os.path.join(HERE, "resources", "bin", "ffmpeg.exe")
    if not os.path.exists(ffmpeg):
        print("  [OPT] ffmpeg.exe (HEVC 图片解码备选，不影响基本导出)")
    if not ok:
        print("\n  [!] 缺少依赖，请先运行 CI 准备步骤或手动下载")
        print("  本地开发: 手动复制 electron/ runtime/node.exe 等文件")
        print("  CI 构建: .github/workflows/build.yml 自动下载")
        sys.exit(1)

    # 清理（保留 dist 由 PyInstaller 自动处理）
    for d in ["build"]:
        p = os.path.join(HERE, d)
        if os.path.exists(p):
            shutil.rmtree(p)
    # dist 只删目标目录
    if os.path.exists(DIST):
        shutil.rmtree(DIST)

    # PyInstaller
    print("\n[1] PyInstaller 打包...")
    sep = ";" if sys.platform == "win32" else ":"
    run([
        sys.executable, "-m", "PyInstaller",
        "--onedir", "--noconsole",
        "--name", "WeChatExport",
        "--distpath", os.path.join(HERE, "dist"),
        f"--add-data=electron{sep}electron",
        f"--add-data=scripts{sep}scripts",
        f"--add-data=runtime{sep}runtime",
        f"--add-data=exporters{sep}exporters",
        f"--add-data=resources{sep}resources",
        f"--add-data=export_config.json{sep}.",
        "--add-data", f"gui.py{sep}.",
        "--hidden-import", "openpyxl",
        "--hidden-import", "fpdf",
        "--hidden-import", "PIL",
        os.path.join(HERE, "export.py"),
    ], cwd=HERE)

    # 启动器（ASCII 编码，避免 CMD 中文乱码）
    print("\n[2] 创建启动器...")
    bat = ("@echo off\r\nchcp 65001 >nul\r\n"
           "title WeChat Export\r\n\r\n"
           "echo   WeChat Export Tool v3.0\r\n"
           "echo   =======================\r\n\r\n"
           "echo   Usage: enter args below\r\n"
           "echo   -----------------------\r\n"
           "echo   list  --data-dir=PATH          List all sessions\r\n"
           "echo   export --data-dir=PATH        Export all checked chats\r\n"
           "echo   key                           Get decryption key\r\n"
           "echo   --whitelist \"A,B\" --images    Options\r\n"
           "echo   gui    GUI tool\r\n"
           "echo   -----------------------\r\n\r\n"
           "set /p args=\"Enter args: \"\r\n"
           "WeChatExport.exe %args%\r\n"
           "pause\r\n")
    with open(os.path.join(DIST, "启动.bat"), "w", encoding="ascii") as f:
        f.write(bat)

    # GUI 快捷启动
    with open(os.path.join(DIST, "启动GUI.bat"), "w", encoding="ascii") as f:
        f.write("@echo off\r\nchcp 65001 >nul\r\nstart \"\" \"WeChatExport.exe\"\r\n")

    # 大小
    total = 0
    for dp, dn, fns in os.walk(DIST):
        for fn in fns:
            try: total += os.path.getsize(os.path.join(dp, fn))
            except Exception: pass

    print(f"\n  完成! 输出: {DIST}  ({total // 1024 // 1024} MB)")
    print(f"  {os.path.join(DIST, '启动.bat')}")


if __name__ == "__main__":
    main()
