#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""下载打包所需的大文件（CI 中 GitHub Actions 自动执行此逻辑）
本地使用:  python setup_deps.py
"""

import os, sys, shutil, subprocess, urllib.request, zipfile, glob

HERE = os.path.dirname(os.path.abspath(__file__))


def download(url, dest):
    """下载文件，带进度条"""
    print(f"  下载: {url}")
    print(f"  目标: {dest}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    def reporthook(blocknum, blocksize, totalsize):
        pct = min(100, int(blocknum * blocksize * 100 / totalsize)) if totalsize > 0 else 0
        mb = blocknum * blocksize / (1024 * 1024)
        sys.stdout.write(f"\r  {pct}% ({mb:.0f} MB)")
        sys.stdout.flush()

    urllib.request.urlretrieve(url, dest, reporthook)
    print(f"\n  完成 ({os.path.getsize(dest) / 1024 / 1024:.0f} MB)")


def run(cmd, **kw):
    print(f"  > {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kw)


def setup_electron():
    """通过 npm 安装 electron，提取 electron.exe + 资源文件"""
    print("\n[1/3] Electron 运行时")
    dest = os.path.join(HERE, "electron")
    if os.path.exists(os.path.join(dest, "electron.exe")):
        print("  已存在，跳过")
        return

    scripts = os.path.join(HERE, "scripts")
    run(["npm", "install"], cwd=scripts, shell=True)

    # 复制整个 electron dist 目录
    src = os.path.join(scripts, "node_modules", "electron", "dist")
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest)

    sz = sum(os.path.getsize(os.path.join(dp, fn))
             for dp, _, fns in os.walk(dest) for fn in fns)
    print(f"  Electron 就绪 ({sz / 1024 / 1024:.0f} MB)")


def setup_node():
    """下载 Node.js 运行时（用于密钥捕获）"""
    print("\n[2/3] Node.js 运行时")
    dest = os.path.join(HERE, "runtime", "node.exe")
    if os.path.exists(dest):
        print("  已存在，跳过")
        return
    download("https://nodejs.org/dist/v20.18.0/win-x64/node.exe", dest)


def setup_ffmpeg():
    """下载 ffmpeg（HEVC 图片解码，可选）"""
    print("\n[3/3] ffmpeg（可选）")
    dest = os.path.join(HERE, "resources", "bin", "ffmpeg.exe")
    if os.path.exists(dest):
        print("  已存在，跳过")
        return

    zip_path = os.path.join(HERE, "resources", "ffmpeg_temp.zip")
    download("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", zip_path)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        print("  解压中...")
        shutil.unpack_archive(zip_path, tmp)
        # 找 ffmpeg.exe（在子目录的 bin/ 下）
        for root, _, files in os.walk(tmp):
            if "ffmpeg.exe" in files:
                shutil.copy2(os.path.join(root, "ffmpeg.exe"), dest)
                break
    os.remove(zip_path)

    if os.path.exists(dest):
        print(f"  ffmpeg 就绪 ({os.path.getsize(dest) / 1024 / 1024:.0f} MB)")
    else:
        print("  [!] ffmpeg 下载失败（不影响基本导出功能）")


def main():
    print("=" * 56)
    print("  下载构建依赖")
    print("=" * 56)

    # npm install（koffi, fzstd）
    scripts = os.path.join(HERE, "scripts")
    if not os.path.exists(os.path.join(scripts, "node_modules", "koffi")):
        print("\n[0] npm install (koffi, fzstd)...")
        run(["npm", "install"], cwd=scripts, shell=True)

    setup_electron()
    setup_node()
    setup_ffmpeg()

    print(f"\n{'=' * 56}")
    print("  依赖就绪！运行: python build.py")
    print("=" * 56)


if __name__ == "__main__":
    main()
