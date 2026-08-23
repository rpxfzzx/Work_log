# -*- coding: utf-8 -*-
"""打包脚本：把工作日志打包为单文件 exe（带 Logo 图标）。

用法：python build_exe.py   （或双击 打包exe.bat）
产物：工作日志.exe（项目根目录，可拷贝到任意电脑双击运行，数据保存在 exe 旁 data/ 目录）
"""
import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
EXE_NAME = "工作日志"


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("未安装 PyInstaller，正在安装...", flush=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    print("Logo 文件检查...", flush=True)
    if not os.path.exists(os.path.join(BASE, "logo.ico")):
        print("缺少 logo.ico，先生成：python make_logo.py", flush=True)
        sys.exit(1)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", EXE_NAME,
        "--icon", os.path.join(BASE, "logo.ico"),
        "--add-data", "logo.ico" + os.pathsep + ".",
        "--add-data", "logo_64.png" + os.pathsep + ".",
        os.path.join(BASE, "worklog.py"),
    ]
    print("开始打包（首次约 1~3 分钟）...", flush=True)
    subprocess.check_call(cmd, cwd=BASE)

    src = os.path.join(BASE, "dist", EXE_NAME + ".exe")
    dst = os.path.join(BASE, EXE_NAME + ".exe")
    shutil.copy2(src, dst)
    print("打包完成：", dst, flush=True)
    print("说明：exe 为单文件，可整体拷贝到其他电脑；记录保存在 exe 旁的 data/worklog.json，", flush=True)
    print("周报导出到 exe 旁的 reports/ 目录。", flush=True)


if __name__ == "__main__":
    main()
