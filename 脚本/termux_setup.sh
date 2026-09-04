#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  小说爬虫 Termux (安卓) 安装脚本 — CLI 子集
#  用法: bash termux_setup.sh   (在项目根目录执行)
#  安装后: python 源码/启动器.py <小说目录页URL>
# ============================================================
set -e

echo "== [1/3] 更新 Termux 软件源与基础包 =="
pkg update -y
pkg install -y python clang libxml2 libxslt binutils

echo "== [2/3] 安装 Python 依赖 (核心子集) =="
python -m pip install --upgrade pip
pip install -r requirements-termux.txt

echo "== [3/3] 完成 =="
echo ""
echo "  运行示例:"
echo "    cd 项目目录"
echo "    python 源码/启动器.py <小说目录页URL>        # 完整抓取"
echo "    python 源码/启动器.py <URL> --list          # 查看章节列表"
echo "    python 源码/启动器.py --update              # 一键更新书架"
echo ""
echo "  说明: Termux 版为 CLI 子集; 无 GUI / 浏览器渲染 / 验证码OCR,"
echo "  强反爬站点可能失败。可选 TLS 指纹: pkg install rust 后取消"
echo "  requirements-termux.txt 中 curl_cffi 注释再重装。"
