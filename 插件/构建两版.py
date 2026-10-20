# -*- coding: utf-8 -*-
"""构建 Chrome / Edge 两个版本的插件 (2026-10-20)。

两个版本**功能完全一致** (MV3 在 Chromium 系浏览器通用), 差异只在:
· manifest 的 name/description 标注浏览器名 (便于在扩展列表里区分);
· 安装说明的入口路径 (chrome://extensions vs edge://extensions)。

产物:
  插件/dist/chrome/    (可"加载已解压"的目录)
  插件/dist/edge/
  插件/dist/小说爬虫插件_chrome_v1.0.0.zip
  插件/dist/小说爬虫插件_edge_v1.0.0.zip

用法: python 插件/构建两版.py
"""
import json
import shutil
import zipfile
from pathlib import Path

本目录 = Path(__file__).resolve().parent
版本 = '1.0.0'
共享文件 = ('background.js', 'popup.html', 'popup.js')

_manifest模板 = {
    'manifest_version': 3,
    'version': 版本,
    'permissions': ['cookies', 'storage', 'tabs', 'alarms'],
    'host_permissions': ['http://127.0.0.1/*', 'http://localhost/*', '<all_urls>'],
    'background': {'service_worker': 'background.js'},
    'action': {'default_popup': 'popup.html', 'default_title': '小说爬虫 · 凭据中继'},
}

_说明模板 = """# 小说爬虫 · 凭据中继（{浏览器} {版本} 版）

把浏览器里的**真实登录 Cookie**（含 JS 算出/HttpOnly 的反爬 Cookie）推给本机
小说爬虫。只对你**明确加入白名单**的站点生效；爬虫须在本机运行。

## 安装（二选一）

**方式 A（推荐）：从软件内安装**
1. 打开小说爬虫 → 左侧「远控」页 → 点「浏览器插件」→ 选「安装{浏览器}版」
2. 程序会自动把插件复制到本地并打开扩展管理页
3. 在扩展管理页打开右上角「开发者模式」→ 点「加载已解压的扩展程序」→
   选择程序显示的目录（已自动复制好）

**方式 B：手动安装**
1. {扩展页}
2. 打开右上角「开发者模式」
3. 「加载已解压的扩展程序」→ 选中本目录

## 配置

1. 程序「远控」页 → 复制 token（端口默认 8760）
2. 点插件图标 → 填端口和 token → 「保存设置并测试连通」

## 使用

- 单个站点：打开目标小说站（确认能看到正文）→ 插件图标 → 「加入白名单并推送」
- 自动同步：白名单内的域每 5 分钟自动重新推送（浏览器 Cookie 变了会自动跟上）

## 边界

- Cookie 只接受白名单内的域（白名单在爬虫侧 `数据/插件白名单.json`）
- 仅本机 127.0.0.1 可推送，手机/局域网不能
- 插件不解析、不存书、不改爬虫状态——只搬 Cookie
- 需要读取任意站点 Cookie 的 `<all_urls>` 权限（开发者模式自用插件，可审查本目录全部源码）

> 仅供个人学习与研究使用，请遵守相关法律法规及目标站点服务条款。
"""


def 构建(浏览器: str, 扩展页: str) -> Path:
    目标 = 本目录 / 'dist' / 浏览器
    if 目标.exists():
        shutil.rmtree(目标)
    目标.mkdir(parents=True)

    manifest = dict(_manifest模板)
    manifest['name'] = f'小说爬虫 · 凭据中继（{浏览器.capitalize()} 版）'
    manifest['description'] = f'把当前网站的登录 Cookie 推送给本机小说爬虫（{浏览器.capitalize()} 版，仅限白名单站点）'
    (目标 / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    for f in 共享文件:
        shutil.copy2(本目录 / f, 目标 / f)

    (目标 / 'README.md').write_text(
        _说明模板.format(浏览器=浏览器.capitalize(), 版本=版本, 扩展页=扩展页),
        encoding='utf-8')
    return 目标


def 打包(目录: Path, 浏览器: str) -> Path:
    zip路径 = 本目录 / 'dist' / f'小说爬虫插件_{浏览器}_v{版本}.zip'
    with zipfile.ZipFile(zip路径, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(目录.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(目录))
    return zip路径


if __name__ == '__main__':
    for 浏览器, 扩展页 in (('chrome', 'chrome://extensions'), ('edge', 'edge://extensions')):
        目录 = 构建(浏览器, 扩展页)
        z = 打包(目录, 浏览器)
        print(f'[OK] {浏览器}: {目录}  →  {z.name} ({z.stat().st_size/1024:.0f}KB)')
    print('构建完成')
