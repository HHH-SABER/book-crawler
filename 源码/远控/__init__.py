# -*- coding: utf-8 -*-
"""远控服务包: 常驻机上的 Web 远控入口 (方案见 文档/手机远控方案设计.md)。

组件:
  配置.py   数据/远控配置.json (token 自动生成, 惰性单例)
  服务.py   FastAPI 层 (/api/v1 + 面板)
  面板.html 单页面板 (vanilla JS, 移动端优先)
启动: 项目根目录 `python -m 远控` (或双击 启动远控.bat)。
"""
