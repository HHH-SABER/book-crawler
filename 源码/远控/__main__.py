# -*- coding: utf-8 -*-
"""远控服务入口: python -m 远控

依赖 源码 在 sys.path (启动远控.bat 已设 PYTHONPATH, 或在 源码/ 目录下运行)。
"""
import os
import sys

# 保证能 import 源码下的兄弟模块 (日志/书架/gui_components/爬虫...)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn

from 远控.配置 import 取配置
from 远控.服务 import app


def main():
    cfg = 取配置()
    host, port = cfg.get("绑定", "127.0.0.1"), int(cfg.get("端口", 8760))
    print(f"[远控] 服务地址 : http://{host}:{port}/")
    print(f"[远控] 访问 token: {cfg.get('token', '')}")
    print("[远控] 面板打开后输入该 token 即可使用; 外网访问建议 tailscale serve 反代")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
