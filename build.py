#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build release package via PyInstaller"""

import os, sys, shutil, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist", "WeChatExport")


def run(cmd, **kw):
    print(f"  > {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kw)


def check_file(path, desc):
    if os.path.exists(path):
        print(f"  [OK] {desc}")
        return True
    else:
        print(f"  [MISSING] {desc} -> {path}")
        return False


def main():
    print("=" * 56)
    print("  WeChat Export Tool - Build")
    print("=" * 56)

    print("\n[0] Check dependencies...")
    ok = True
    ok &= check_file(os.path.join(HERE, "electron", "electron.exe"), "electron.exe")
    ok &= check_file(os.path.join(HERE, "runtime", "node.exe"), "runtime/node.exe")
    ok &= check_file(os.path.join(HERE, "runtime", "WCDB.dll"), "WCDB.dll")
    ok &= check_file(os.path.join(HERE, "scripts", "node_modules", "koffi"), "koffi")
    ok &= check_file(os.path.join(HERE, "scripts", "node_modules", "fzstd"), "fzstd")
    ffmpeg = os.path.join(HERE, "resources", "bin", "ffmpeg.exe")
    if not os.path.exists(ffmpeg):
        print("  [OPT] ffmpeg.exe (not required for basic export)")
    if not ok:
        print("\n  [!] Missing dependencies. Run setup_deps.py first.")
        sys.exit(1)

    for d in ["build"]:
        p = os.path.join(HERE, d)
        if os.path.exists(p):
            shutil.rmtree(p)
    if os.path.exists(DIST):
        shutil.rmtree(DIST)

    print("\n[1] PyInstaller...")
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

    print("\n[2] Create launchers...")
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

    with open(os.path.join(DIST, "启动GUI.bat"), "w", encoding="ascii") as f:
        f.write("@echo off\r\nchcp 65001 >nul\r\nstart \"\" \"WeChatExport.exe\"\r\n")

    total = 0
    for dp, dn, fns in os.walk(DIST):
        for fn in fns:
            try: total += os.path.getsize(os.path.join(dp, fn))
            except Exception: pass

    print(f"\n  Done! Output: {DIST}  ({total // 1024 // 1024} MB)")
    print(f"  Launcher: {os.path.join(DIST, 'launch.bat')}")


if __name__ == "__main__":
    main()
