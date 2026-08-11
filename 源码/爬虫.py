# -*- coding: utf-8 -*-
"""
小说爬虫主程序
==============

功能概览：
    1. 目录页解析：根据域名或通用规则提取章节标题与 URL
    2. 章节内容抓取：支持四种正文模式（见下方），自动分页合并、去重
    3. 反爬机制处理：JS cookie 校验、PC UA 重试、AJAX 签名模拟、Selenium 兜底
    4. 通用内容清洗：零宽字符清理、通用广告行过滤、段落指纹去重、重复分页检测
    5. 断点续传 / 进度条显示 / 章节数字排序

正文模式识别顺序（通用分发层优先）：
    a. qsbs_bb      — <script>qsbs.bb('BASE64')</script> 加密块（云趣阁/zhiruo/biquwx/ahxsw 等）
    b. ajax_two_step — /api/read_sign.php 两步 AJAX 动态加载（11bzw.org 等）
    c. html_selector — 遍历 14 种常见 CSS 选择器取最长正文（yqyp.net 等）
    d. selenium      — 以上均失败时，用浏览器渲染兜底

默认输出目录：项目根目录/抓取结果/（基于脚本路径计算，避免从不同 cwd 启动产生重复）

使用方式：
    交互式：  python 爬虫.py
    命令行：  python 爬虫.py <目录页URL> [--list|--test] [--no-sort] [--no-resume]
                        [--no-progress] [--output-dir 自定义目录]
    双击：    启动爬虫.bat（推荐，自动找虚拟环境 + 强制输出目录）
"""

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from bs4 import BeautifulSoup
import time
from fake_useragent import UserAgent
import re
import json
import base64
import os
import sys
import tempfile
from pathlib import Path

# 导入站点适配模式库 (可复用的网站适配配置)
try:
    from sites_config import (
        SITE_PATTERNS, PATTERN_QSBS_BB, PATTERN_AJAX_TWO_STEP,
        PATTERN_HTML_SELECTOR, PATTERN_SELENIUM,
        get_site_pattern, build_paged_url, auto_detect_pattern,
        extract_content as extract_content_by_pattern,
        validate_public_url,
    )
    SITES_CONFIG_AVAILABLE = True
except ImportError:
    SITES_CONFIG_AVAILABLE = False

    def validate_public_url(url):
        """本地兜底 URL 校验 (sites_config 未导入时使用)"""
        import ipaddress
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            raise ValueError(f"仅允许 http/https 协议: {url}")
        host = (parsed.hostname or '').lower()
        if not host or host == 'localhost' or host.endswith('.local') or host.endswith('.internal'):
            raise ValueError(f"禁止访问内网主机: {url}")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return
        if ip.is_private or ip.is_loopback or ip.is_link_local or \
                ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError(f"禁止访问非公网地址: {url}")

# 尝试导入Selenium
selenium_available = False
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    selenium_available = True
    print("Selenium 导入成功，可以使用浏览器模拟")
except ImportError:
    print("Selenium 未安装，将使用传统方法")


def _is_waf_js_challenge(response) -> bool:
    """判断响应是否为 WAF JS 动态令牌挑战页 (banlvzw 等)

    特征: 401 + Loading 转圈动画 + /@wafjs? 混淆脚本
    """
    try:
        if response.status_code not in (401, 403, 429):
            return False
        text = response.text or ''
        return ('@wafjs' in text) or ('Loading...' in text and '__WV' in text) \
            or ('Loading...' in text and 'wafjs' in text)
    except Exception:
        return False


def _chapter_sort_key(chap):
    """统一的章节排序键：按章节号 → 楔子 → URL数字 → 番外排序"""
    title = chap.get('title', '')
    url = chap.get('url', '')
    if '楔子' in title:
        return 0
    m = re.search(r'第(\d+)章', title)
    if m:
        return int(m.group(1))
    m2 = re.search(r'/(\d+)\.html', url)
    if m2:
        return int(m2.group(1))
    if '番外' in title:
        return 99999
    return 9999


# 通用广告行/无意义字符特征 (基于内容特征, 适用于所有小说网站)
# 这些正则模式识别广告/导航/推荐列表的通用结构特征, 不依赖具体书名或站点名

# 结构特征 (对所有行生效, 基于行的整体结构判断)
_AD_LINE_STRUCT_PATTERNS = [
    # 相邻推荐列表: 多个书名以连续空格(3+)分隔, 无中文标点
    # 例: "书名1   书名2   书名3   书名4"
    re.compile(r'^[^\s].*\s{3,}[^\s].*\s{3,}[^\s]'),
    # 纯数字/字母组合 (如章节编号残留、验证码、页码)
    re.compile(r'^[\d\s]{5,}$'),
    # 站点域名行: www.xxx.com 或 m.xxx.com 格式
    re.compile(r'^(www\.|m\.|https?://)[\w\.\-]+'),
    # 纯符号分隔行 (如 "----------" 或 "=========")
    re.compile(r'^[\-\=\*\_]{5,}$'),
]

# 标签特征 (仅对短行 <40 字生效, 避免误伤正文段落)
# 这些模式匹配小说搜索标签、站点宣传语等短行广告
_AD_LINE_TAG_PATTERNS = [
    # "XX小说网" / "XX阅读网" 等站点名后缀 (通用, 不针对具体站点)
    re.compile(r'.{2,8}小说网$'),
    re.compile(r'.{2,8}阅读网$'),
    re.compile(r'.{2,8}文学网$'),
    # "XX最新章节" / "XXtxt下载" 等小说搜索标签
    re.compile(r'.{2,15}最新章节$'),
    re.compile(r'.{2,15}txt下载$'),
    re.compile(r'.{2,15}全文阅读$'),
    re.compile(r'.{2,15}无删减$'),
    re.compile(r'.{2,15}完整版$'),
]

# 站点宣传语通用片段 (跨站点共用, 非具体书名; 仅对短行 <40 字检查)
_AD_PHRASE_FRAGMENTS = (
    '记住本站', '收藏本站', '本站域名', '本站网址', '网址:',
    '请记住', '希望大家收藏', '手机用户', '电脑阅读', '手机阅读',
    '扫描二维码', '手机浏览器扫描',
    '发送任意邮件', '最新地址发送', '获取最新地址',
    '无弹窗', 'txt下载', '全文下载', '无删减',
    '最新章节列表', '刚刚更新', '猜你喜欢', '热门推荐',
    '同类推荐', '相邻推荐', '相关推荐', '推荐阅读',
    '加入书架', '存书签', '章节目录', '返回目录',
    '上一章', '下一章', '上一页', '下一页',
    '本章未完', '点击下一页', '继续阅读',
    '请勿开启浏览器', '阅读模式',
    '创作者：', '创作完成日',
    'Copyright', '版权所有', 'All Rights Reserved',
)

# 通用正文过滤关键词 (跨站点共用, 在 clean_content 和 get_chapter_content 中复用)
_CONTENT_FILTER_KEYWORDS = [
    # 导航元素
    '上一章', '下一章', '上一页', '下一页', '章节目录', '保存书签',
    '加入书架', '返回顶部', '首页', '末页', '目录', '书页',
    '本章未完', '本章未完，点击下一页继续阅读', '开始阅读',
    '没有了', '返回书页', '返回目录',
    # 站点宣传语/占位提示 (通用, 跨站点)
    '一秒记住新域名', '三秒记住本站', '请收藏本站', '请记住本站域名',
    '请记住域名', '手机用户请访问', '手机阅读', '电脑阅读',
    '手机版阅读', '本站网址', '网址：www', '网址:www',
    '内容正在更新', '请稍后查看', '免费提供', '在线阅读',
    '希望大家收藏', '无防盗', '转载作品', '网友上传',
    '转载至本站只是为了宣传本书让更多读者欣赏',
    '基于搜索引擎技术为您提供免费阅读无弹窗',
    # 版权/法律声明
    'Copyright', '版权所有', '本站所有内容', '本站所有小说',
    '本站爬虫遵循robots协议', '本站仅对抓取到的内容',
    # 阅读器提示
    '请勿开启浏览器阅读模式',
    # 元信息标记 (云趣阁等站点在正文前插入的元数据)
    '创作者：', '创作完成日：', '最新章节txt——',
    '最新章节列表', '刚刚更新',
    # JS 残留 (Base64 解码或渲染失败时的脚本碎片)
    'myJs.', 'bookJs', 'novelspider', 'Add to Chat',
    'document.writeln', 'document.write',
    # 通用阅读引导/广告短语
    '相邻推荐', '相关推荐', '番外+大结局',
    '全文阅读', '免费阅读', 'VIP会员', '退出浏览器',
    '后续内容已被隐藏',
]


def _is_ad_line(line):
    """通用广告行/无意义字符检测 (基于内容特征, 不依赖具体书名或站点名)

    识别策略 (分两层, 避免误伤正文):
    1. 结构特征 (对所有行): 连续空格分隔的推荐列表、纯符号行、域名行、纯数字行
    2. 标签特征 (仅对短行 <40 字): 小说搜索标签、站点宣传语片段

    正文段落通常 >40 字且含完整中文标点, 不会被误伤。

    Args:
        line: 单行文本 (已 strip)

    Returns:
        True 表示该行是广告/无意义字符, 应过滤
    """
    if not line:
        return False
    # 1. 结构特征匹配 (对所有行生效)
    for pat in _AD_LINE_STRUCT_PATTERNS:
        if pat.search(line):
            return True
    # 2. 标签特征匹配 (仅对短行 <40 字, 避免误伤正文段落)
    if len(line) < 40:
        for pat in _AD_LINE_TAG_PATTERNS:
            if pat.search(line):
                return True
        for frag in _AD_PHRASE_FRAGMENTS:
            if frag in line:
                return True
    return False


class NovelSpider:
    """
    通用小说爬虫主类。

    主要职责：
        * 管理 requests Session（请求头、Cookie、User-Agent、重试策略）
        * 解析目录页 -> 章节列表（get_chapter_list）
        * 单章正文抓取 + 多页合并 + 通用清洗（get_chapter_content）
        * 批量整书抓取 + 断点续传 + 进度条 + 保存为 TXT（run）

    内部重要属性：
        self._detected_pattern  缓存首章节识别出的正文模式，后续页复用，
                                避免重复触发特征检测请求导致分页中断。
    """

    def __init__(self, base_url):
        """
        初始化爬虫实例。

        Args:
            base_url: 站点根 URL，例如 'https://www.28zw.org'，
                      用于相对 URL 拼接与 AJAX 请求的 Referer/同源设置。
        """
        self.base_url = base_url
        self.session = requests.Session()        # 默认直连: 忽略系统/环境代理。Windows 系统代理若指向已关闭的代理软件
        # (如 127.0.0.1:12334) 会导致所有请求 ProxyError; 小说站国内直连即可。
        # 确需代理时, 在 captcha_config.json 的 request_proxy 字段显式配置
        # (如 "http://127.0.0.1:7890"), 仅对该字段指定的代理生效。
        self.session.trust_env = False
        try:
            import _path_utils
            _cfg_path = _path_utils.resolve_data_file("captcha_config.json")
            if os.path.isfile(_cfg_path):
                _rp = json.loads(Path(_cfg_path).read_text(encoding='utf-8')).get('request_proxy') or ''
                if _rp:
                    self.session.proxies.update({'http': _rp, 'https': _rp})
        except Exception:
            pass  # 配置读取失败时保持直连
        self.session.verify = False
        self.ua = UserAgent()
        # 固定 UA (会话内不变): ① WAF 验证码放行 cookie 与 UA 绑定, 每次随机 UA
        # 会导致验证码白过; ② 固定 UA 更接近真实浏览器, 降低反爬触发率
        self._fixed_ua = self.ua.random
        # 添加完整的请求头，模拟真实浏览器
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'DNT': '1',
            'Sec-GPC': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Pragma': 'no-cache',
            'TE': 'trailers'
        })
        # 启用会话的持久连接
        self.session.keep_alive = True
        # ===== 验证码处理模块 (可插拔: 规避优先 + 分级识别 + 监控容错) =====
        # 独立模块 captcha_module.py, 与核心爬取逻辑解耦;
        # 初始化失败时降级为内置人工流程, 不影响爬虫主功能
        self._captcha_manager = None
        self._avoidance = None
        try:
            from captcha_module import build_manager
            self._captcha_manager, self._avoidance = build_manager(ua_provider=self.ua)
            print("[验证码模块] 已加载 (策略: {})".format(
                self._captcha_manager.current_strategy()))
        except Exception as e:
            print(f"[验证码模块] 初始化失败, 使用内置人工流程: {e}")
        # tanmixs.com 持久化 Selenium driver: 验证码解决后复用同一浏览器实例
        # 避免每次创建新driver都触发WAF验证码
        self._tanmixs_driver = None
        self._tanmixs_user_data = os.path.join(tempfile.gettempdir(), 'tanmixs_chrome_profile')
        # 并发模式: 每个线程独立 driver + 独立 profile (Selenium driver 非线程安全)
        self._tanmixs_concurrent = False
        # 通用数据文件解码模式 (每章第1页探测, 命中后整章走数据文件)
        self._datafile_mode = False

    def _create_tanmixs_driver(self, visible=False, profile_dir=None):
        """创建 tanmixs.com 专用的浏览器 driver (支持反检测引擎)

        Args:
            visible: 是否使用非无头模式 (验证码解决时需要)
            profile_dir: 浏览器 profile 目录 (并发时每线程独立, 避免锁冲突)

        Returns:
            新建的 driver (PlaywrightDriver 或 Selenium WebDriver, 接口兼容)
        """
        if profile_dir is None:
            profile_dir = self._tanmixs_user_data

        # 引擎选择: 默认 Playwright (反检测指纹, 显著降低 WAF 验证码触发率)
        # 可在 captcha_config.json 的 browser_engine 字段切换为 selenium
        engine = 'playwright'
        if self._captcha_manager is not None:
            try:
                engine = self._captcha_manager.config.data.get('browser_engine', 'playwright')
            except Exception:
                pass
        if engine == 'playwright':
            try:
                from browser_driver import create_driver
                driver = create_driver(engine='playwright', visible=visible,
                                       user_data_dir=profile_dir)
                return driver
            except Exception as e:
                print(f"[tanmixs] Playwright 反检测引擎启动失败: {str(e)[:100]}, 回退 Selenium")

        options = Options()
        if not visible:
            options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-popup-blocking')
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('user-agent=Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36')
        options.add_argument('--window-size=800,600')
        options.add_argument('--disable-notifications')
        options.add_argument(f'--user-data-dir={profile_dir}')

        try:
            driver = webdriver.Chrome(options=options)
        except Exception as e:
            # profile 损坏(上次运行崩溃遗留)会导致 Chrome 无法启动:
            # 备份损坏的 profile 并换全新 profile 重试, 保证爬虫可用
            print(f"[tanmixs] 使用持久化 profile 启动失败: {str(e)[:120]}")
            print(f"[tanmixs] 备份损坏的 profile 并创建新 profile 重试...")
            try:
                import shutil
                backup_dir = profile_dir + f'_corrupt_{int(time.time())}'
                if os.path.exists(profile_dir):
                    shutil.move(profile_dir, backup_dir)
                    print(f"[tanmixs] 已备份损坏 profile 到: {backup_dir}")
            except Exception as be:
                print(f"[tanmixs] 备份失败(继续尝试): {be}")
                try:
                    shutil.rmtree(profile_dir, ignore_errors=True)
                except Exception:
                    pass
            driver = webdriver.Chrome(options=options)

        driver.set_page_load_timeout(30)
        driver.set_script_timeout(30)
        return driver

    def _get_tanmixs_driver(self, visible=False):
        """获取或创建 tanmixs.com 专用的持久化 Selenium driver

        Args:
            visible: 是否使用非无头模式 (验证码解决时需要)

        Returns:
            WebDriver 实例 (持久化, 跨请求复用; 并发模式下为线程独立实例)
        """
        # 并发模式: 每个线程独立 driver + 独立 profile (避免共享 driver 竞态与 profile 锁)
        if self._tanmixs_concurrent:
            import threading
            tls = threading.local()
            if not hasattr(tls, '_tanmixs_driver'):
                tls._tanmixs_driver = self._create_tanmixs_driver(
                    visible, os.path.join(tempfile.gettempdir(), f'tanmixs_profile_{threading.get_ident()}'))
            return tls._tanmixs_driver

        # 如果已有持久化driver且模式匹配, 直接复用
        if self._tanmixs_driver is not None:
            try:
                # 测试driver是否还活着
                _ = self._tanmixs_driver.current_url
                return self._tanmixs_driver
            except Exception:
                try:
                    self._tanmixs_driver.quit()
                except Exception:
                    pass
                self._tanmixs_driver = None

        driver = self._create_tanmixs_driver(visible)
        self._tanmixs_driver = driver
        return driver

    def _solve_tanmixs_captcha(self, driver, url):
        """检测并处理 tanmixs.com WAF验证码
        
        如果当前页面是验证码页面, 切换到非无头浏览器让用户解决,
        解决后复用同一driver继续。如果已有driver是非无头的, 直接在当前driver上等待。
        
        Args:
            driver: 当前WebDriver实例
            url: 目标URL
            
        Returns:
            page_source (str): 验证码解决后的页面源码
            None: 如果不是验证码页面
        """
        page_source = driver.page_source
        if '__wafcaptcha' not in page_source and '_waform' not in page_source and '访问频率太高' not in page_source:
            return page_source  # 不是验证码页面, 直接返回

        print("[tanmixs] 检测到WAF验证码页面")
        # 优先走验证码模块的自动识别链 (ddddocr → slider → 打码平台 → 人工)
        # 仅当配置中启用了对应识别策略时才会尝试自动识别, 否则直接进入人工流程
        if self._captcha_manager is not None:
            try:
                solved = self._captcha_manager.handle(driver, url, page_source)
                if solved is not None and not self._captcha_manager.is_captcha_page(solved):
                    print("[tanmixs] ✅ 验证码模块已解决 (自动识别或人工输入)")
                    self._captcha_manager.record_request(True)
                    return solved
                print("[tanmixs] 验证码模块未解决, 回退内置人工流程")
            except Exception as e:
                print(f"[tanmixs] 验证码模块异常, 回退内置人工流程: {e}")
        # 关闭当前headless driver, 切换到可见driver
        try:
            driver.quit()
        except Exception:
            pass
        if self._tanmixs_concurrent:
            # 并发模式: 重置当前线程的 driver, 用可见模式重建
            import threading
            tls = threading.local()
            tls._tanmixs_driver = self._create_tanmixs_driver(
                visible=True, profile_dir=os.path.join(tempfile.gettempdir(), f'tanmixs_profile_{threading.get_ident()}'))
            visible_driver = tls._tanmixs_driver
        else:
            self._tanmixs_driver = None
            # 创建可见driver (复用同一user-data-dir)
            visible_driver = self._get_tanmixs_driver(visible=True)
        visible_driver.get(url)
        print("[tanmixs] 已打开浏览器窗口, 请在浏览器中输入验证码图片字符并提交")
        print("[tanmixs] 系统将自动检测验证码是否已解决 (最多等待5分钟)...")

        # 自动轮询检测验证码是否已解决
        captcha_solved = False
        for wait_round in range(60):
            time.sleep(5)
            try:
                cur_src = visible_driver.page_source
                if '__wafcaptcha' not in cur_src and '_waform' not in cur_src and '访问频率太高' not in cur_src:
                    captcha_solved = True
                    print(f"[tanmixs] 验证码已解决 (等待了{(wait_round+1)*5}秒)")
                    break
            except Exception:
                pass
            if (wait_round + 1) % 6 == 0:
                print(f"[tanmixs] 仍在等待验证码解决... (已等待{(wait_round+1)*5}秒)")

        if not captcha_solved:
            print("[tanmixs] 验证码等待超时(5分钟)")
            raise RuntimeError('验证码超时未解决')

        # 验证码解决后, 用同一driver访问目标URL
        visible_driver.get(url)
        WebDriverWait(visible_driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, 'body'))
        )
        time.sleep(2)
        page_source = visible_driver.page_source
        print(f"[tanmixs] 验证码解决后页面长度: {len(page_source)} 字符")
        return page_source

    def _get_with_js_challenge(self, url, headers=None, timeout=30):
        """发起GET请求并处理JS cookie校验反爬(如zhiruo.org的ge_js_validator)。
        首次响应可能是一个通过<script>设置cookie后window.location.reload的校验页面，
        这里提取document.cookie并重试，直到拿到真实内容。返回最终的response对象。
        注意: 调用方headers中不要硬编码Cookie头，否则会覆盖session.cookies导致校验cookie发不出去。"""
        validate_public_url(url)  # 安全校验: 仅允许公网 http/https
        _t0 = time.time()
        challenge_markers = ['ge_js_validator', 'window.location.reload']
        response = self.session.get(url, headers=headers, timeout=timeout)
        # ---- WAF 图片验证码 (banlvzw 等: 401 + __wafcaptcha 特征) ----
        # 放行 cookie 会按请求数/时间过期, 因此每次命中 401 都尝试重新解决;
        # 失败后 60 秒冷却, 避免 IP 被拉黑时无限重试刷屏。
        # 识别需要 captcha_config.json 显式开启 ddddocr (默认关闭)
        try:
            from waf_captcha import is_waf_captcha_page, solve_waf_captcha
        except Exception:
            is_waf_captcha_page = None
            solve_waf_captcha = None
        if is_waf_captcha_page is not None:
            if not hasattr(self, '_waf_last_try'):
                self._waf_last_try = 0.0
            _now_t = time.time()
            # 冷却只针对"解决失败" (IP 可能被拉黑); 解决成功后立即重置,
            # 因为该 WAF 按请求数限频, 放行 cookie 会周期性过期, 需随时可重试
            if is_waf_captcha_page(response.status_code, response.text) and \
                    _now_t - self._waf_last_try > 60:
                try:
                    print(f"[反爬检测] 命中 WAF 图片验证码页 ({len(response.text)}字节)，尝试自动解决...")
                    if solve_waf_captcha(self.session, url, headers=headers, log=print):
                        self._waf_last_try = 0.0  # 成功: 允许后续立即重试
                        response = self.session.get(url, headers=headers, timeout=timeout)
                    else:
                        self._waf_last_try = time.time()  # 失败: 60 秒冷却
                except Exception as e:
                    print(f"[反爬检测] WAF 验证码处理异常: {e}")

        # ---- WAF JS 动态令牌挑战 (banlvzw 等: 401 + @wafjs 混淆脚本) ----
        # 页面含 Loading 转圈 + /@wafjs? 脚本, 需浏览器执行 JS 生成令牌 cookie。
        # 用 Playwright 渲染一次, 把浏览器 cookie 回灌 requests session。
        if is_waf_captcha_page is not None and _is_waf_js_challenge(response):
            if not hasattr(self, '_waf_js_last_try'):
                self._waf_js_last_try = 0.0
            _now_t = time.time()
            if _now_t - self._waf_js_last_try > 30:
                self._waf_js_last_try = _now_t
                try:
                    print("[反爬检测] 命中 WAF JS 挑战页, 用浏览器渲染获取令牌 cookie...")
                    if self._solve_waf_js_challenge(url):
                        self._waf_js_last_try = 0.0
                        # 令牌 cookie 绑定浏览器 UA, 重试时用同步后的 UA
                        hdrs2 = dict(headers or {})
                        hdrs2['User-Agent'] = self._fixed_ua
                        response = self.session.get(url, headers=hdrs2, timeout=timeout)
                except Exception as e:
                    print(f"[反爬检测] WAF JS 挑战处理异常: {e}")
        for retry in range(4):
            raw = response.content
            if not any(m.encode() in raw for m in challenge_markers):
                break
            print(f"[反爬检测] 第{retry+1}次请求命中JS cookie校验页面({len(raw)}字节)，提取cookie后重试...")
            m = re.search(rb'document\.cookie\s*=\s*"([^"]+)"', raw)
            if m:
                cookie_str = m.group(1).decode('utf-8', errors='ignore')
                cookie_kv = cookie_str.split(';')[0].strip()
                if '=' in cookie_kv:
                    ck_name, ck_val = cookie_kv.split('=', 1)
                    self.session.cookies.set(ck_name.strip(), ck_val.strip())
                    print(f"[反爬检测] 已设置cookie: {ck_name.strip()}")
            time.sleep(2)
            response = self.session.get(url, headers=headers, timeout=timeout)
        # 调试日志: 请求 URL + 状态码 + 耗时 (供事后排查网络/反爬问题)
        print(f"[调试] GET {url} -> 状态 {response.status_code}, 耗时 {time.time()-_t0:.2f}s")
        return response

    def _solve_waf_js_challenge(self, url, max_wait: int = 12) -> bool:
        """用 Playwright 渲染解决 WAF JS 动态令牌挑战, 并把浏览器 cookie 回灌 requests session。

        Args:
            url: 被挑战拦截的 URL
            max_wait: 等待 JS 挑战完成的最长秒数

        Returns:
            True=已获得令牌 cookie
        """
        try:
            from browser_driver import create_driver
        except Exception as e:
            print(f"[反爬检测] Playwright 不可用: {e}")
            return False
        driver = None
        try:
            driver = create_driver(engine='playwright', visible=False)
            driver.get(url)
            # 等待 JS 挑战执行 (spinner → 跳转真实页), 最长 max_wait 秒
            deadline = time.time() + max_wait
            while time.time() < deadline:
                time.sleep(2)
                try:
                    src = driver.page_source
                    if src and '@wafjs' not in src and 'Loading...' not in src \
                            and '<title>' in src and 'loading banlvzw' not in src:
                        break
                except Exception:
                    pass
            cookies = driver.get_cookies()
            if not cookies:
                print("[反爬检测] 浏览器未获得令牌 cookie")
                return False
            # 令牌 cookie 绑定浏览器 UA: 把浏览器 UA 同步到 session,
            # 否则 requests 用自己的 UA 请求仍会被挑战拦截
            try:
                ua = driver.execute_script('return navigator.userAgent;')
                if ua:
                    self._fixed_ua = ua
                    self.session.headers['User-Agent'] = ua
            except Exception:
                pass
            # 把浏览器 cookie 回灌 requests session (cookie 有效期一般 24 小时)
            for c in cookies:
                if c.get('name') and c.get('value') is not None:
                    try:
                        self.session.cookies.set(
                            c['name'], c['value'],
                            domain=c.get('domain', ''),
                            path=c.get('path', '/'),
                        )
                    except Exception:
                        try:
                            self.session.cookies.set(c['name'], c['value'])
                        except Exception:
                            pass
            print(f"[反爬检测] ✅ 已获取 {len(cookies)} 个令牌 cookie, 回灌 session")
            return True
        except Exception as e:
            print(f"[反爬检测] JS 挑战渲染失败: {e}")
            return False
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    def _selenium_get_soup(self, url, headers):
        """统一 Selenium 抓取: 创建无头 Chrome → 访问页面 → 处理 JS cookie 反爬 → 返回 BeautifulSoup。
        失败时返回 None。driver 在 finally 中自动关闭。
        """
        if not selenium_available:
            return None
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-popup-blocking')
            chrome_options.add_argument('--ignore-certificate-errors')
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_argument(f'user-agent={headers["User-Agent"]}')
            chrome_options.add_argument('--disable-notifications')

            driver = webdriver.Chrome(options=chrome_options)
            driver.set_page_load_timeout(30)
            driver.set_script_timeout(30)
            try:
                driver.get(url)
                _wait_driver_body(driver)
                time.sleep(2)
                page_source = driver.page_source
                # 处理 JS cookie 校验反爬 (如 zhiruo.org)
                challenge_markers = ['ge_js_validator', 'window.location.reload', 'document.cookie']
                for _ in range(5):
                    if not any(m in page_source for m in challenge_markers):
                        break
                    print(f"[反爬检测] 检测到JS cookie校验页面({len(page_source)}字符)，等待reload后重试...")
                    time.sleep(3)
                    page_source = driver.page_source
                print(f"[Selenium] 获取到页面内容，长度: {len(page_source)} 字符")
                return BeautifulSoup(page_source, 'lxml')
            finally:
                try:
                    driver.quit()
                except Exception as e:
                    print(f"[Selenium] 关闭浏览器失败: {e}")
        except Exception as e:
            print(f"[Selenium] 抓取失败: {e}")
            return None

    def inspect_page(self, url):
        """获取网页结构"""
        validate_public_url(url)  # 安全校验: 仅允许公网 http/https
        # 尝试使用不同的User-Agent和请求头
        headers = {
            'User-Agent': self._fixed_ua,  # 会话固定UA (验证码cookie绑定UA)
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'DNT': '1',
            'Sec-GPC': '1',
            'Referer': url,
            'Host': url.split('/')[2],
            # 不要在此硬编码 Cookie 头：requests 传入 headers 中的 Cookie 会覆盖 session.cookies，
            # 导致反爬提取的 cookie(如 zhiruo.org 的 ge_js_validator_20)无法随请求发出，校验永远过不去。
            # 让 session.cookies 自动管理即可。
            'Pragma': 'no-cache',
            'TE': 'trailers'
        }
        
        # tanmixs.com: 使用持久化 Selenium driver, 验证码解决后复用同一浏览器实例
        # 避免每次创建新driver都触发WAF验证码
        if 'tanmixs.com' in url and selenium_available:
            print("[tanmixs] 使用持久化Selenium driver抓取")
            try:
                driver = self._get_tanmixs_driver(visible=False)
                driver.get(url)
                _wait_driver_body(driver)
                # tanmixs 为服务端渲染静态页, driver.get 返回即内容就绪, 无需额外等待
                page_source = driver.page_source
                # 检测并处理验证码 (如有)
                page_source = self._solve_tanmixs_captcha(driver, url)
                if '<html' in page_source.lower() or '<body' in page_source.lower():
                    print(f"[tanmixs] 成功获取页面, 长度: {len(page_source)} 字符")
                    soup = BeautifulSoup(page_source, 'lxml')
                    return soup
                else:
                    print("[tanmixs] 未能获取到HTML内容")
            except Exception as e:
                print(f"[tanmixs] Selenium抓取失败: {e}")
                import traceback
                traceback.print_exc()

        # 对于qingheks.com、27xsw.cc网站，直接使用Selenium
        # (zhiruo.org也使用JS cookie校验反爬ge_js_validator，但经测试用requests提取cookie重试即可绕过，
        #  无需Selenium，因此zhiruo.org走下方requests路径；仅当requests失败时才回退到末尾的Selenium)
        if ('qingheks.com' in url or '27xsw.cc' in url) and selenium_available:
            print(f"直接使用Selenium抓取{url.split('/')[2]}网站")
            soup = self._selenium_get_soup(url, headers)
            if soup:
                return soup
        
        time.sleep(3)  # 增加延迟，避免被反爬虫
        
        try:
            response = self._get_with_js_challenge(url, headers)

            # 尝试使用ignore模式解码
            try:
                text = response.content.decode('utf-8', errors='ignore')
                # 打印解码后的内容，看看实际获取到了什么
                print(f"解码后内容前500个字符: {text[:500]}")
                # 检查解码后的内容是否包含HTML标签
                if '<html' in text.lower() or '<body' in text.lower():
                    print(f"成功获取到HTML内容，长度: {len(text)} 字符")
                    response.encoding = 'utf-8'
                    soup = BeautifulSoup(text, 'lxml')
                    return soup
                else:
                    # 尝试使用其他解析器
                    print("尝试使用html.parser解析器")
                    soup = BeautifulSoup(text, 'html.parser')
                    if soup.find():  # 检查是否解析出了任何元素
                        print("成功解析出HTML元素")
                        return soup
            except Exception as e:
                print(f"解码失败: {e}")
        except Exception as e:
            print(f"请求失败: {e}")
        
        # requests 失败后的 Selenium 兜底 (复用 _selenium_get_soup 方法)
        if ('qingheks.com' in url or '27xsw.cc' in url or 'zhiruo.org' in url or 'tanmixs.com' in url) and selenium_available:
            soup = self._selenium_get_soup(url, headers)
            if soup:
                return soup
        
        # 如果所有尝试都失败，返回空的BeautifulSoup对象
        return BeautifulSoup('', 'lxml')

    def get_chapter_list(self, catalog_url, sort_chapters=False):
        """
        从小说目录页提取章节列表。

        处理顺序：
            1. 域名特判分支（zhiruo / baoshuism / 11bzw / yqyp / 云趣阁等）
               — 目录页结构差异大的站点单独适配
            2. 通用链接过滤：按路径规则 + 同路径前缀 筛选出所有疑似章节链接
            3. 数字排序（sort_chapters=True 时）：按章节号 / URL 尾号重排

        Args:
            catalog_url: 目录页 URL
            sort_chapters: 是否按数字序重新排序章节（部分站点目录为倒序或乱序）

        Returns:
            list[dict]: [{'title': str, 'url': str}, ...] 可能为空列表
        """
        chapters = []
        
        # 提取当前小说的URL路径部分，用于过滤章节链接

        # exotxt.net: URL规范化 (在fetch之前), /infos/5556990/1/ → /infos/5556990.html
        if 'exotxt.net' in catalog_url:
            book_id_match = re.search(r'/infos/(\d+)', catalog_url)
            if book_id_match:
                book_id = book_id_match.group(1)
                normalized_url = f"{self.base_url}/infos/{book_id}.html"
                if normalized_url != catalog_url:
                    print(f"[exotxt.net] 规范化目录URL: {catalog_url} → {normalized_url}")
                    catalog_url = normalized_url

        # 先查看网页结构
        soup = self.inspect_page(catalog_url)

        # 特殊处理zhiruo.org网站：目录页章节链接用 onclick="read_tz(章节ID)" 而非 href，
        # 正文URL格式为 /infos/{小说ID}/{章节ID}.html；目录可能分页 /infos/{id}/1/, /infos/{id}/2/ ...
        if 'zhiruo.org' in catalog_url:
            print("检测到zhiruo.org网站，使用onclick解析章节列表")
            novel_id_match = re.search(r'/infos/(\d+)', catalog_url)
            if not novel_id_match:
                print("[zhiruo] 无法从URL提取小说ID")
                return chapters
            novel_id = novel_id_match.group(1)
            seen_ids = set()
            page_no = 1
            while True:
                if page_no == 1:
                    page_soup = soup  # 第1页已由inspect_page抓取，直接复用
                else:
                    catalog_page_url = f"{self.base_url}/infos/{novel_id}/{page_no}/"
                    print(f"[zhiruo] 抓取目录第{page_no}页: {catalog_page_url}")
                    page_soup = self.inspect_page(catalog_page_url)
                if not page_soup:
                    break
                chap_as = page_soup.find_all('a', onclick=re.compile(r'read_tz\s*\('))
                if not chap_as:
                    print(f"[zhiruo] 第{page_no}页未找到章节链接，结束分页提取")
                    break
                new_count = 0
                for a in chap_as:
                    onclick = a.get('onclick', '')
                    m = re.search(r'read_tz\s*\(\s*(\d+)\s*\)', onclick)
                    if not m:
                        continue
                    chap_id = m.group(1)
                    if chap_id in seen_ids:
                        continue
                    seen_ids.add(chap_id)
                    title = a.get_text(strip=True)
                    if not title:
                        continue
                    chap_url = f"{self.base_url}/infos/{novel_id}/{chap_id}.html"
                    chapters.append({'title': self.clean_chapter_title(title), 'url': chap_url})
                    new_count += 1
                print(f"[zhiruo] 第{page_no}页: 新增 {new_count} 章，累计 {len(chapters)} 章")
                if new_count == 0:
                    break
                page_no += 1
                if page_no > 50:  # 安全上限
                    break
            print(f"[zhiruo] 共提取 {len(chapters)} 个章节")
            if sort_chapters and chapters:
                chapters.sort(key=_chapter_sort_key)
                print("[zhiruo] 已按章节号排序")
            for i, chap in enumerate(chapters):
                print(f"  {i+1}. {chap['title']} -> {chap['url']}")
            return chapters

        # 特殊处理biquwx.cc网站:
        # 目录URL可能是 /index/{id}/1/ (含最新章节) 或 /txt{id}.shtml (全文目录);
        # 章节链接格式 /{cat_id}/{book_id}/{chap_id}.html, 容器在 #list dl 下;
        # 正文用 qsbs.bb Base64 加密。
        if 'biquwx.cc' in catalog_url:
            print("检测到biquwx.cc网站，使用专门的处理逻辑")
            book_id_match = re.search(r'[/_](\d{5,})', catalog_url)
            book_id = book_id_match.group(1) if book_id_match else ''
            print(f"当前小说ID: {book_id}")
            # 优先访问全文目录 /txt{id}.shtml，其次是原始catalog_url
            pages_to_try = []
            if book_id:
                pages_to_try.append(f"{self.base_url}/txt{book_id}.shtml")
            if catalog_url not in pages_to_try:
                pages_to_try.append(catalog_url)
            seen_urls = set()
            for page_url in pages_to_try:
                print(f"[biquwx] 抓取目录页: {page_url}")
                page_soup = self.inspect_page(page_url)
                if not page_soup:
                    continue
                found_on_page = 0
                # 按 #list dl a → #list a → 全文 a 递进查找
                for sel in ['#list dl a[href]', '#list a[href]', 'a[href]']:
                    page_chaps = 0
                    for a in page_soup.select(sel):
                        href = a.get('href', '')
                        text = a.get_text(strip=True)
                        if not text or len(text) < 2:
                            continue
                        if 'javascript' in href.lower():
                            continue
                        # 正文链接格式: /{cat_id}/{book_id}/{chap_id}.html 或 完整URL
                        if not (f'/{book_id}/' in href and re.search(r'\d+\.html?$', href)):
                            # 全文 a 扫描时更宽松：只要末尾含 /数字.html 且 文本含"第X章"
                            if sel != 'a[href]':
                                continue
                            if not re.match(r'^第[一二三四五六七八九十百千0-9零]+[章节回话篇]', text):
                                continue
                            if not re.search(r'/\d+\.html?$', href):
                                continue
                        if not href.startswith('http'):
                            href = self.base_url + href
                        if href in seen_urls:
                            continue
                        seen_urls.add(href)
                        chapters.append({'title': self.clean_chapter_title(text), 'url': href})
                        page_chaps += 1
                    if page_chaps > 0:
                        found_on_page += page_chaps
                        print(f"[biquwx] 选择器 {sel} 提取 {page_chaps} 章")
                        break  # 这个选择器命中了就不用下一个
                if found_on_page:
                    print(f"[biquwx] 页面 {page_url} 共新增 {found_on_page} 章")
            # 按章节号排序(biquwx常倒序显示，最新在前)
            if sort_chapters and chapters:
                chapters.sort(key=_chapter_sort_key)
                print("[biquwx] 已按章节号排序")
            print(f"[biquwx] 共提取 {len(chapters)} 个章节")
            for i, chap in enumerate(chapters):
                print(f"  {i+1}. {chap['title'][:60]} -> {chap['url']}")
            return chapters

        # 特殊处理11bzw.org网站:
        # 目录URL为 /index/{aid}/，章节链接格式 /read/{aid}/{cid}.html;
        # 正文通过两步AJAX加载(签名+内容接口)，见get_chapter_content。
        if '11bzw.org' in catalog_url:
            print("检测到11bzw.org网站，使用专门的处理逻辑")
            aid_match = re.search(r'/(?:index|book)/(\d+)', catalog_url)
            if not aid_match:
                print("[11bzw] 无法从URL提取小说ID")
                return chapters
            aid = aid_match.group(1)
            print(f"[11bzw] 小说ID: {aid}")
            # 目录页可能含"开始阅读"等导航链接，对每个cid选最长文本作为章节名
            cid_texts = {}
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text(strip=True)
                if not text:
                    continue
                m = re.search(r'/read/' + aid + r'/(\d+)\.html', href)
                if not m:
                    continue
                cid = m.group(1)
                # 选较长的文本(章节名通常比"开始阅读"等导航词长)
                if cid not in cid_texts or len(text) > len(cid_texts[cid]):
                    cid_texts[cid] = text
            # 按cid数字顺序排序
            for cid in sorted(cid_texts.keys(), key=lambda x: int(x)):
                title = self.clean_chapter_title(cid_texts[cid])
                chap_url = f"{self.base_url}/read/{aid}/{cid}.html"
                chapters.append({'title': title, 'url': chap_url})
            print(f"[11bzw] 共提取 {len(chapters)} 个章节")
            for i, chap in enumerate(chapters):
                print(f"  {i+1}. {chap['title'][:60]} -> {chap['url']}")
            return chapters

        # 特殊处理yqyp.net网站:
        # 目录URL为 /book/{aid}.html, 章节链接格式 /book/{aid}/{cid}.html;
        # 目录页章节倒序+正序重复, 需去重并按章节号排序;
        # 正文在 div.info_dv1.ov 下第一个 div.read_btn 之后的 <p> 标签中。
        if 'yqyp.net' in catalog_url:
            print("检测到yqyp.net网站，使用专门的处理逻辑")
            aid_match = re.search(r'/book/(\d+)', catalog_url)
            if not aid_match:
                print("[yqyp] 无法从URL提取小说ID")
                return chapters
            aid = aid_match.group(1)
            print(f"[yqyp] 小说ID: {aid}")
            # 目录页可能是 /book/{aid}.html (用户给的是章节页时需跳转)
            catalog_page_url = f"{self.base_url}/book/{aid}.html"
            if catalog_url.endswith(f"/{aid}.html"):
                catalog_page_url = catalog_url
            print(f"[yqyp] 目录页: {catalog_page_url}")
            page_soup = self.inspect_page(catalog_page_url)
            if not page_soup:
                print("[yqyp] 目录页获取失败")
                return chapters
            # 提取 /book/{aid}/{cid}.html 链接, 去重(同一cid取第一次出现)
            seen_cids = set()
            for a in page_soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text(strip=True)
                if not text or '立即阅读' in text:
                    continue
                m = re.search(r'/book/' + aid + r'/(\d+)\.html', href)
                if not m:
                    continue
                cid = m.group(1)
                if cid in seen_cids:
                    continue
                seen_cids.add(cid)
                chapters.append({'title': self.clean_chapter_title(text), 'url': f"{self.base_url}/book/{aid}/{cid}.html"})
            # 按章节号排序
            chapters.sort(key=_chapter_sort_key)
            print(f"[yqyp] 共提取 {len(chapters)} 个章节")
            for i, chap in enumerate(chapters):
                print(f"  {i+1}. {chap['title'][:60]} -> {chap['url']}")
            return chapters

        # 特殊处理云趣阁 (28zw.org / spscl.com 等镜像):
        # 目录URL可能是 /book/{aid}/ (小说详情页) 或 /book/{aid}/ml{N}.html (分页目录);
        # 详情页含"最新章节"倒序列表 + "章节列表"正序, 需去重并按章节号排序;
        # 章节链接格式 /book/{aid}/{cid}.html (spscl.com 用 /yue/{aid}/{cid}.html);
        # 正文在 div.content / div.word_read 的 <p> 标签中, 见 get_chapter_content。
        if '28zw.org' in catalog_url or 'spscl.com' in catalog_url:
            print("检测到云趣阁(28zw.org/spscl.com)，使用专门的处理逻辑")
            is_yue = '/yue/' in catalog_url
            path_prefix = '/yue/' if is_yue else '/book/'
            aid_match = re.search(path_prefix + r'(\d+)', catalog_url)
            if not aid_match:
                print("[云趣阁] 无法从URL提取小说ID")
                return chapters
            aid = aid_match.group(1)
            print(f"[云趣阁] 小说ID: {aid}")

            # 收集所有目录分页 URL (ml1.html, ml2.html, ...)
            # 同时把详情页本身也作为一页(含"章节列表"区, 部分短篇只有详情页)
            catalog_pages = [catalog_url]
            for page_no in range(1, 30):
                ml_url = f"{self.base_url}{path_prefix}{aid}/ml{page_no}.html"
                if ml_url not in catalog_pages:
                    catalog_pages.append(ml_url)

            seen_cids = set()
            for page_url in catalog_pages:
                print(f"[云趣阁] 抓取目录页: {page_url}")
                page_soup = self.inspect_page(page_url)
                if not page_soup:
                    continue
                new_on_page = 0
                for a in page_soup.find_all('a', href=True):
                    href = a['href']
                    text = a.get_text(strip=True)
                    if not text:
                        continue
                    # 章节链接格式: /book/{aid}/{cid}.html 或 /yue/{aid}/{cid}.html
                    # 排除 ml{N}.html (目录分页本身) 和 {cid}_N.html (章节分页)
                    m = re.search(path_prefix + aid + r'/(\d+)\.html$', href)
                    if not m:
                        continue
                    cid = m.group(1)
                    if cid in seen_cids:
                        continue
                    # 过滤明显非章节链接 (如"查看更多章节..."、"开始阅读")
                    if any(kw in text for kw in ['查看更多', '更多章节', '开始阅读', '立即阅读',
                                                  '章节目录', '全部章节', '上一页', '下一页']):
                        continue
                    seen_cids.add(cid)
                    chap_url = f"{self.base_url}{path_prefix}{aid}/{cid}.html"
                    chapters.append({'title': self.clean_chapter_title(text), 'url': chap_url})
                    new_on_page += 1
                print(f"[云趣阁] 页面 {page_url} 新增 {new_on_page} 章，累计 {len(chapters)} 章")
                # 当前页没拿到任何新章节 → 后续分页应已结束
                if new_on_page == 0 and page_url != catalog_url:
                    break

            # 按章节号/章节数字排序 (云趣阁目录常倒序+正序混合)
            if sort_chapters and chapters:
                chapters.sort(key=_chapter_sort_key)
                print("[云趣阁] 已按章节号排序")
            print(f"[云趣阁] 共提取 {len(chapters)} 个章节")
            for i, chap in enumerate(chapters):
                print(f"  {i+1}. {chap['title'][:60]} -> {chap['url']}")
            return chapters

        # 特殊处理 tanmixs.com (探秘小说网移动版)
        # 目录分页: /{book_id}/ml.html (第1页) → /{book_id}/ml_N.html (后续页, N=2,3,...)
        # 注意: ml_1.html 与 ml.html 内容相同, 应跳过
        # 章节链接: /{book_id}/{chapter_id}.html
        # 目录页章节标题统一为 "分章阅读 N", 实际标题在章节页第一段
        if 'tanmixs.com' in catalog_url:
            print("检测到tanmixs.com网站，使用专门的处理逻辑")
            book_id_match = re.search(r'/([A-Za-z0-9]+)/', catalog_url)
            if not book_id_match:
                print("[tanmixs] 无法从URL提取小说ID")
                return chapters
            book_id = book_id_match.group(1)
            novel_path = f'/{book_id}/'
            novel_path_alt = novel_path
            print(f"[tanmixs] 小说ID: {book_id}, 路径: {novel_path}")

            # 收集所有目录分页 URL
            # ml.html (第1页, 不带数字) + ml_2.html, ml_3.html, ... (后续页)
            # ml_1.html 与 ml.html 内容重复, 跳过
            catalog_pages = [catalog_url]
            for page_no in range(2, 30):
                ml_url = f"{self.base_url}/{book_id}/ml_{page_no}.html"
                if ml_url not in catalog_pages:
                    catalog_pages.append(ml_url)

            seen_cids = set()
            for page_url in catalog_pages:
                print(f"[tanmixs] 抓取目录页: {page_url}")
                page_soup = self.inspect_page(page_url)
                if not page_soup:
                    continue
                new_on_page = 0
                # 优先从 ul.chapter-list 提取, 避免匹配到推荐区
                chap_list_ul = page_soup.find('ul', class_='chapter-list')
                if chap_list_ul:
                    link_containers = [chap_list_ul]
                else:
                    link_containers = None
                for a in (chap_list_ul.find_all('a', href=True) if chap_list_ul else page_soup.find_all('a', href=True)):
                    href = a.get('href', '')
                    text = a.get_text(strip=True)
                    if not text:
                        continue
                    # 章节链接格式: /{book_id}/{cid}.html
                    m = re.search(rf'/{book_id}/(\d+)\.html$', href)
                    if not m:
                        continue
                    cid = m.group(1)
                    if cid in seen_cids:
                        continue
                    # 过滤掉目录分页本身 (ml*.html) 和推荐区
                    if href.endswith('ml.html') or '/ml_' in href or '/ml' in href:
                        continue
                    # 过滤非章节链接
                    if any(kw in text for kw in ['查看更多', '更多章节', '开始阅读', '立即阅读',
                                                  '章节目录', '全部章节', '上一页', '下一页',
                                                  '返回介绍', '下载作品', '分类', '排行', '完本',
                                                  '首页', '地图', '找小说', '简体', '繁体']):
                        continue
                    seen_cids.add(cid)
                    chap_url = f"{self.base_url}/{book_id}/{cid}.html"
                    # 标题处理: 优先用章节页提取的真实标题
                    # 目录页常出现 "分章阅读 N" (快速跳转) 或 "[tanmixs.com]分章阅读 N" / "{探秘小说网}分章阅读 N" (站点水印+跳转) 等非真实标题
                    # 真实章节标题在章节页第一段, 此处统一用 "第N章" 作为占位符
                    if ('分章阅读' in text
                            or re.match(r'^\s*[\[{].+?[\]}]', text)
                            or not text):
                        chap_title = f'第{cid}章'
                    else:
                        chap_title = text
                    chapters.append({'title': self.clean_chapter_title(chap_title), 'url': chap_url})
                    new_on_page += 1
                print(f"[tanmixs] 页面 {page_url} 新增 {new_on_page} 章，累计 {len(chapters)} 章")
                # 当前页没拿到任何新章节 → 后续分页应已结束 (到末尾了)
                if new_on_page == 0 and page_url != catalog_url:
                    break

            # 按章节号排序
            if sort_chapters and chapters:
                chapters.sort(key=_chapter_sort_key)
                print("[tanmixs] 已按章节号排序")
            print(f"[tanmixs] 共提取 {len(chapters)} 个章节")
            for i, chap in enumerate(chapters[:10]):
                print(f"  {i+1}. {chap['title'][:60]} -> {chap['url']}")
            if len(chapters) > 10:
                print(f"  ... (共 {len(chapters)} 章)")
            return chapters

        # 特殊处理hatxt.cc网站
        if 'hatxt.cc' in catalog_url:
            print("检测到hatxt.cc网站，使用专门的处理逻辑")
            # 提取小说ID
            novel_id_pattern = re.search(r'/books/(\d+)', catalog_url)
            novel_id = novel_id_pattern.group(1) if novel_id_pattern else ''
            print(f"当前小说ID: {novel_id}")
            # 构建两种可能的路径格式
            novel_path = f'/books/{novel_id}/'
            novel_path_alt = f'/books/{novel_id}'  # 用于匹配194971_1.html这种格式
        # 特殊处理pjxdd.com网站
        elif 'pjxdd.com' in catalog_url:
            print("检测到pjxdd.com网站，使用专门的处理逻辑")
            # 提取小说路径
            novel_path_pattern = re.search(r'(/xiaoshuo/\d+/)', catalog_url)
            novel_path = novel_path_pattern.group(1) if novel_path_pattern else ''
            novel_path_alt = novel_path  # 对于pjxdd.com，两种路径格式相同
        # 特殊处理ahxsw.com网站
        elif 'ahxsw.com' in catalog_url:
            print("检测到ahxsw.com网站，使用专门的处理逻辑")
            # 提取小说ID路径，如 /book/143259/
            novel_path_pattern = re.search(r'(/book/\d+/)', catalog_url)
            novel_path = novel_path_pattern.group(1) if novel_path_pattern else ''
            # ahxsw.com的章节链接格式为 /read/143/143259/xxx.html
            # 提取/read/路径部分用于匹配
            read_path_pattern = re.search(r'(/read/\d+/\d+/)', catalog_url)
            novel_path_alt = read_path_pattern.group(1) if read_path_pattern else '/read/'
            print(f"当前小说路径: {novel_path}, 读取路径: {novel_path_alt}")
        elif '5hbook.net' in catalog_url:
            print("检测到5hbook.net网站，使用专门的处理逻辑")
            # 提取小说ID路径，如 /books/539.html → /books/539/
            novel_path_pattern = re.search(r'(/books/\d+)\.html', catalog_url)
            novel_path = (novel_path_pattern.group(1) + '/') if novel_path_pattern else ''
            novel_path_alt = novel_path
            print(f"当前小说路径: {novel_path}")
        elif 'exotxt.net' in catalog_url:
            print("检测到exotxt.net网站，使用专门的处理逻辑")
            book_id_match = re.search(r'/infos/(\d+)', catalog_url)
            book_id = book_id_match.group(1) if book_id_match else ''
            novel_path = f"/infos/{book_id}/" if book_id_match else ''
            novel_path_alt = novel_path
            print(f"当前小说路径: {novel_path}")
        else:
            # 通用逻辑：尝试多种URL模式提取小说路径
            novel_path = ''
            novel_path_alt = ''

            # 模式1: /97_97855/ (27xsw.cc格式)
            novel_path_pattern = re.search(r'(/\d+_\d+/)', catalog_url)
            if novel_path_pattern:
                novel_path = novel_path_pattern.group(1)
            else:
                # 模式2: /books/301597.html → /books/301597/ (baoshuism.com格式)
                novel_path_pattern = re.search(r'(/[a-z]+/)(\d+)\.html?', catalog_url)
                if novel_path_pattern:
                    prefix = novel_path_pattern.group(1)
                    book_id = novel_path_pattern.group(2)
                    novel_path = f"{prefix}{book_id}/"
                    print(f"[路径提取] 模式2: 从URL提取小说路径 {novel_path}")
                else:
                    # 模式3: /infos/5523629.html → /infos/5523629/ (zhiruo.org格式)
                    novel_path_pattern = re.search(r'(/[a-z]+/)(\d+)(?:\.html?|/)', catalog_url)
                    if novel_path_pattern:
                        prefix = novel_path_pattern.group(1)
                        book_id = novel_path_pattern.group(2)
                        novel_path = f"{prefix}{book_id}/"
                        print(f"[路径提取] 模式3: 从URL提取小说路径 {novel_path}")
                    else:
                        # 模式4: 提取URL中的数字ID作为关键词
                        id_match = re.search(r'/(\d{4,})', catalog_url)
                        if id_match:
                            novel_path = id_match.group(1)
                            print(f"[路径提取] 模式4: 从URL提取小说ID {novel_path}")
                        else:
                            # 模式5: /4y9k/index_1.html → /4y9k/ (banlvzw伴侣中文网等:
                            # 字母数字书ID + index_分页目录)
                            alt_match = re.search(r'/([a-z0-9]{2,12})/index(?:_\d+)?\.html?', catalog_url)
                            if alt_match:
                                novel_path = f"/{alt_match.group(1)}/"
                                print(f"[路径提取] 模式5: 从URL提取小说路径 {novel_path}")

            novel_path_alt = novel_path  # 对于其他网站，两种路径格式相同
        
        print(f"当前小说路径: {novel_path}")
        print(f"章节排序选项: {'启用' if sort_chapters else '禁用'}")
        
        # 5hbook.net: 专用章节提取 (路径 + 正则双重验证)
        if '5hbook.net' in catalog_url and not chapters:
            print("[5hbook.net] 使用专用章节提取逻辑")
            book_id_match = re.search(r'/books/(\d+)', catalog_url)
            book_id = book_id_match.group(1) if book_id_match else ''
            if book_id:
                chapter_pattern = re.compile(r'/books/' + book_id + r'/(\d+)\.html$')
                seen_ids = set()
                for a in soup.find_all('a', href=True):
                    href = a.get('href', '')
                    text = a.get_text(strip=True)
                    if not text or len(text) < 2:
                        continue
                    if 'javascript:' in href.lower():
                        continue
                    m = chapter_pattern.search(href)
                    if not m:
                        continue
                    chap_id = m.group(1)
                    if chap_id in seen_ids:
                        continue
                    # 过滤特殊非章节链接
                    if text in ('完本感言', '开始阅读'):
                        continue
                    if any(kw in text for kw in ['正序', '倒序', '切换']):
                        continue
                    seen_ids.add(chap_id)
                    url = href if href.startswith('http') else self.base_url + href
                    chapters.append({'title': self.clean_chapter_title(text), 'url': url})
                print(f"[5hbook.net] 专用提取: {len(chapters)} 个章节 (去重后)")
                if sort_chapters and chapters:
                    chapters.sort(key=_chapter_sort_key)
                    print("[5hbook.net] 已按章节号排序")
                for i, chap in enumerate(chapters[:5]):
                    print(f"  {i+1}. {chap['title']} -> {chap['url']}")
                if len(chapters) > 5:
                    print(f"  ... 共 {len(chapters)} 章")
                return chapters

        # exotxt.net: 专用章节提取 (.yanqing_list ul 结构)
        if 'exotxt.net' in catalog_url and not chapters:
            print("[exotxt.net] 使用专用章节提取逻辑")
            book_id_match = re.search(r'/infos/(\d+)', catalog_url)
            book_id = book_id_match.group(1) if book_id_match else ''
            if book_id:
                seen_ids = set()
                # 优先从 .yanqing_list 提取
                yanqing_list = soup.select('.yanqing_list')
                for ul in yanqing_list:
                    for a in ul.find_all('a', href=True):
                        href = a.get('href', '')
                        text = a.get_text(strip=True)
                        if not text or len(text) < 2:
                            continue
                        if 'javascript:' in href.lower():
                            continue
                        m = re.search(r'/infos/' + book_id + r'/(\d+)\.html', href)
                        if not m:
                            continue
                        chap_id = m.group(1)
                        if chap_id in seen_ids:
                            continue
                        if text in ('完本感言', '开始阅读'):
                            continue
                        if any(kw in text for kw in ['正序', '倒序', '切换', '立即阅读']):
                            continue
                        seen_ids.add(chap_id)
                        url = href if href.startswith('http') else self.base_url + href
                        chapters.append({'title': self.clean_chapter_title(text), 'url': url})
                # 备用: 从全页提取
                if not chapters:
                    for a in soup.find_all('a', href=True):
                        href = a.get('href', '')
                        text = a.get_text(strip=True)
                        if not text or len(text) < 2:
                            continue
                        if 'javascript:' in href.lower():
                            continue
                        m = re.search(r'/infos/' + book_id + r'/(\d+)\.html', href)
                        if not m:
                            continue
                        chap_id = m.group(1)
                        if chap_id in seen_ids:
                            continue
                        if any(kw in text for kw in ['正序', '倒序', '切换', '立即阅读', '加入书架']):
                            continue
                        seen_ids.add(chap_id)
                        url = href if href.startswith('http') else self.base_url + href
                        chapters.append({'title': self.clean_chapter_title(text), 'url': url})
                print(f"[exotxt.net] 专用提取: {len(chapters)} 个章节 (去重后)")
                if sort_chapters and chapters:
                    chapters.sort(key=_chapter_sort_key)
                    print("[exotxt.net] 已按章节号排序")
                for i, chap in enumerate(chapters[:5]):
                    print(f"  {i+1}. {chap['title']} -> {chap['url']}")
                if len(chapters) > 5:
                    print(f"  ... 共 {len(chapters)} 章")
                return chapters

        # 首先检查是否有章节目录链接
        catalog_link = None
        # 对于ahxsw.com网站，构建章节目录URL并跳转
        if 'ahxsw.com' in catalog_url:
            print("ahxsw.com网站，跳转到章节目录页面提取完整章节列表")
            # 从/book/143259/构建/mulu/143/143259/1.html
            book_id_match = re.search(r'/book/(\d+)/', catalog_url)
            if book_id_match:
                book_id = book_id_match.group(1)
                # ahxsw.com的mulu URL格式: /mulu/{前3位数字}/{完整ID}/1.html
                mulu_url = f"{self.base_url}/mulu/{book_id[:3]}/{book_id}/1.html"
                print(f"构建章节目录URL: {mulu_url}")
                catalog_soup = self.inspect_page(mulu_url)
                if catalog_soup and catalog_soup.find('a', href=True):
                    soup = catalog_soup
                    catalog_link = mulu_url
                    print(f"成功访问章节目录页面")
                else:
                    print("章节目录页面访问失败，尝试从当前页面提取")
            else:
                print("无法从URL提取小说ID，尝试从当前页面提取")
        else:
            # 查找章节目录链接（验证链接URL包含小说ID，避免匹配到推荐链接）
            # 从catalog_url提取小说ID用于验证
            novel_id_match = re.search(r'/(\d{4,})', catalog_url)
            novel_id = novel_id_match.group(1) if novel_id_match else ''

            catalog_texts = ['章节目录', '全部章节', '章节列表', '目录']
            for text in catalog_texts:
                links = soup.find_all('a', string=lambda s: s and text in s)
                for link in links:
                    href = link.get('href', '')
                    # 验证链接URL包含小说ID（避免匹配到推荐其他小说的链接）
                    if novel_id and novel_id in href:
                        catalog_link = href
                        print(f"找到章节目录链接: {catalog_link} (验证小说ID: {novel_id})")
                        break
                    # 如果无法验证小说ID，且链接文本精确匹配（不是推荐链接）
                    elif not novel_id and link.get_text().strip() == text:
                        catalog_link = href
                        print(f"找到章节目录链接: {catalog_link}")
                        break
                if catalog_link:
                    break

            # 如果找到章节目录链接，访问该链接获取章节列表
            if catalog_link:
                if not catalog_link.startswith('http'):
                    catalog_link = self.base_url + catalog_link
                print(f"访问章节目录页面: {catalog_link}")
                catalog_soup = self.inspect_page(catalog_link)
                soup = catalog_soup
        
        # 处理分页（特别针对322zw.com等有分页的网站）
        # 对于ahxsw.com网站，使用/mulu/分页URL格式
        if 'ahxsw.com' in catalog_url and catalog_link:
            print(f"\n[分页检测] ahxsw.com网站，使用/mulu/分页URL格式")
            print(f"[分页检测] 起始目录页: {catalog_link}")
            page_urls = [catalog_link]
            # ahxsw.com的mulu分页格式: /mulu/{前3位}/{完整ID}/{页码}.html
            # 尝试获取后续分页页面（最多10页）
            book_id_match = re.search(r'/mulu/\d+/(\d+)/', catalog_link)
            if book_id_match:
                book_id = book_id_match.group(1)
                prefix = book_id[:3]
                print(f"[分页检测] 提取小说ID: {book_id}, 前缀: {prefix}")

                # 先收集第一页的章节URL，用于后续比较
                first_page_links = set()
                try:
                    first_soup = self.inspect_page(catalog_link)
                    first_links = first_soup.select('#list a, dd a[href*="/read/"]')
                    for a in first_links:
                        href = a.get('href', '')
                        if '/read/' in href and href.endswith('.html'):
                            first_page_links.add(href)
                    print(f"[分页检测] 第1页章节链接集合 ({len(first_page_links)}个):")
                    for link in first_page_links:
                        print(f"[分页检测]   - {link}")
                except Exception as e:
                    print(f"[分页检测] 第1页章节链接收集失败: {e}")

                for page_num in range(2, 11):
                    mulu_page_url = f"{self.base_url}/mulu/{prefix}/{book_id}/{page_num}.html"
                    print(f"\n[分页检测] 检查分页 {page_num}: {mulu_page_url}")
                    try:
                        check_soup = self.inspect_page(mulu_page_url)
                        check_links = check_soup.select('#list a, dd a[href*="/read/"]')
                        read_links = [a for a in check_links if '/read/' in a.get('href', '') and a.get('href', '').endswith('.html')]
                        print(f"[分页检测] 分页{page_num}: 找到 {len(read_links)} 个章节链接")

                        if read_links:
                            # 检查新页面的章节URL是否与第一页相同
                            new_page_links = set(a.get('href') for a in read_links)
                            print(f"[分页检测] 分页{page_num} 链接集合 ({len(new_page_links)}个):")
                            for link in new_page_links:
                                print(f"[分页检测]   - {link}")

                            if new_page_links == first_page_links:
                                print(f"[分页检测] ⚠️ 分页{page_num} 章节链接与第一页完全相同，停止查找")
                                break
                            # 检查部分重叠
                            overlap = new_page_links & first_page_links
                            if overlap:
                                print(f"[分页检测] ⚠️ 分页{page_num} 与第一页有 {len(overlap)} 个重叠链接")

                            print(f"[分页检测] ✅ 找到分页页面 {page_num}: {mulu_page_url} ({len(read_links)}个章节)")
                            page_urls.append(mulu_page_url)
                        else:
                            print(f"[分页检测] 分页{page_num} 无章节内容，停止查找")
                            break
                    except Exception as e:
                        print(f"[分页检测] 分页{page_num} 访问失败: {e}，停止查找")
                        break
                print(f"[分页检测] 共找到 {len(page_urls)} 个分页页面")
        else:
            page_urls = [catalog_url]

            # 查找分页链接 (仅识别明确的"下一页"文本; "下章/下一章节"指向下一章, 会误判分页)
            next_page_texts = ['下一页', '下一頁', '下一页>>', '>>']
            next_page_link = None
            for text in next_page_texts:
                next_page_link = soup.find('a', string=lambda s: s and text in s)
                if next_page_link:
                    break

            if next_page_link:
                next_page_url = next_page_link.get('href')
                if not next_page_url.startswith('http'):
                    next_page_url = self.base_url + next_page_url
                page_urls.append(next_page_url)

                # 继续查找下一页，最多查找30页 (长篇小说目录可能分页较多)
                for _ in range(29):
                    try:
                        next_soup = self.inspect_page(next_page_url)
                        next_page_link = None
                        for text in next_page_texts:
                            next_page_link = next_soup.find('a', string=lambda s: s and text in s)
                            if next_page_link:
                                break
                        if not next_page_link:
                            break
                        next_page_url = next_page_link.get('href')
                        if not next_page_url.startswith('http'):
                            next_page_url = self.base_url + next_page_url
                        if next_page_url not in page_urls:
                            page_urls.append(next_page_url)
                        else:
                            break
                    except:
                        break

        print(f"找到 {len(page_urls)} 个分页页面")
        
        # 遍历所有分页页面
        for page_url in page_urls:
            print(f"处理分页页面: {page_url}")
            page_soup = self.inspect_page(page_url)

            # 尝试不同的常见章节列表选择器
            chapter_selectors = [
                '.chapterlist a',  # 常见的章节列表类名
                '.list_chapter a',  # 另一种常见的章节列表类名
                '#chapterlist a',  # 可能的ID选择器
                '.zhangjie a',  # 章节的中文类名
                'ul.chapter a',  # 无序列表形式的章节
                'ol.chapter a',  # 有序列表形式的章节
                'div[id*="chapter"] a',  # 包含chapter的ID
                'dl a',  # dl/dd 章节列表结构 (3gxs/笔趣阁风格), 需在 chapter 容器之前
                'div[class*="chapter"] a',  # 包含chapter的class
                'dd a',  # 常见的章节列表结构
                'li a[href*="/chapter/"]',  # 包含chapter的链接
                'li a[href*="/xs/"]',  # 包含xs的链接
                '.list a',  # 列表链接
                '.chapter a',  # 章节链接
                'ul.list a',  # 无序列表链接
                'ol.list a',  # 有序列表链接
                'div.list a',  # 列表div中的链接
                'div.chapterlist a',  # 章节列表div中的链接
                'table.chapter a',  # 表格形式的章节
                'tr a[href*="/chapter/"]',  # 表格行中的章节链接
                'li a[href*="/book/"]',  # 包含book的链接
                'a[href*="/book/"][href*="/"]',  # 包含book和数字的链接
                'div.ml a',  # 目录页面的链接
                '.ml a',  # 目录页面的链接
                'ul.ml a',  # 目录页面的无序列表链接
                'ol.ml a',  # 目录页面的有序列表链接
                'div[id*="ml"] a',  # 包含ml的ID
                'div[class*="ml"] a',  # 包含ml的class
                # 新增移动端网站常用选择器
                '.chapter-list a',  # 章节列表
                '.chapter-item a',  # 章节项
                '.chapter-title a',  # 章节标题
                '.chapter-link a',  # 章节链接
                '.list-chapter a',  # 列表章节
                '.list-item a',  # 列表项
                '.list-title a',  # 列表标题
                '.list-link a',  # 列表链接
                '.content-list a',  # 内容列表
                # 新增ahxsw.com网站选择器
                '#list a',  # ahxsw.com的章节列表
                '#chapterlist a',  # 可能的章节列表ID
                'div.list a[href*="/read/"]',  # ahxsw.com的读取链接
                '.content-item a',  # 内容项
                '.content-title a',  # 内容标题
                '.content-link a',  # 内容链接
                'ul.chapter-list a',  # 无序列表章节列表
                'ol.chapter-list a',  # 有序列表章节列表
                'ul.list-chapter a',  # 无序列表列表章节
                'ol.list-chapter a',  # 有序列表列表章节
                'div.chapter-list a',  # div章节列表
                'div.list-chapter a',  # div列表章节
                'div.content-list a',  # div内容列表
                'li a[href*="/chapter"]',  # 包含chapter的链接
                'li a[href*="/xiaoshuo/"]',  # 包含xiaoshuo的链接
                'a[href*="/chapter"]',  # 包含chapter的链接
                'a[href*="/xiaoshuo/"]',  # 包含xiaoshuo的链接
                # 新增pjxdd.com网站可能的选择器
                'a[href*="/chapter/"]',  # 包含chapter的链接
            ]
            
            found_chapters = False
            # 尝试使用更简单的选择器
            simple_selectors = ['a', 'a[href]', 'div a', 'span a', 'li a', 'ul a', 'ol a']
            
            # 对于ahxsw.com网站，优先使用#list a选择器
            if 'ahxsw.com' in catalog_url and not found_chapters:
                ahxsw_selectors = ['#list a', 'dd a[href*="/read/"]', 'dd a', 'li a[href*="/read/"]']
                for selector in ahxsw_selectors:
                    links = page_soup.select(selector)
                    if links:
                        relevant_links = []
                        for link in links:
                            href = link.get('href', '')
                            if '/read/' in href and href.endswith('.html') and link.get_text().strip():
                                relevant_links.append(link)
                        
                        if relevant_links:
                            print(f"ahxsw.com: 找到章节列表，使用选择器: {selector}")
                            for link in relevant_links:
                                title = link.get_text().strip()
                                url = link.get('href')
                                if not url:  # 无 href 的 <a> 标签, 跳过
                                    continue
                                if not url.startswith('http'):
                                    url = self.base_url + url
                                if len(title) > 1:
                                    chapters.append({'title': title, 'url': url})
                            found_chapters = True
                            break
            
            # 先尝试使用复杂的选择器
            for selector in chapter_selectors:
                links = page_soup.select(selector)
                if links:
                    # 检查前几个链接是否包含当前小说的路径
                    relevant_links = []
                    for link in links:
                        href = link.get('href', '')
                        # 对于hatxt.cc网站，同时检查两种路径格式
                        if 'hatxt.cc' in catalog_url:
                            if novel_path in href or novel_path_alt in href:
                                relevant_links.append(link)
                        elif 'pjxdd.com' in catalog_url:
                            # 对于pjxdd.com网站，检查是否包含小说路径或章节路径
                            if novel_path in href and href.endswith('.html') and link.get_text().strip():
                                relevant_links.append(link)
                        elif 'ahxsw.com' in catalog_url:
                            # 对于ahxsw.com网站，检查是否包含/read/路径
                            if '/read/' in href and href.endswith('.html') and link.get_text().strip():
                                relevant_links.append(link)
                        else:
                            # novel_path 为空时 (路径提取失败) 不启用路径过滤,
                            # 避免 '' in href 恒为 True 导致全页链接都被当章节
                            if novel_path and novel_path in href:
                                relevant_links.append(link)
                    
                    if relevant_links:
                        print(f"找到章节列表，使用选择器: {selector}")
                        # 抓取所有章节
                        for link in relevant_links:
                            title = link.get_text().strip()
                            url = link.get('href')
                            if not url:  # 无 href 的 <a> 标签, 跳过
                                continue
                            # 如果是相对路径，添加基础URL
                            if not url.startswith('http'):
                                url = self.base_url + url
                            # 过滤掉太短的文本
                            if len(title) > 1:
                                # 过滤掉非章节链接（如排序链接）
                                if '正序' not in title and '倒序' not in title and '切换' not in title:
                                    chapters.append({'title': title, 'url': url})
                        found_chapters = True
                        break
            
            # 如果没有找到，尝试使用简单的选择器
            if not found_chapters:
                print("尝试使用简单的选择器")
                for selector in simple_selectors:
                    links = page_soup.select(selector)
                    if links:
                        # 检查前几个链接是否包含当前小说的路径
                        relevant_links = []
                        for link in links:
                            href = link.get('href', '')
                            # 对于pjxdd.com网站，检查是否包含小说路径或章节路径
                            if 'pjxdd.com' in catalog_url:
                                if novel_path in href or '/chapter/' in href:
                                    relevant_links.append(link)
                            else:
                                if novel_path in href:
                                    relevant_links.append(link)
                        
                        if relevant_links:
                            print(f"找到章节列表，使用简单选择器: {selector}")
                            # 抓取所有章节
                            for link in relevant_links:
                                title = link.get_text().strip()
                                url = link.get('href')
                                if not url:  # 无 href 的 <a> 标签 (锚点/脚本), 跳过
                                    continue
                                # 如果是相对路径，添加基础URL
                                if not url.startswith('http'):
                                    url = self.base_url + url
                                # 过滤掉太短的文本
                                if len(title) > 1:
                                    # 过滤掉非章节链接（如排序链接）
                                    if '正序' not in title and '倒序' not in title and '切换' not in title:
                                        chapters.append({'title': title, 'url': url})
                            found_chapters = True
                            break
            
            # 如果没有找到特定的章节列表，尝试通用的链接选择
            if not found_chapters:
                print("尝试通用的链接选择")
                # 查找所有链接
                all_links = page_soup.find_all('a', href=True)
                print(f"找到 {len(all_links)} 个链接")
                
                for i, link in enumerate(all_links):
                    href = link.get('href', '')
                    text = link.get_text().strip()
                    print(f"链接 {i+1}: {text} -> {href}")
                    
                    # 过滤掉太短的文本
                    if len(text) > 1:
                        # 对于pjxdd.com网站，使用更宽松的条件
                        if 'pjxdd.com' in catalog_url:
                            # 检查是否包含小说路径、章节路径或小说ID
                            if novel_path and novel_path in href and href.endswith('.html') and text:
                                # 过滤掉JavaScript代码
                                if 'javascript:' in href:
                                    continue
                                # 过滤掉可能的目录页和下载页
                                if any(keyword in href for keyword in ['/ch1.html', '/dx1.html', '/index.html', '/index_']):
                                    continue
                                # 过滤掉非章节链接（如排序链接）
                                if '正序' in text or '倒序' in text or '切换' in text or text == '开始阅读':
                                    continue
                                url = self.base_url + href if not href.startswith('http') else href
                                chapters.append({'title': text, 'url': url})
                                print(f"添加链接: {text} -> {url}")
                        else:
                            # 对于其他网站，使用原来的条件
                            path_match = False
                            if 'hatxt.cc' in catalog_url:
                                if (novel_path and novel_path in href) or \
                                   (novel_path_alt and novel_path_alt in href):
                                    path_match = True
                            else:
                                if novel_path and novel_path in href:
                                    path_match = True
                            
                            if path_match:
                                # 过滤掉JavaScript代码
                                if 'javascript:' in href:
                                    continue
                                # 过滤掉可能的目录页和下载页
                                if any(keyword in href for keyword in ['/ch1.html', '/dx1.html', '/index.html']):
                                    continue
                                # 过滤掉路径结尾的链接（可能是目录页）
                                if href.endswith(novel_path):
                                    continue
                                # 过滤掉非章节链接（如排序链接）
                                if '正序' in text or '倒序' in text or '切换' in text:
                                    continue
                                url = self.base_url + href if not href.startswith('http') else href
                                chapters.append({'title': text, 'url': url})
                
                # 对于pjxdd.com网站，尝试直接从文本中提取链接
                if 'pjxdd.com' in catalog_url and not chapters:
                    print("尝试直接从文本中提取链接")
                    # 获取原始文本
                    text = str(page_soup)
                    # 使用正则表达式提取链接
                    # 匹配http或https链接
                    http_links = re.findall(r'http[s]?://[^"\'>\s]+', text)
                    print(f"找到 {len(http_links)} 个http链接")
                    for link in http_links:
                        print(f"HTTP链接: {link}")
                        # 检查是否包含小说路径、章节路径或小说ID
                        if novel_path in link or '/chapter/' in link or 'chapter' in link.lower():
                            # 提取标题（使用链接的最后一部分作为标题）
                            title = link.split('/')[-1].replace('.html', '').replace('_', ' ')
                            chapters.append({'title': title, 'url': link})
                            print(f"添加HTTP链接: {title} -> {link}")
                    
                    # 匹配相对路径链接
                    relative_links = re.findall(r'href=["\']([^"\'>]+)["\']', text)
                    print(f"找到 {len(relative_links)} 个相对路径链接")
                    for link in relative_links:
                        print(f"相对路径链接: {link}")
                        # 检查是否包含小说路径、章节路径或小说ID
                        if novel_path in link or '/chapter/' in link or 'chapter' in link.lower():
                            # 构建完整URL
                            if not link.startswith('http'):
                                if link.startswith('/'):
                                    url = self.base_url + link
                                else:
                                    url = self.base_url + '/' + link
                            else:
                                url = link
                            # 提取标题（使用链接的最后一部分作为标题）
                            title = url.split('/')[-1].replace('.html', '').replace('_', ' ')
                            chapters.append({'title': title, 'url': url})
                            print(f"添加相对路径链接: {title} -> {url}")

        # 去重章节（基于URL），保持原始顺序
        print(f"\n[章节去重] 去重前共 {len(chapters)} 个章节")
        # 非章节导航链接(如"查看更多章节...")，需过滤掉
        nav_keywords = ['查看更多章节', '更多章节', '查看全部', '全部章节', '展开全部', '加载更多',
                        '上一页', '下一页', '上一章', '下一章', '返回书页', '返回目录',
                        '章节目录', '首页', '末页', '加入书架']
        unique_chapters = []
        seen_urls = set()
        duplicate_count = 0
        nav_filtered = 0
        for chap in chapters:
            title_stripped = chap['title'].strip()
            # 过滤导航类链接(标题完全匹配导航关键词，或以"查看更多"开头)
            if any(title_stripped == kw or title_stripped.startswith(kw) for kw in nav_keywords):
                nav_filtered += 1
                print(f"[章节过滤] 移除导航链接: '{title_stripped[:30]}' -> {chap['url']}")
                continue
            # 过滤目录/列表/首页链接 (URL 特征: list/mulu/catalog 页或站点根)
            if re.search(r'/(list|mulu|catalog|booklist)\d*\.html', chap['url']) or \
                    chap['url'].rstrip('/') == self.base_url.rstrip('/'):
                nav_filtered += 1
                print(f"[章节过滤] 移除目录页链接: '{title_stripped[:30]}' -> {chap['url']}")
                continue
            if chap['url'] not in seen_urls:
                seen_urls.add(chap['url'])
                # 清理章节标题
                original_title = chap['title']
                chap['title'] = self.clean_chapter_title(chap['title'])
                if original_title != chap['title']:
                    print(f"[标题清理] '{original_title[:30]}...' -> '{chap['title'][:30]}...'")
                unique_chapters.append(chap)
            else:
                duplicate_count += 1
        chapters = unique_chapters
        print(f"[章节去重] 去重后共 {len(chapters)} 个章节，移除 {duplicate_count} 个重复，过滤 {nav_filtered} 个导航链接")

        # 根据参数决定是否进行章节排序
        if sort_chapters:
            print("\n[章节排序] 启用章节排序")
            # 尝试按章节顺序排序
            def chapter_sort_key(chap):
                title = chap['title']
                # 提取章节号

                # 特殊处理楔子
                if '楔子' in title:
                    print(f"[排序键值] '{title[:30]}' -> 0 (楔子)")
                    return 0

                # 特殊处理"开始阅读"，视为第1章
                if '开始阅读' in title:
                    print(f"[排序键值] '{title[:30]}' -> 1 (开始阅读)")
                    return 1

                # 特殊处理番外
                if '番外' in title:
                    print(f"[排序键值] '{title[:30]}' -> 99999 (番外)")
                    return 99999

                # 中文数字映射
                chinese_nums = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}

                # 尝试多种章节号格式
                patterns = [
                    r'第(\d+)章',  # 第X章
                    r'第(\d+)节',  # 第X节
                    r'第(\d+)部分',  # 第X部分
                    r'第(\d+)回',    # 第X回
                    r'第(\d+)卷',    # 第X卷
                    r'第(\d+)话',  # 第X话
                    r'第([一二三四五六七八九十百千零]+)章',  # 第X章（中文数字）
                    r'第([一二三四五六七八九十百千零]+)节',  # 第X节（中文数字）
                    r'第([一二三四五六七八九十百千零]+)部分',  # 第X部分（中文数字）
                    r'第([一二三四五六七八九十百千零]+)话',  # 第X话（中文数字）
                    r'(\d+)章',    # X章
                    r'(\d+)节',    # X节
                    r'章节(\d+)',  # 章节X
                    r'(\d+)话',    # X话
                ]

                for i, pattern in enumerate(patterns):
                    match = re.search(pattern, title)
                    if match:
                        try:
                            num_str = match.group(1)
                            # 如果是纯数字
                            if num_str.isdigit():
                                key = int(num_str)
                                print(f"[排序键值] '{title[:30]}' -> {key} (模式{i+1}: 数字)")
                                return key
                            # 如果是中文数字
                            if num_str in chinese_nums:
                                key = chinese_nums[num_str]
                                print(f"[排序键值] '{title[:30]}' -> {key} (模式{i+1}: 中文数字)")
                                return key
                            # 尝试解析复杂中文数字（如二十三）
                            if '十' in num_str:
                                parts = num_str.split('十')
                                tens = chinese_nums.get(parts[0], 1) if parts[0] else 1
                                ones = chinese_nums.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
                                key = tens * 10 + ones
                                print(f"[排序键值] '{title[:30]}' -> {key} (模式{i+1}: 复杂中文数字)")
                                return key
                            print(f"[排序键值] '{title[:30]}' -> 9999 (模式{i+1}: 无法解析)")
                            return 9999
                        except:
                            pass

                # 尝试从URL中提取章节号
                url = chap['url']
                url_patterns = [
                    r'/book/\d+/([\d]+)\.html',
                    r'/books/\d+/([\d]+)\.html',  # baoshuism.com格式
                    r'/chapter/([\d]+)',
                    r'/xs/([\d]+)',
                    r'/\d+_\d+/([\d]+)\.html',  # 322zw.com格式
                    r'/read/\d+/\d+/([\d]+)\.html',  # ahxsw.com格式
                ]

                for i, pattern in enumerate(url_patterns):
                    match = re.search(pattern, url)
                    if match:
                        try:
                            key = int(match.group(1))
                            print(f"[排序键值] '{title[:30]}' -> {key} (URL模式{i+1})")
                            return key
                        except:
                            pass

                # 默认值
                print(f"[排序键值] '{title[:30]}' -> 9999 (默认值，无法提取)")
                return 9999

            # 记录排序前的顺序
            print("[章节排序] 排序前顺序:")
            for i, chap in enumerate(chapters):
                print(f"  {i+1}. {chap['title'][:40]}")

            chapters.sort(key=chapter_sort_key)

            print("[章节排序] 排序后顺序:")
            for i, chap in enumerate(chapters):
                print(f"  {i+1}. {chap['title'][:40]}")
        else:
            print("保持原目录顺序，不进行自动排序")

        print(f"\n共找到 {len(chapters)} 个章节（已去重并排序）")
        # 打印章节列表
        for i, chap in enumerate(chapters):
            print(f"  {i+1}. {chap['title']} -> {chap['url']}")

        return chapters

    def clean_chapter_title(self, title):
        """清理章节标题，移除无意义字符并截断过长的标题"""
        if not title:
            return title

        # 移除HTML实体和特殊字符
        title = title.replace('&ldquo;', '"').replace('&rdquo;', '"')
        title = title.replace('&hellip;', '…').replace('&mdash;', '—')
        title = title.replace('&ndash;', '–').replace('&nbsp;', ' ')
        title = title.replace('ldquo', '').replace('rdquo', '')
        title = title.replace('hellip', '…').replace('mdash', '—')
        title = title.replace('nbsp', ' ')

        # 移除控制字符和特殊符号
        title = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', title)
        title = re.sub(r'\s+', ' ', title).strip()

        # 如果标题过长（超过50个字符），尝试截断
        # 保留章节号前缀（如"第三章"），后面的内容截取合理长度
        if len(title) > 50:
            # 尝试匹配章节号前缀
            chapter_prefix_match = re.match(r'^(第[一二三四五六七八九十百千零\d]+[章节话回卷])\s*', title)
            if chapter_prefix_match:
                prefix = chapter_prefix_match.group(1)
                rest = title[len(prefix):].strip()
                # 截取前30个字符的描述部分
                if len(rest) > 30:
                    rest = rest[:30] + '…'
                title = f"{prefix} {rest}"
            else:
                # 没有章节号前缀，直接截断
                title = title[:50] + '…'

        return title.strip()

    def clean_content(self, content):
        """清理无意义字符和广告内容"""
        if not content:
            return ""

        # 移除零宽/不可见字符 (U+200B 零宽空格 / U+200C ZWNJ / U+200D ZWJ /
        # U+FEFF BOM / U+2060 Word Joiner / U+00AD 软连字符)
        # 部分网站会在正文中插入这些不可见字符用于反爬/水印, 通用清理适用于所有站点
        content = re.sub(r'[\u200b\u200c\u200d\ufeff\u2060\u00ad]', '', content)

        # 移除反爬干扰串: 部分站点 (如 oldtimeswx.net) 会在正文中随机插入
        # "字母+数字"混合短串作为水印 (如"给体0N肏烂了"中的"0N")。
        # 规则: 直接夹在两个汉字之间的 2-4 位"含数字且含字母"的混合串 → 删除。
        # 白名单保护正常词汇 (如 "5G时代"/"3D眼镜"); 纯字母串 (SPA/NBA/RBQ) 与
        # 纯数字串 (1999年) 天然不被匹配, 无需担心误删。
        _JUNK_WHITELIST = {'3d', '5g', '4g', '2g', '2k', '4k', '8k', '3s', 't恤'}
        content = re.sub(
            r'(?<=[\u4e00-\u9fff])([A-Za-z0-9]{2,4})(?=[\u4e00-\u9fff])',
            lambda m: m.group(0) if m.group(1).lower() in _JUNK_WHITELIST
            or m.group(1).isdigit() or m.group(1).isalpha() else '',
            content)

        # 修复HTML实体（Base64解码后可能残留的实体名称）
        html_entities = {
            'ldquo': '"', 'rdquo': '"', 'lsquo': "'", 'rsquo': "'",
            'hellip': '…', 'mdash': '—', 'ndash': '–', 'nbsp': ' ',
            'middot': '·', 'bull': '•', 'amp': '&', 'lt': '<', 'gt': '>',
        }
        for entity, char in html_entities.items():
            content = content.replace(f'&{entity};', char)
            content = content.replace(entity, char) if len(entity) > 3 else content

        # 使用模块级常量 (避免重复定义)
        filter_keywords = _CONTENT_FILTER_KEYWORDS
        
        # 修复常见编码错误字符（Base64解码后可能出现的乱码）
        encoding_fixes = {
            '口禽': '噙', '昏滚': '混蛋', '昏蛋': '混蛋',
            '王八旦': '王八蛋', '玉辟': '玉臂',
            '插人': '插入', '律劲': '律动',
            '巳经': '已经', '佷多': '很多',  # 形近字乱码 (爬虫常见)
        }
        for wrong, correct in encoding_fixes.items():
            content = content.replace(wrong, correct)

        # 移除页码标记, 如 （第1页）/(第2页), 防止混入正文
        content = re.sub(r'[（(]\s*第\d+页\s*[)）]', '', content)
        content = re.sub(r'^第\d+部分（第\d+页）', '', content)

        # 按行处理 (必须在上述修复之后拆分)
        lines = content.split('\n')
        filtered_lines = []

        for line in lines:
            stripped_line = line.strip()
            if not stripped_line:
                continue

            # 跳过包含过滤关键词的行
            if any(keyword in stripped_line for keyword in filter_keywords):
                continue

            # 跳过URL和邮箱
            if 'http://' in stripped_line or 'https://' in stripped_line or '@' in stripped_line:
                continue

            # 跳过过短的行（可能是导航或广告）
            if len(stripped_line) < 5:
                continue

            # 跳过主要是符号的行
            symbol_count = sum(1 for c in stripped_line if not c.isalnum() and not c.isspace() and not '\u4e00' <= c <= '\u9fff')
            if symbol_count > len(stripped_line) * 0.5:
                continue

            # 通用广告行特征检测 (基于内容特征, 不依赖具体书名/站点名)
            if _is_ad_line(stripped_line):
                continue

            filtered_lines.append(stripped_line)

        # 段落排版整理: 合并碎片化短行
        # 云趣阁/笔趣阁等站点的 <p> 标签可能因分段不一致产生短行,
        # 这些短行既非对话引语 (不以中文/英文引号开头) 也非独立段落,
        # 应合并到上一段, 使正文段落完整、连贯。
        merged_lines = []
        for line in filtered_lines:
            if not line:
                continue
            # 对话引语独立成段: 以 "「 或 " 或 ' 或 「 开头的短行保留独立
            is_dialogue = bool(re.match(r'^[“”"\']', line)) or line.startswith('「') or line.startswith('『')
            # 段落首行特征: 较长 (>=30字) 或是对话引语
            is_paragraph_start = (len(line) >= 30) or is_dialogue
            if merged_lines and not is_paragraph_start and len(line) < 25:
                # 短行 (非对话引语) 合并到上一段
                merged_lines[-1] = merged_lines[-1] + line
            else:
                merged_lines.append(line)

        # 合并过滤后的行
        cleaned_content = '\n\n'.join(merged_lines)

        # 移除多余的空行
        cleaned_content = re.sub(r'\n{3,}', '\n\n', cleaned_content)

        # 移除行首行尾的空白
        cleaned_content = '\n'.join([line.strip() for line in cleaned_content.split('\n') if line.strip()])

        # ===== 排版规范化 (对整章最终文本, 均不影响语义) =====
        # 1. 全角空格 → 空 (部分站点用全角空格做对齐水印)
        cleaned_content = cleaned_content.replace('\u3000', '')
        # 2. 行内连续空格压缩为单空格
        cleaned_content = re.sub(r' {2,}', ' ', cleaned_content)
        # 3. 逗号句号连排 ",。" / "，。" → "。" (站点拼接残渣)
        cleaned_content = re.sub(r'[，,]+[。.]', '。', cleaned_content)
        # 4. 重复标点压缩: 4 个以上连续感叹/问号/句号 → 保留 2 个 (保留强调语气, 去掉刷屏冗余)
        cleaned_content = re.sub(r'([！？。])\1{3,}', r'\1\1', cleaned_content)
        # 5. 段内行尾残留的章节号/页码 (如行尾 "第3页" 残留) 清理
        cleaned_content = re.sub(r'(?<=[\u4e00-\u9fff])第\d+页\s*$', '', cleaned_content, flags=re.M)

        return cleaned_content.strip()

    def _detect_content_pattern(self, url, headers):
        """通用内容模式自动检测 (基于页面内容特征, 不依赖域名)

        检测策略:
        1. 获取页面 HTML
        2. 检测 qsbs.bb Base64 加密特征
        3. 检测 AJAX 两步加载特征
        4. 检测 HTML 选择器能否提取到正文
        5. 都不匹配返回 None (回退到域名分支)

        Returns:
            'qsbs_bb' / 'ajax_two_step' / 'html_selector' / None
        """
        if hasattr(self, '_detected_pattern') and self._detected_pattern:
            return self._detected_pattern
        try:
            print(f"[通用检测] 开始检测内容模式: {url}")
            response = self._get_with_js_challenge(url, headers)
            response.encoding = response.apparent_encoding
            html = response.text
            print(f"[通用检测] 页面获取成功, 状态码={response.status_code}, HTML长度={len(html)} 字符")
            # 1. qsbs.bb Base64 加密
            qsbs_blocks = re.findall(r"qsbs\.bb\('([A-Za-z0-9+/=]+)'\)", html)
            if qsbs_blocks:
                print(f"[通用检测] ✅ 识别到 qsbs.bb Base64 加密, 共 {len(qsbs_blocks)} 个加密块")
                return 'qsbs_bb'
            # 1b. str_decode Base64 加密 (5hbook.net 等)
            str_decode_blocks = re.findall(r'str_decode\("([^"]+)"\)', html)
            if str_decode_blocks:
                print(f"[通用检测] ✅ 识别到 str_decode Base64 加密, 共 {len(str_decode_blocks)} 个加密块")
                return 'str_decode_bb'
            # 1c. document.writeln(obj.func('BASE64')) 加密 (3gxs 的 racgr.tggjzdv 等)
            writeln_blocks = re.findall(r"document\.writeln\(\s*[A-Za-z_]\w*\.[A-Za-z_]\w*\s*\(\s*'([A-Za-z0-9+/=]{20,})'\s*\)\s*\)", html)
            if writeln_blocks:
                print(f"[通用检测] ✅ 识别到 writeln Base64 加密, 共 {len(writeln_blocks)} 个加密块")
                return 'qsbs_bb'
            # 2. AJAX 两步加载
            if re.search(r'/api/read_sign\.php', html):
                print(f"[通用检测] ✅ 识别到 AJAX 两步加载特征 (/api/read_sign.php)")
                return 'ajax_two_step'
            # 3. HTML 选择器 (尝试常见容器能否提取到足够文本)
            soup = BeautifulSoup(html, 'lxml')
            selectors = ['div.content', 'div.word_read', 'div.info_dv1.ov', 'div#txt',
                        '#content', '.content', '#nr1', '#bookcontent', '#chaptercontent',
                        'div.chapter-content', 'div#chapter-content', 'div.read-content', 'div.txt',
                        'div.bookContent', 'div.readContent', 'div.text']
            for sel in selectors:
                el = soup.select_one(sel)
                if el:
                    text_len = len(el.get_text(strip=True))
                    if text_len > 200:
                        print(f"[通用检测] ✅ 选择器 '{sel}' 命中正文 ({text_len} 字符 > 200)")
                        return 'html_selector'
                    else:
                        print(f"[通用检测] 选择器 '{sel}' 命中但内容过短 ({text_len} 字符 < 200), 跳过")
            print(f"[通用检测] ⚠️ 未识别到任何已知内容模式, 将回退到域名分支")
            return None
        except Exception as e:
            print(f"[通用检测] ❌ 检测失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _extract_base64_blocks(self, url, headers, pattern, tag='base64'):
        """通用 Base64 加密块解码提取 (不依赖域名)

        适用于所有使用 Base64 加密正文的站点。
        解码每个 Base64 块为 <p> 段落, 用 _is_ad_line() 通用过滤广告行。

        Args:
            url: 章节页 URL
            headers: 请求头
            pattern: Base64 块的正则表达式 (含一个捕获组)
            tag: 日志标签 (如 'qsbs' / 'str_decode')
        """
        try:
            response = self._get_with_js_challenge(url, headers)
            response.encoding = response.apparent_encoding
            html = response.text
            blocks = re.findall(pattern, html)
            # qsbs.bb 额外尝试 writeln 变体
            if not blocks and tag == 'qsbs':
                blocks = re.findall(
                    r"document\.writeln\(\s*[A-Za-z_]\w*\.[A-Za-z_]\w*\s*\(\s*'([A-Za-z0-9+/=]{20,})'\s*\)\s*\)",
                    html)
                if blocks:
                    print(f"[通用提取-{tag}] 使用通用 writeln 加密模式, 找到 {len(blocks)} 个加密块")
            if not blocks:
                print(f"[通用提取-{tag}] ⚠️ 未找到加密块")
                return ''
            print(f"[通用提取-{tag}] 找到 {len(blocks)} 个 Base64 块, 开始解码...")
            parts = []
            decoded_count = 0
            filtered_count = 0
            for i, b in enumerate(blocks):
                try:
                    decoded_bytes = base64.b64decode(b)
                    decoded_text = None
                    for enc in ['utf-8', 'gbk', 'gb2312', 'gb18030']:
                        try:
                            decoded_text = decoded_bytes.decode(enc)
                            if '<p>' in decoded_text or len(decoded_text) > 20:
                                break
                        except Exception:
                            continue
                    if not decoded_text or '<p>' not in decoded_text:
                        print(f"[通用提取-{tag}] 块{i+1}: 解码后无<p>标签, 跳过")
                        continue
                    p_soup = BeautifulSoup(decoded_text, 'lxml')
                    text = p_soup.get_text(separator='\n', strip=True)
                    if not text:
                        continue
                    if _is_ad_line(text):
                        filtered_count += 1
                        print(f"[通用提取-{tag}] 块{i+1}: 广告行过滤 ({len(text)} 字符)")
                        continue
                    decoded_count += 1
                    parts.append(text)
                except Exception as e:
                    print(f"[通用提取-{tag}] 块{i+1}: 解码失败 - {e}")
            result = '\n\n'.join(parts)
            print(f"[通用提取-{tag}] 解码完成: {decoded_count} 有效块, 过滤 {filtered_count} 广告行, 提取 {len(result)} 字符")
            return result
        except Exception as e:
            print(f"[通用提取-{tag}] ❌ 解码失败: {e}")
            return ''

    def _extract_qsbs_bb_generic(self, url, headers):
        """通用 qsbs.bb Base64 解码提取 (不依赖域名)

        适用于所有使用 qsbs.bb() 加密的站点 (zhiruo/biquwx/ahxsw/28zw/spscl 等)。
        复用 _extract_base64_blocks 通用解码逻辑。
        """
        return self._extract_base64_blocks(url, headers,
            pattern=r"qsbs\.bb\('([A-Za-z0-9+/=]+)'\)", tag='qsbs')

    def _extract_str_decode_generic(self, url, headers):
        """通用 str_decode Base64 解码提取 (不依赖域名)

        适用于所有使用 str_decode("...") 加密的站点 (5hbook.net 等)。
        复用 _extract_base64_blocks 通用解码逻辑。
        """
        return self._extract_base64_blocks(url, headers,
            pattern=r'str_decode\("([^"]+)"\)', tag='str_decode')

    def _extract_html_selector_generic(self, url, headers):
        """通用 HTML 选择器提取 (不依赖域名)

        适用于所有正文直接内嵌 HTML 的站点。
        依次尝试常见正文容器, 用 _is_ad_line() 逐行过滤广告。
        """
        try:
            # 内部函数: 用给定 headers 提取一次, 返回 (最佳文本, 选择器名)
            def _try_extract(hdrs):
                response = self._get_with_js_challenge(url, hdrs)
                response.encoding = response.apparent_encoding
                html = response.text
                soup = BeautifulSoup(html, 'lxml')
                # 遍历所有选择器, 取提取文本最长的结果 (不依赖具体域名, 自动选最优容器)
                selectors = [
                    'div.info_dv1.ov', 'div.content', 'div.word_read', 'div#txt',
                    '#content', '.content', '#nr1', '#bookcontent', '#chaptercontent',
                    'div.chapter-content', 'div#chapter-content', 'div.read-content', 'div.txt',
                    'div.bookContent', 'div.readContent', 'div.text',
                ]
                best_t = ''
                best_s = ''
                for sel in selectors:
                    el = soup.select_one(sel)
                    if not el:
                        continue
                    ps = el.find_all('p')
                    if ps:
                        parts = []
                        filtered = 0
                        for p in ps:
                            txt = p.get_text(strip=True)
                            if not txt:
                                continue
                            if _is_ad_line(txt):
                                filtered += 1
                                continue
                            parts.append(txt)
                        if parts:
                            text = '\n\n'.join(parts)
                            if len(text) > len(best_t):
                                print(f"[通用提取-html] 选择器 '{sel}': {len(ps)} 个<p>, 过滤 {filtered}, {len(text)} 字符 — 当前最佳")
                                best_t = text
                                best_s = sel
                            continue
                    text = el.get_text('\n', strip=True)
                    if len(text) > 100:
                        lines = [l for l in text.split('\n') if l.strip() and not _is_ad_line(l.strip())]
                        if lines:
                            joined = '\n'.join(lines)
                            if len(joined) > len(best_t):
                                print(f"[通用提取-html] 选择器 '{sel}'(纯文本): {len(text)} 字符, 过滤后 {len(lines)} 行 — 当前最佳")
                                best_t = joined
                                best_s = sel
                return best_t, best_s

            # 第一次: 用原始 headers 提取
            best_text, best_sel = _try_extract(headers)
            if best_text:
                print(f"[通用提取-html] 首次提取: '{best_sel}' → {len(best_text)} 字符")
            # 内容过短时用 PC UA 重试 (部分网站如 yqyp.net 随机 UA 返回移动版, 内容缺失)
            if len(best_text) < 500:
                print(f"[通用提取-html] 内容过短 ({len(best_text)} 字符), 用 PC UA 重试...")
                pc_headers = dict(headers)
                pc_headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                text2, sel2 = _try_extract(pc_headers)
                if len(text2) > len(best_text):
                    print(f"[通用提取-html] PC UA 重试改善: '{sel2}' → {len(text2)} 字符 (原 {len(best_text)} 字符)")
                    best_text, best_sel = text2, sel2
            if best_text:
                print(f"[通用提取-html] ✅ 最终选用 '{best_sel}', 提取 {len(best_text)} 字符")
                return best_text
            print(f"[通用提取-html] ⚠️ 所有选择器均未命中正文")
            return ''
        except Exception as e:
            print(f"[通用提取-html] ❌ HTML 选择器提取失败: {e}")
            return ''

    def _extract_ajax_two_step_generic(self, url, headers):
        """通用 AJAX 两步加载提取 (不依赖域名)

        适用于所有使用 /api/read_sign.php 两步 AJAX 加载的站点 (如 11bzw.org)。
        自动从 URL 或页面 HTML 中提取 aid/cid 和 page_path, 执行两步 AJAX 获取正文:
          步骤1: GET /api/read_sign.php?aid=X&cid=Y 获取 {sign, bk}
          步骤2: GET {page_path}?ajax=1&aid=X&cid=Y&bk=Z&sign=S 获取正文
        解码后用 _is_ad_line() 逐行过滤广告/导航行, 不依赖具体域名。
        """
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path = parsed.path

            # 1. 从 URL 提取 aid/cid 和 page_path
            #    通用格式: /{prefix}/{aid}/{cid}(_{N})?.html (如 /read/46358/9218488_2.html)
            m_url = re.search(r'/(\w+)/(\d+)/(\d+)(_\d+)?\.html', path)
            aid = cid_base = cid_full = page_path = None
            if m_url:
                prefix = m_url.group(1)
                aid = m_url.group(2)
                cid_base = m_url.group(3)
                cid_full = m_url.group(3) + (m_url.group(4) or '')
                page_path = f"/{prefix}/{aid}/{cid_full}.html"

            # 2. 访问章节页确保拿到 cookie (PHPSESSID/SSRID) + 处理 JS cookie 校验反爬
            resp = self._get_with_js_challenge(url, headers)
            html = resp.text if resp is not None else ''

            # 3. 如果 URL 提取失败, 从页面 HTML 中的 read_sign.php 引用提取 aid/cid
            if not aid or not cid_base:
                m_html = re.search(r"/api/read_sign\.php\?aid=(\d+)&cid=(\d+)", html)
                if m_html:
                    aid = m_html.group(1)
                    cid_base = m_html.group(2)
                    cid_full = cid_base
                    page_path = path  # 用 URL 的 path 作为 page_path

            if not aid or not cid_base or not page_path:
                print(f"[通用提取-ajax] ❌ 无法从 URL/HTML 提取 aid/cid: {url}")
                return ''
            print(f"[通用提取-ajax] 提取参数: aid={aid}, cid={cid_full}, page_path={page_path}")

            # 4. 取签名 (用基础 cid, sign 对所有分页通用)
            ts = int(time.time() * 1000)
            ajax_headers = {
                'Referer': f"{self.base_url}{page_path}",
                'X-Requested-With': 'XMLHttpRequest',
            }
            sign_url = f"{self.base_url}/api/read_sign.php?aid={aid}&cid={cid_base}&_={ts}"
            validate_public_url(sign_url)  # 安全校验
            sign_resp = self.session.get(sign_url, headers={**headers, **ajax_headers}, timeout=20)
            sign_data = sign_resp.json()
            if sign_data.get('code') != 0:
                print(f"[通用提取-ajax] ❌ 签名失败: {sign_data}")
                return ''
            bk = sign_data['bk']
            sign = sign_data['sign']
            print(f"[通用提取-ajax] 签名成功: bk={str(bk)[:16]}..., sign={str(sign)[:16]}...")

            # 5. 取正文
            ts2 = int(time.time() * 1000)
            content_url = f"{self.base_url}{page_path}?ajax=1&aid={aid}&cid={cid_full}&bk={bk}&sign={sign}&_={ts2}"
            validate_public_url(content_url)  # 安全校验
            content_resp = self.session.get(content_url, headers={**headers, **ajax_headers}, timeout=20)
            content_html = content_resp.text
            print(f"[通用提取-ajax] 正文获取成功, HTML长度={len(content_html)} 字符")
            if not content_html.strip():
                print(f"[通用提取-ajax] ⚠️ 正文为空")
                return ''

            # 6. 解析正文 HTML, 逐行过滤广告/导航行 (基于内容特征, 不依赖域名)
            csoup = BeautifulSoup(content_html, 'lxml')
            # 优先按 <p> 提取并过滤
            ps = csoup.find_all('p')
            if ps:
                parts = []
                filtered = 0
                for p in ps:
                    txt = p.get_text(strip=True)
                    if not txt:
                        continue
                    if _is_ad_line(txt):
                        filtered += 1
                        continue
                    parts.append(txt)
                if parts:
                    print(f"[通用提取-ajax] <p>提取: {len(ps)} 个<p>, 过滤 {filtered} 广告行, 提取 {len(parts)} 段")
                    return '\n\n'.join(parts)
            # 无 <p> 时直接取文本并逐行过滤
            text = csoup.get_text('\n', strip=True)
            lines = [l for l in text.split('\n') if l.strip() and not _is_ad_line(l.strip())]
            print(f"[通用提取-ajax] 纯文本提取: {len(text)} 字符, 过滤后 {len(lines)} 行")
            return '\n'.join(lines)
        except Exception as e:
            print(f"[通用提取-ajax] ❌ AJAX 两步加载失败: {e}")
            return ''

    def deduplicate_paragraphs(self, content):
        """整章段落级去重

        云趣阁 (28zw.org/spscl.com) 等站点的分页机制会在每页开头重复前页内容,
        导致合并后的章节内出现大段重复段落。本方法按段落指纹 (前60字) 去重,
        保留首次出现的段落, 删除后续重复, 同时保留短段落 (对话引语等) 不参与去重。

        注意: clean_content 后段落间是单换行 \\n, 多页合并处是 \\n\\n,
        所以按 \\n 分割段落, 同时保留空行分隔结构。

        Args:
            content: 整章正文 (多页合并后)

        Returns:
            去重后的正文
        """
        if not content:
            return content
        # 按换行分割成段落 (clean_content 后每行是一个段落)
        paragraphs = content.split('\n')
        seen_fingerprints = set()
        result = []
        removed = 0
        for para in paragraphs:
            para = para.strip()
            if not para:
                # 保留空行 (段落间的分隔)
                if result and result[-1] != '':
                    result.append('')
                continue
            # 短段落 (<60字) 不参与去重, 保留对话引语、短句等
            if len(para) < 60:
                result.append(para)
                continue
            # 用前60字作为指纹 (跨页重复段落通常开头完全相同)
            fingerprint = para[:60]
            if fingerprint in seen_fingerprints:
                removed += 1
                continue
            seen_fingerprints.add(fingerprint)
            result.append(para)
        # 清理尾部空行
        while result and result[-1] == '':
            result.pop()
        if removed > 0:
            print(f"[段落去重] 移除 {removed} 个重复段落, 保留 {len([r for r in result if r])} 段")
        return '\n'.join(result)

    def get_chapter_content(self, chapter_url, max_pages=None):
        """
        抓取单章正文，自动处理分页、合并、清洗、去重。

        执行流程（通用分发层优先，域名分支兜底）：
            1. 查 sites_config 匹配站点预设模式；或进入通用检测
            2. 第 1 页调用 `_detect_content_pattern` 识别三种模式：
               qsbs_bb / ajax_two_step / html_selector，并缓存到 self._detected_pattern
            3. 根据识别结果调用通用提取方法；通用层为空时回退到三处「向后兼容备用分支」
            4. 逐页循环：根据模式生成分页 URL，命中相同指纹即停止（防止重复/死循环）
            5. 合并所有页 → clean_content 通用清洗 → deduplicate_paragraphs 段落去重

        Args:
            chapter_url: 第 1 页 URL
            max_pages: 最大分页上限（None 时根据站点配置默认，最多 30 页）；
                       通常用于 --test 模式限制为 2 页

        Returns:
            str: 整理好的单章正文（段落以空行分隔，末尾不含多余空白）
        """
        # ===== 站点适配模式库: 自动匹配已知站点配置 =====
        site_pattern = None
        if SITES_CONFIG_AVAILABLE:
            site_pattern = get_site_pattern(chapter_url)
            if site_pattern:
                print(f"[sites_config] 匹配到站点配置: {site_pattern['domain']}, 模式: {site_pattern['pattern']}")

        # 使用更真实的User-Agent，针对hatxt.cc网站添加特殊处理
        headers = {
            'User-Agent': self._fixed_ua,  # 会话固定UA (验证码cookie绑定UA)
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'DNT': '1',
            'Sec-GPC': '1',
            # 针对hatxt.cc网站添加的额外头信息
            'Referer': chapter_url,
            'Host': chapter_url.split('/')[2],
            'Pragma': 'no-cache',
            'TE': 'trailers'
        }

        # 存储所有页面的内容
        total_content = ""

        # 重置页面内容指纹（用于检测重复内容）
        self._last_page_fingerprint = None

        # 处理分页
        page_index = 0
        # ===== 优先使用 sites_config 中的分页配置 =====
        if site_pattern and 'content_pagination' in site_pattern:
            site_max_pages = site_pattern['content_pagination'].get('max_pages', 30)
        elif 'ahxsw.com' in chapter_url:
            site_max_pages = 30
        elif 'baoshuism.com' in chapter_url or 'zhiruo.org' in chapter_url or 'biquwx.cc' in chapter_url or '11bzw.org' in chapter_url:
            site_max_pages = 30
        else:
            site_max_pages = 20  # 未知站点默认 20 页 (原 5 页导致多页章节抓不全)
        # 如果调用方显式指定了 max_pages(例如测试模式只取前2页)，取较小值
        if max_pages is not None:
            max_pages = min(max_pages, site_max_pages)
        else:
            max_pages = site_max_pages
        
        while page_index < max_pages:
            # 构建当前页的URL
            if page_index == 0:
                current_url = chapter_url
            else:
                # ===== 优先使用 sites_config 生成分页 URL =====
                if site_pattern and 'content_pagination' in site_pattern:
                    current_url = build_paged_url(chapter_url, page_index, site_pattern['content_pagination'])
                    if current_url is None:
                        print(f"[分页] 已达到最大页数限制，停止")
                        break
                elif '.html' in chapter_url:
                    # 11bzw.org分页: 第2页是_2.html, 第3页是_3.html (page_index+1)
                    if '11bzw.org' in chapter_url:
                        current_url = chapter_url.replace('.html', f'_{page_index+1}.html')
                    else:
                        current_url = chapter_url.replace('.html', f'_{page_index}.html')
                else:
                    break
            
            validate_public_url(current_url)  # 安全校验: 仅允许公网 http/https
            print(f"\n=== 提取章节内容（第{page_index+1}页）: {current_url} ===")
            
            # 标记是否成功抓取
            success = False

            # ===== 通用数据文件解码 (content_decoder): 所有站点自动生效, 优先于通用检测 =====
            # 部分站点把正文放在独立数据文件中 (tanmixs .xs / banlvzw .book 码点流等),
            # 且正文页本身只是"加载中"占位 — 通用检测会把占位内容误判为正文,
            # 因此数据文件探测必须先于通用检测执行。
            if page_index == 0:
                self._datafile_mode = False
            if not self._datafile_mode and page_index == 0:
                try:
                    from content_decoder import decode_chapter_data
                    # 用本会话 (含 WAF 放行 cookie 等) 获取页面 HTML 后传入,
                    # 避免 decode_chapter_data 内部独立请求被反爬拦截 (如 banlvzw WAF 验证码)
                    self._datafile_page_html = None
                    try:
                        soup = self.inspect_page(current_url)
                        if soup is not None and hasattr(soup, 'prettify'):
                            self._datafile_page_html = str(soup)
                    except Exception:
                        self._datafile_page_html = None
                    data_text, data_method = decode_chapter_data(
                        current_url, page=1, page_html=self._datafile_page_html,
                        headers=headers)
                    if data_text and len(data_text) > 50:
                        self._datafile_mode = True
                        print(f"[数据文件] 探测命中 ({data_method}), 本卷章走数据文件模式")
                except ImportError:
                    pass  # content_decoder 模块未部署时走常规流程
                except Exception as e:
                    print(f"[数据文件] 探测失败, 走常规流程: {e}")
            if self._datafile_mode:
                try:
                    from content_decoder import decode_chapter_data
                    # 复用探测时的页面 HTML (数据文件引用每页相同), 避免独立请求被 WAF 拦截
                    data_text, data_method = decode_chapter_data(
                        current_url, page=page_index + 1,
                        page_html=getattr(self, '_datafile_page_html', None),
                        headers=headers)
                    if data_text and len(data_text) > 50:
                        # 去掉首行标题/元信息 (作者/字数/日期), 保留正文
                        data_lines = [l.strip() for l in data_text.split('\n') if l.strip()]
                        if data_lines and ('作者' in data_lines[0] or '★' in data_lines[0]
                                           or '☆' in data_lines[0] or '第' in data_lines[0]):
                            data_lines = data_lines[1:]
                        data_lines = [l for l in data_lines
                                      if not (('作者' in l and '字数' in l) or l.startswith('字数'))]
                        data_content = '\n'.join(data_lines)
                        if len(data_content) > 50:
                            print(f"[数据文件] 解码成功({data_method}): {len(data_content)} 字符 (第{page_index+1}页)")
                            page_text = self.clean_content(data_content)
                            if len(page_text) < 50:
                                print(f"[数据文件] 内容过短, 可能已到末页")
                                break
                            import hashlib
                            # 复合指纹: 前200字符 + 总长度 (避免分页开头固定模板导致误判重复)
                            fingerprint = hashlib.sha256((page_text[:200] + f"|{len(page_text)}").encode('utf-8')).hexdigest()[:16]
                            if fingerprint == self._last_page_fingerprint:
                                print(f"[数据文件] 与上一页指纹相同, 停止抓取")
                                break
                            self._last_page_fingerprint = fingerprint
                            total_content += page_text + '\n\n'
                            print(f"[数据文件] ✅ 合并, 累计 {len(total_content)} 字符")
                            success = True
                            page_index += 1
                            continue
                except ImportError:
                    self._datafile_mode = False
                except Exception as e:
                    print(f"[数据文件] 解码失败, 走常规流程: {e}")
                    self._datafile_mode = False

            # ===== 通用自动检测分发层 (基于内容特征, 不依赖域名) =====
            # 对未知站点自动识别内容模式 (qsbs_bb / html_selector), 优先尝试通用提取;
            # 已知站点的域名分支作为备用, 保证向后兼容。
            # 检测只在第1页做一次, 后续页面复用结果 (避免重复请求)
            # tanmixs.com: requests必然401, 跳过通用检测层直接走Selenium分支, 省去每页~15秒重试
            if 'tanmixs.com' in current_url:
                self._detected_pattern = None
            elif page_index == 0:
                self._detected_pattern = None  # 清除上一章节的缓存, 强制重新检测
                self._detected_pattern = self._detect_content_pattern(current_url, headers)
            generic_content = ''
            if self._detected_pattern == 'qsbs_bb':
                if page_index == 0:
                    print(f"[通用检测] 检测到 qsbs.bb Base64 加密, 走通用解码路径")
                generic_content = self._extract_qsbs_bb_generic(current_url, headers)
            elif self._detected_pattern == 'str_decode_bb':
                if page_index == 0:
                    print(f"[通用检测] 检测到 str_decode Base64 加密, 走通用解码路径")
                generic_content = self._extract_str_decode_generic(current_url, headers)
            elif self._detected_pattern == 'ajax_two_step':
                if page_index == 0:
                    print(f"[通用检测] 检测到 AJAX 两步加载, 走通用 AJAX 提取路径")
                generic_content = self._extract_ajax_two_step_generic(current_url, headers)
            elif self._detected_pattern == 'html_selector':
                if page_index == 0:
                    print(f"[通用检测] 检测到 HTML 选择器模式, 走通用提取路径")
                generic_content = self._extract_html_selector_generic(current_url, headers)

            if generic_content:
                # 通用提取成功, 走通用清洗+指纹去重流程
                import hashlib
                page_text = self.clean_content(generic_content)
                print(f"[通用提取] 第{page_index+1}页清洗后: {len(page_text)} 字符")
                if len(page_text) < 50:
                    print(f"[通用提取] 正文过短, 可能已到末页, 结束分页")
                    break
                # 复合指纹: 前200字符 + 总长度 (避免分页开头固定模板导致误判重复)
                fingerprint = hashlib.sha256((page_text[:200] + f"|{len(page_text)}").encode('utf-8')).hexdigest()[:16]
                if fingerprint == self._last_page_fingerprint:
                    print(f"[通用提取] 第{page_index+1}页与上一页指纹相同, 停止抓取")
                    break
                self._last_page_fingerprint = fingerprint
                total_content += page_text + '\n\n'
                print(f"[通用提取] 第{page_index+1}页: ✅ 合并, 累计 {len(total_content)} 字符")
                success = True
                page_index += 1
                continue

            # 通用层未命中或返回空内容, 尝试其他提取方式 (Selenium 等)

            # 对于tanmixs.com (探秘小说网移动版), 使用持久化Selenium driver
            # 正文容器为 div#chapter-content, 内含 <p class="chapter-line"> 段落
            # 段落中混有内联base64表情图, 需剔除; 首段为章节标题, 次段为元信息 (作者/字数/日期)
            # 分页: ?page=N 查询参数, 末页的下一页链接指向下一章 (无 ?page=)
            # 验证码: 使用 _solve_tanmixs_captcha 自动检测处理, 解决后复用同一driver
            if 'tanmixs.com' in current_url and selenium_available:
                print("[tanmixs] 使用持久化Selenium driver抓取章节内容")
                try:
                    driver = self._get_tanmixs_driver(visible=False)
                    driver.get(current_url)
                    _wait_driver_body(driver)
                    time.sleep(2)
                    # 检测并处理验证码 (如有)
                    page_source = self._solve_tanmixs_captcha(driver, current_url)
                    print(f"[tanmixs] 页面长度: {len(page_source)} 字符")

                    soup = BeautifulSoup(page_source, 'lxml')
                    # 提取 div#chapter-content
                    content_div = soup.select_one('div#chapter-content')
                    if not content_div:
                        print("[tanmixs] 未找到 div#chapter-content")
                        page_text = ''
                    else:
                        paragraphs = []
                        for p in content_div.find_all('p', class_='chapter-line'):
                            # 移除内联base64表情图
                            for img in p.find_all('img'):
                                img.decompose()
                            txt = p.get_text(strip=True)
                            if not txt:
                                continue
                            # 过滤元信息行 (作者, 字数, 日期等)
                            if re.search(r'^(作者[:：]|字数[:：]|更新|简介[:：]|类型[:：])', txt):
                                continue
                            if re.search(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}', txt):  # 纯日期行
                                continue
                            if _is_ad_line(txt):
                                continue
                            paragraphs.append(txt)
                        page_text = '\n\n'.join(paragraphs)
                        print(f"[tanmixs] 提取 {len(paragraphs)} 段, 共 {len(page_text)} 字符")

                    if len(page_text) < 50:
                        print(f"[tanmixs] 第{page_index+1}页正文过短 ({len(page_text)}字符), 结束分页")
                        success = False
                    else:
                        import hashlib
                        # 复合指纹: 前200字符 + 总长度 (避免分页开头固定模板导致误判重复)
                        fingerprint = hashlib.sha256((page_text[:200] + f"|{len(page_text)}").encode('utf-8')).hexdigest()[:16]
                        if fingerprint == self._last_page_fingerprint:
                            print(f"[tanmixs] 第{page_index+1}页与上一页指纹相同, 停止抓取")
                            success = False
                        else:
                            self._last_page_fingerprint = fingerprint
                            total_content += page_text + '\n\n'
                            print(f"[tanmixs] 第{page_index+1}页: 合并, 累计 {len(total_content)} 字符")
                            success = True

                            # 检测是否有下一页 (仅在分页URL ?page= 模式下)
                            # 末页的 "下一页" 链接指向下一章 (如 /YzN6/2.html), 没有 ?page= 参数
                            if page_index + 1 < max_pages:
                                next_a = None
                                # 找含 ?page= 的下一页链接
                                for a in soup.find_all('a', href=True):
                                    href = a.get('href', '')
                                    if '?page=' in href:
                                        next_a = a
                                        break
                                if next_a:
                                    next_href = next_a.get('href', '')
                                    # 处理相对路径
                                    if not next_href.startswith('http'):
                                        if next_href.startswith('/'):
                                            next_href = f"{self.base_url}{next_href}"
                                        else:
                                            next_href = f"{self.base_url}/{next_href}"
                                    # 校验URL
                                    try:
                                        validate_public_url(next_href)
                                    except ValueError:
                                        print(f"[tanmixs] 下一页URL校验失败: {next_href}")
                                        next_href = None
                                    if next_href:
                                        # 显式递增到下一分页
                                        page_index += 1
                                        current_url = next_href
                                        print(f"[tanmixs] 检测到下一分页: {current_url}")
                                        continue
                                else:
                                    print(f"[tanmixs] 未找到 ?page= 链接, 本章分页结束")
                except Exception as e:
                    print(f"[tanmixs] Selenium抓取失败: {e}")
                    import traceback
                    traceback.print_exc()

            # 对于pjxdd.com、qingheks.com、27xsw.cc、tanmixs.com网站，尝试使用Selenium
            # (zhiruo.org改用上方Base64解码分支，无需Selenium)
            if ('pjxdd.com' in current_url or 'qingheks.com' in current_url or '27xsw.cc' in current_url) and selenium_available:
                print("[Selenium] 尝试使用Selenium抓取内容")
                soup = self._selenium_get_soup(current_url, headers)
                if soup:
                    content = ""
                    content_selectors = ['#content', '.content', '.chapter_content', '.article_content', '.novel_content',
                                       '.read-content', '.article-content', '.story-content', '.post-content']
                    for selector in content_selectors:
                        content_div = soup.select_one(selector)
                        if content_div:
                            print(f"[Selenium] 找到内容容器: {selector}")
                            text = content_div.get_text(separator='\n\n', strip=True)
                            if text:
                                content = text
                                print(f"[Selenium] 提取到内容，长度: {len(content)} 字符")
                                break
                    if not content:
                        print("[Selenium] 尝试获取整个页面内容")
                        text = soup.get_text(separator='\n\n', strip=True)
                        content = text
                        print(f"[Selenium] 从整个页面提取到内容，长度: {len(content)} 字符")
                    if content:
                        content = re.sub(r'[\x00-\x1f\x7f-\xff]', '', content)
                        content = re.sub(r'\s+', ' ', content)
                        content = '\n'.join([line.strip() for line in content.split('\n') if line.strip()])
                        total_content += content + '\n\n'
                        print("[Selenium] 成功提取到内容")
                        success = True
                    else:
                        print("[Selenium] 未能提取到内容")
                else:
                    print("[Selenium] 页面抓取失败, 跳过")
                    success = False
            
            # 传统方法：使用requests
            import random
            max_retries = 3
            success = False
            for i in range(max_retries):  # 重试机制
                # tanmixs.com: requests必然401, 跳过重试 (已由上方Selenium分支处理)
                if 'tanmixs.com' in current_url:
                    break
                try:
                    # 随机延迟，避免被反爬虫 (0.5~1.5秒, 平衡速度与反爬)
                    delay = random.uniform(0.5, 1.5)
                    time.sleep(delay)
                    
                    response = self.session.get(current_url, headers=headers, timeout=30)
                    
                    # 检查状态码
                    if response.status_code == 404:
                        # 404 = 该页不存在 = 已到末页 (分页探测的 _N.html 常见此情况)
                        print(f"第{page_index+1}页不存在(404), 视为末页, 结束分页")
                        break
                    if response.status_code != 200:
                        print(f"请求失败，状态码: {response.status_code}")
                        if i < max_retries - 1:
                            # 更新User-Agent
                            headers['User-Agent'] = self._fixed_ua
                            continue
                        else:
                            print("所有重试机会已用尽")
                            break

                    # 处理JS cookie校验反爬(如zhiruo.org)
                    challenge_markers = ['ge_js_validator', 'window.location.reload']
                    for _ in range(4):
                        raw = response.content
                        if not any(m.encode() in raw for m in challenge_markers):
                            break
                        print(f"[反爬检测] 内容页命中JS cookie校验({len(raw)}字节)，提取cookie后重试...")
                        m = re.search(rb'document\.cookie\s*=\s*"([^"]+)"', raw)
                        if m:
                            cookie_str = m.group(1).decode('utf-8', errors='ignore')
                            cookie_kv = cookie_str.split(';')[0].strip()
                            if '=' in cookie_kv:
                                ck_name, ck_val = cookie_kv.split('=', 1)
                                self.session.cookies.set(ck_name.strip(), ck_val.strip())
                                print(f"[反爬检测] 已设置cookie: {ck_name.strip()}")
                            time.sleep(2)
                        response = self.session.get(current_url, headers=headers, timeout=30)

                    # 统一编码检测 (适用于所有网站)
                    try:
                        response.encoding = response.apparent_encoding
                        text = response.text
                        soup = BeautifulSoup(text, 'lxml')
                    except Exception:
                        pass
                    if not soup or not soup.find():
                        try:
                            import chardet
                            result = chardet.detect(response.content)
                            encoding = result['encoding']
                            if encoding:
                                text = response.content.decode(encoding, errors='ignore')
                                soup = BeautifulSoup(text, 'lxml')
                            else:
                                for enc in ['utf-8', 'gbk', 'gb2312', 'iso-8859-1']:
                                    try:
                                        text = response.content.decode(enc, errors='ignore')
                                        if text and len(text) > 100:
                                            soup = BeautifulSoup(text, 'lxml')
                                            break
                                    except Exception:
                                        pass
                        except Exception:
                            text = response.content.decode('utf-8', errors='ignore')
                            soup = BeautifulSoup(text, 'lxml')

                    # 方法1: 尝试从script标签中提取Base64编码内容
                    content = ""

                    # 查找包含Base64编码内容的script标签
                    script_patterns = [
                        r'document\.writeln\(qsbs\.bb\(["\']([^"\']+)["\']\)\);',
                        r'base64\.decode\(["\']([^"\']+)["\']\)',
                        r'atob\(["\']([^"\']+)["\']\)',
                        r'"([A-Za-z0-9+/=]{100,})"'
                    ]

                    # 尝试在原始响应内容中查找
                    raw_content = response.content

                    # 方法1.1: 直接在二进制数据中查找Base64编码
                    try:
                        # 将二进制数据转换为字符串进行搜索
                        raw_str = raw_content.decode('latin1')

                        # 查找可能的Base64编码
                        import base64
                        # 改进的Base64模式，支持更多格式
                        base64_patterns = [
                            r'[A-Za-z0-9+/=]{150,}',  # 更长的Base64编码
                            r'base64\.decode\(["\']([A-Za-z0-9+/=]{100,})["\']\)',  # 明确的base64.decode调用
                            r'atob\(["\']([A-Za-z0-9+/=]{100,})["\']\)',  # atob调用
                            r'document\.writeln\([^)]*["\']([A-Za-z0-9+/=]{100,})["\'][^)]*\)'  # document.writeln中的Base64
                        ]

                        all_matches = []
                        for pattern in base64_patterns:
                            matches = re.findall(pattern, raw_str)
                            if matches:
                                all_matches.extend(matches)

                        print(f"找到 {len(all_matches)} 个可能的Base64编码字符串")

                        # 去重
                        unique_matches = list(set(all_matches))
                        print(f"去重后剩余 {len(unique_matches)} 个唯一的Base64编码字符串")

                        for i, match in enumerate(unique_matches[:8]):  # 尝试前8个
                            try:
                                # 清理匹配结果
                                match = match.strip()
                                if len(match) < 100:
                                    continue

                                # 尝试添加填充并解码
                                padding = '=' * ((4 - len(match) % 4) % 4)
                                decoded_bytes = base64.b64decode(match + padding)

                                # 尝试不同的编码解码
                                decode_encodings = ['utf-8', 'gbk', 'gb2312', 'latin1', 'utf-16', 'utf-16le', 'utf-16be']
                                encoding_found = False  # 标记是否已找到正确编码(避免latin1/utf-16乱码污染)
                                for encoding in decode_encodings:
                                    try:
                                        decoded_text = decoded_bytes.decode(encoding)
                                        if decoded_text and len(decoded_text) > 80:
                                            # 校验解码质量:latin1/utf-16对任意字节都不抛异常,
                                            # 需检查是否含中文字符(UTF-8中文小说的标志)
                                            cjk_count = sum(1 for c in decoded_text if '\u4e00' <= c <= '\u9fff')
                                            # 非utf-8/gbk类编码,要求中文比例较高才算有效
                                            if encoding in ('latin1', 'utf-16', 'utf-16le', 'utf-16be'):
                                                if cjk_count < len(decoded_text) * 0.15:
                                                    print(f"  匹配 {i+1} (使用{encoding}) 解码成功但中文占比过低({cjk_count}/{len(decoded_text)})，跳过")
                                                    continue
                                            print(f"  匹配 {i+1} (使用{encoding}) 解码成功，长度: {len(decoded_text)} 字符")
                                            print(f"  解码后前100个字符: {decoded_text[:100]}...")

                                            # 检查是否包含HTML或文本内容
                                            if '<' in decoded_text:
                                                # 清理HTML标签
                                                soup_decoded = BeautifulSoup(decoded_text, 'lxml')
                                                # 移除脚本和样式
                                                for script in soup_decoded(['script', 'style']):
                                                    script.decompose()
                                                text = soup_decoded.get_text(strip=True)
                                            else:
                                                text = decoded_text

                                            if text and len(text) > 80:
                                                # 对于27xsw.cc网站，使用更严格的过滤
                                                if '27xsw.cc' in chapter_url:
                                                    # 过滤广告和无关内容
                                                    filter_keywords = ['上一章', '下一章', '章节目录', '保存书签', '请勿开启浏览器阅读模式',
                                                                       '相邻推荐', '加入书架', '返回顶部', '首页', '末页', '书包网', '登录', '注册',
                                                                       '搜索', 'Copyright', '版权所有', '本站所有内容', '一秒记住新域名',
                                                                       '田园养包子', '相公太黏人', '蜜母', '小说海棠文无删节', '翠微居全集免费阅读',
                                                                       '番外+大结局', '最新章节', '27小说网', '全文阅读', '免费阅读']

                                                    # 按行过滤
                                                    filtered_lines = []
                                                    for line in text.split('\n'):
                                                        stripped_line = line.strip()
                                                        if stripped_line:
                                                            # 检查是否包含过滤关键词
                                                            if not any(keyword in stripped_line for keyword in filter_keywords):
                                                                # 检查是否为有效的小说内容
                                                                if len(stripped_line) > 15 or any(char in stripped_line for char in ['，', '。', '！', '？', '；', '：', '“', '”', '‘', '’']):
                                                                    filtered_lines.append(stripped_line)

                                                    filtered_text = '\n\n'.join(filtered_lines)
                                                    if len(filtered_text) > 100:
                                                        content += filtered_text + '\n\n'
                                                        print(f"  成功提取到内容，长度: {len(filtered_text)} 字符")
                                                        encoding_found = True
                                                        # 找到足够的内容后停止
                                                        if len(content) > 500:
                                                            break
                                                else:
                                                    content += text + '\n\n'
                                                    print(f"  成功提取到内容，长度: {len(text)} 字符")
                                                    encoding_found = True
                                                    if len(content) > 500:
                                                        break
                                            # 找到有效编码后不再尝试其它编码(避免乱码污染)
                                            if encoding_found:
                                                break
                                    except Exception as e:
                                        pass
                            except Exception as e:
                                print(f"  匹配 {i+1} 解码失败: {e}")
                    except Exception as e:
                        print(f"  在二进制数据中查找Base64失败: {e}")
                    
                    # 方法1.2: 在解码后的文本中查找
                    if not content:
                        for pattern in script_patterns:
                            try:
                                matches = re.findall(pattern, raw_str)
                                if matches:
                                    print(f"找到 {len(matches)} 个匹配的script标签")
                                    for match in matches:
                                        try:
                                            # 提取Base64编码内容
                                            base64_content = match
                                            print(f"提取到Base64编码内容，长度: {len(base64_content)}字符")
                                            
                                            # 尝试直接解码
                                            padding = '=' * ((4 - len(base64_content) % 4) % 4)
                                            decoded_bytes = base64.b64decode(base64_content + padding)
                                            decoded_text = decoded_bytes.decode('utf-8', errors='ignore')
                                            # 从HTML中提取文本
                                            soup_decoded = BeautifulSoup(decoded_text, 'lxml')
                                            text = soup_decoded.get_text(strip=True)
                                            if text:
                                                content += text + '\n\n'
                                                print(f"成功提取到内容，长度: {len(text)} 字符")
                                                break
                                        except Exception as e:
                                            print(f"解码失败: {e}")
                                    if content:
                                        break
                            except Exception as e:
                                print(f"正则搜索失败: {e}")
                    
                    if content:
                        print(f"从script标签提取到内容，长度: {len(content)} 字符")
                    
                    # 方法2: 尝试查找可能的JSON数据
                    if not content or len(content) < 500:
                        # 查找包含小说内容的JSON
                        json_patterns = [
                            r'var\s+content\s*=\s*(\{[^}]+\})',
                            r'var\s+novel\s*=\s*(\{[^}]+\})',
                            r'var\s+chapter\s*=\s*(\{[^}]+\})',
                            r'var\s+data\s*=\s*(\{[^}]+\})',
                            r'content\s*:\s*(\"[^\"]+\")',
                            r'chapter_content\s*:\s*(\"[^\"]+\")',
                            r'novel_content\s*:\s*(\"[^\"]+\")'
                        ]
                        
                        for pattern in json_patterns:
                            match = re.search(pattern, response.text)
                            if match:
                                print(f"找到JSON数据: {pattern}")
                                try:
                                    json_data = match.group(1)
                                    # 尝试解析JSON
                                    if json_data.startswith('{'):
                                        data = json.loads(json_data)
                                        # 查找可能的内容字段
                                        for key in ['content', 'chapter_content', 'novel_content', 'text', 'content_text', 'body']:
                                            if key in data:
                                                content = data[key]
                                                break
                                    else:
                                        # 可能是直接的字符串
                                        content = json_data.strip('\"\'')
                                    break
                                except Exception as e:
                                    print(f"解析JSON失败: {e}")
                    
                    if content:
                        print(f"从JSON提取到内容，长度: {len(content)} 字符")

                    # ===== 通用解密链 (decrypt_utils): 自定义Base64/XOR/字符替换/拼接混淆/eval =====
                    # 常规 Base64 匹配失败时, 自动识别并尝试多种站点加密变体
                    if not content or len(content) < 100:
                        try:
                            from decrypt_utils import decrypt_content
                            decrypted, method = decrypt_content(text)
                            if decrypted:
                                dec_soup = BeautifulSoup(decrypted, 'lxml')
                                for sc in dec_soup(['script', 'style']):
                                    sc.decompose()
                                dec_text = dec_soup.get_text('\n', strip=True)
                                if len(dec_text) > 100:
                                    print(f"[通用解密] 使用 {method} 解密成功, {len(dec_text)} 字符")
                                    content = dec_text
                        except ImportError:
                            pass  # decrypt_utils 未部署时跳过
                        except Exception as e:
                            print(f"[通用解密] 失败: {e}")

                    # 方法2: 尝试查找特定的内容容器
                    if not content or len(content) < 500:
                        # 尝试各种可能的内容容器选择器
                        # 根据网站添加不同的内容选择器
                        content_selectors = [
                            '#content',
                            '.content',
                            '.chapter_content',
                            '.article_content',
                            '.novel_content',
                            '.content_main',
                            '#chapter_content',
                            '.read_content',
                            '.content_text',
                            'div[id*="content"]',
                            'div[class*="content"]',
                            'div[class*="article"]',
                            'div[class*="novel"]',
                            'div[class*="read"]',
                            '.text',
                            '#text',
                            '.neirong',
                            '#neirong',
                            '.zhangjie_content',
                            '.post_content',
                            '.entry_content',
                            '.page-content',
                            '.single-content',
                            '.post-body',
                            '.article-body',
                            '.novel-body',
                            'div[itemprop="articleBody"]',
                            'article',
                            '.article',
                            '.chapter',
                            'div.chapter',
                            'div.content',
                            '.content-wrap',
                            '.main-content',
                            '.article-content',
                            '.story-content',
                            '.chapter-content',
                            '#chapterContent',
                            '#articleContent',
                            '#storyContent',
                            '.content_detail',
                            '.read_text',
                            '.novel_text',
                            '.chapter_text'
                        ]
                        
                        # 针对hatxt.cc网站添加专门的选择器
                        if 'hatxt.cc' in chapter_url:
                            content_selectors.extend([
                                '.content',
                                '.read',
                                '#read',
                                '.chapter-content',
                                '.content_detail',
                                '.article',
                                '#article',
                                '.book-content',
                                '.chapterContent',
                                '.content-inner',
                                '.article-content',
                                '.post-content',
                                '.page-content',
                                'div[id*="content"]',
                                'div[class*="content"]',
                                'div[class*="read"]',
                                'div[class*="article"]',
                                'div[class*="novel"]',
                                'div[class*="story"]',
                                'article',
                                'section',
                                '.main',
                                '.body',
                                '.text',
                                '#text'
                            ])
                        # 针对baoshuism.com网站添加专门的选择器
                        elif 'baoshuism.com' in chapter_url:
                            content_selectors.extend([
                                '.word_read',
                                '#content',
                                '.content',
                                '#bookcontent',
                                '.bookcontent',
                                '#booktxt',
                                '.booktxt',
                                '#nr1',
                                '.nr1',
                                'div.content',
                                'div#content',
                                'div.bookcontent',
                                'div.text',
                                'article',
                                '.article',
                                '.read-content',
                                '.chapter-content'
                            ])
                        # 针对zhiruo.org网站添加专门的选择器
                        elif 'zhiruo.org' in chapter_url:
                            content_selectors.extend([
                                '#content',
                                '.content',
                                '#bookcontent',
                                '.bookcontent',
                                '#nr1',
                                '.nr1',
                                'div.content',
                                'div#content',
                                'div.bookcontent',
                                'article',
                                '.article',
                                '.read-content',
                                '.chapter-content'
                            ])
                        # 针对pjxdd.com网站添加专门的选择器
                        elif 'pjxdd.com' in chapter_url:
                            content_selectors.extend([
                                '.content',
                                '#content',
                                '.chapter_content',
                                '.article_content',
                                '.novel_content',
                                '.read_content',
                                '.content_text',
                                '.neirong',
                                '#neirong',
                                '.zhangjie_content',
                                '.post_content',
                                '.entry_content',
                                '.page-content',
                                '.single-content',
                                '.post-body',
                                '.article-body',
                                '.novel-body',
                                'div[itemprop="articleBody"]',
                                'article',
                                '.article',
                                '.chapter',
                                'div.chapter',
                                'div.content',
                                '.content-wrap',
                                '.main-content',
                                '.article-content',
                                '.story-content',
                                '.chapter-content',
                                '#chapterContent',
                                '#articleContent',
                                '#storyContent',
                                '.content_detail',
                                '.read_text',
                                '.novel_text',
                                '.chapter_text'
                            ])
                        # 针对27xsw.cc网站添加专门的选择器
                        elif '27xsw.cc' in chapter_url:
                            content_selectors.extend([
                                '#content',
                                '.content',
                                '.read-content',
                                '.chapter-content',
                                '.article-content',
                                '.novel-content',
                                '.content-main',
                                '.content_text',
                                'div[id*="content"]',
                                'div[class*="content"]',
                                'div[class*="read"]',
                                'div[class*="chapter"]',
                                'div[class*="article"]',
                                'div[class*="novel"]',
                                'article',
                                '.article',
                                '.chapter',
                                'div.chapter',
                                '.content-wrap',
                                '.main-content',
                                '.article-content',
                                '.story-content',
                                '.chapter-content',
                                '#chapterContent',
                                '#articleContent',
                                '#storyContent',
                                '.content_detail',
                                '.read_text',
                                '.novel_text',
                                '.chapter_text',
                                '.text',
                                '#text',
                                '.neirong',
                                '#neirong'
                            ])
                        
                        for selector in content_selectors:
                            content_div = soup.select_one(selector)
                            if content_div:
                                print(f"找到内容容器: {selector}")
                                # 移除脚本和样式
                                for script in content_div(['script', 'style']):
                                    script.decompose()
                                # 移除导航元素
                                for nav in content_div(['nav', 'footer', 'aside']):
                                    nav.decompose()
                                # baoshuism.com: word_read 内剔除标题(h3)/导航/广告元素,
                                # 避免 "第X部分（第1页）" 等标题混入正文
                                if 'baoshuism.com' in chapter_url:
                                    for el in content_div(['h1', 'h2', 'h3', 'h4', 'div', 'a']):
                                        el.decompose()
                                # 获取文本
                                text = content_div.get_text(separator='\n\n', strip=True)
                                
                                # 针对hatxt.cc网站的特殊处理
                                if 'hatxt.cc' in chapter_url:
                                    # 对hatxt.cc网站使用更严格的过滤条件
                                    print(f"原始内容长度: {len(text)} 字符")
                                    # 移除导航、版权、推荐等无关信息
                                    lines = text.split('\n')
                                    filtered_lines = []
                                    
                                    # 定义更全面的过滤关键词
                                    nav_keywords = ['上一章', '下一章', '章节目录', '保存书签', '加入书架', '返回顶部', '首页', '末页', '登录', '注册', '搜索', '立即阅读', '手机访问', '更新时间', '作者：']
                                    copy_keywords = ['Copyright', '版权所有', '本站所有内容', '哈哈电子书']
                                    recommend_keywords = ['《蜜母》最新章节', '主角', '小说海棠文无删节', '翠微居全集免费阅读', '番外+大结局', '最新章节']
                                    nav_section_keywords = ['首  页', '玄幻修真', '重生穿越', '都市小说', '军史小说', '网游小说', '科幻小说', '灵异小说', '言情小说', '其他小说', '阅读记录', '会员书架']
                                    
                                    # 标记是否进入小说正文
                                    in_content = False
                                    
                                    for line in lines:
                                        stripped_line = line.strip()
                                        if stripped_line:
                                            # 检查是否为导航部分
                                            if any(keyword in stripped_line for keyword in nav_section_keywords):
                                                continue
                                            
                                            # 检查是否为其他无关信息
                                            if any(keyword in stripped_line for keyword in nav_keywords + copy_keywords + recommend_keywords):
                                                continue
                                            
                                            # 检查是否为章节标题
                                            if '第' in stripped_line and ('章' in stripped_line or '节' in stripped_line):
                                                filtered_lines.append(stripped_line)
                                                in_content = True
                                                continue
                                            
                                            # 检查是否为小说正文内容（长度大于50字符，且不包含网站相关信息）
                                            if len(stripped_line) > 50 and 'http' not in stripped_line and '.com' not in stripped_line:
                                                filtered_lines.append(stripped_line)
                                                in_content = True
                                            elif in_content and len(stripped_line) > 20:
                                                # 如果已经进入正文，保留较短的段落
                                                filtered_lines.append(stripped_line)
                                    
                                    content = '\n\n'.join(filtered_lines)
                                    print(f"过滤后内容长度: {len(content)} 字符")
                                else:
                                    # 其他网站使用更宽松的过滤条件
                                    lines = text.split('\n')
                                    filtered_lines = []
                                    
                                    # 定义更全面的过滤关键词
                                    filter_keywords = [
                                        '上一章', '下一章', '章节目录', '保存书签', '请勿开启浏览器阅读模式',
                                        '相邻推荐', '加入书架', '返回顶部', '首页', '末页', '书包网', '登录', '注册',
                                        '搜索', 'Copyright', '版权所有', '本站所有内容', '一秒记住新域名',
                                        '田园养包子', '相公太黏人', '蜜母', '小说海棠文无删节', '翠微居全集免费阅读',
                                        '番外+大结局', '最新章节', '27小说网', '全文阅读', '免费阅读',
                                        '快穿：心机BOSS日日撩', '快穿成大佬的死对头', '穿成路人甲替深情男配挡箭后',
                                        '学长今天回家吗？', '敢吗？到我怀里来', '神话同人', '杨戬', '莲花千里不如君',
                                        '开朗少年奸淫记', '异世界一支枪', '农女天降', '娘子又又又乌鸦嘴了',
                                        '同人续写', '珠帘篇', '纳兰公瑾', 'z76488', '隨心', '孤牧栀笙'
                                    ]
                                    
                                    # 定义广告模式
                                    ad_patterns = [
                                        r'第\d+章.*?一秒记住新域名',
                                        r'一秒记住新域名.*?27小说网',
                                        r'27小说网.*?[《》]',
                                        r'[《》].*?最新章节',
                                        r'[《》].*?全文阅读',
                                        r'[《》].*?免费阅读'
                                    ]
                                    
                                    for line in lines:
                                        stripped_line = line.strip()
                                        if stripped_line:
                                            # 检查是否包含过滤关键词
                                            if any(keyword in stripped_line for keyword in filter_keywords):
                                                continue
                                            
                                            # 检查是否匹配广告模式
                                            ad_match = False
                                            for pattern in ad_patterns:
                                                if re.search(pattern, stripped_line):
                                                    ad_match = True
                                                    break
                                            if ad_match:
                                                continue
                                            
                                            # 检查是否为有效的小说内容
                                            if len(stripped_line) > 15 or any(char in stripped_line for char in ['，', '。', '！', '？', '；', '：', '“', '”', '‘', '’', '（', '）']):
                                                filtered_lines.append(stripped_line)
                                    
                                    content = '\n\n'.join(filtered_lines)
                                    
                                    # 对于27xsw.cc网站，进行额外的过滤
                                    if '27xsw.cc' in chapter_url:
                                        # 移除重复的空行
                                        content = re.sub(r'\n{3,}', '\n\n', content)
                                        # 移除行首行尾的空白
                                        content = '\n'.join([line.strip() for line in content.split('\n') if line.strip()])
                                        # 移除明显的广告段落
                                        paragraphs = content.split('\n\n')
                                        filtered_paragraphs = []
                                        for para in paragraphs:
                                            if para and len(para) > 50 and not any(keyword in para for keyword in filter_keywords):
                                                # 检查段落是否主要由广告组成
                                                ad_count = sum(1 for keyword in filter_keywords if keyword in para)
                                                if ad_count < 3:
                                                    filtered_paragraphs.append(para)
                                        content = '\n\n'.join(filtered_paragraphs)
                                
                                if content:
                                    print(f"从容器提取到内容，长度: {len(content)} 字符")
                                    break
                        
                        # 如果仍然没有找到内容，对hatxt.cc网站尝试直接从整个页面提取
                        if not content and 'hatxt.cc' in chapter_url:
                            print("尝试直接从整个页面提取内容")
                            # 移除脚本和样式
                            for script in soup(['script', 'style']):
                                script.decompose()
                            # 移除导航元素
                            for nav in soup(['nav', 'footer', 'aside']):
                                nav.decompose()
                            # 获取整个页面的文本
                            full_text = soup.get_text(separator='\n\n', strip=True)
                            print(f"整个页面原始内容长度: {len(full_text)} 字符")
                            
                            # 对hatxt.cc网站使用更严格的过滤条件
                            lines = full_text.split('\n')
                            filtered_lines = []
                            
                            # 定义更全面的过滤关键词
                            nav_keywords = ['上一章', '下一章', '章节目录', '保存书签', '加入书架', '返回顶部', '首页', '末页', '登录', '注册', '搜索', '立即阅读', '手机访问', '更新时间', '作者：']
                            copy_keywords = ['Copyright', '版权所有', '本站所有内容', '哈哈电子书']
                            recommend_keywords = ['《蜜母》最新章节', '主角', '小说海棠文无删节', '翠微居全集免费阅读', '番外+大结局', '最新章节']
                            nav_section_keywords = ['首  页', '玄幻修真', '重生穿越', '都市小说', '军史小说', '网游小说', '科幻小说', '灵异小说', '言情小说', '其他小说', '阅读记录', '会员书架']
                            
                            # 标记是否进入小说正文
                            in_content = False
                            
                            for line in lines:
                                stripped_line = line.strip()
                                if stripped_line:
                                    # 检查是否为导航部分
                                    if any(keyword in stripped_line for keyword in nav_section_keywords):
                                        continue
                                    
                                    # 检查是否为其他无关信息
                                    if any(keyword in stripped_line for keyword in nav_keywords + copy_keywords + recommend_keywords):
                                        continue
                                    
                                    # 检查是否为章节标题
                                    if '第' in stripped_line and ('章' in stripped_line or '节' in stripped_line):
                                        filtered_lines.append(stripped_line)
                                        in_content = True
                                        continue
                                    
                                    # 检查是否为小说正文内容（长度大于50字符，且不包含网站相关信息）
                                    if len(stripped_line) > 50 and 'http' not in stripped_line and '.com' not in stripped_line:
                                        filtered_lines.append(stripped_line)
                                        in_content = True
                                    elif in_content and len(stripped_line) > 20:
                                        # 如果已经进入正文，保留较短的段落
                                        filtered_lines.append(stripped_line)
                            content = '\n\n'.join(filtered_lines)
                            print(f"整个页面过滤后内容长度: {len(content)} 字符")
                            if content:
                                print("成功从整个页面提取到内容")
                    
                    # 方法3: 尝试使用正则表达式提取长段落
                    if not content or len(content) < 500:
                        # 移除HTML标签
                        clean_text = re.sub(r'<[^>]+>', '', response.text)
                        # 分割为段落
                        paragraphs = re.split(r'\n\s*\n', clean_text)
                        # 过滤段落
                        filtered_paragraphs = []
                        
                        for para in paragraphs:
                            para = para.strip()
                            if (len(para) > 300 and 
                                not any(keyword in para for keyword in ['上一章', '下一章', '章节目录', '保存书签', '请勿开启浏览器阅读模式', '相邻推荐', '加入书架', '返回顶部', '首页', '末页', '书包网', '登录', '注册', '搜索', 'Copyright', '版权所有', '本站所有内容']) and
                                'http' not in para and
                                '.com' not in para):
                                filtered_paragraphs.append(para)
                        
                        if filtered_paragraphs:
                            content = '\n\n'.join(filtered_paragraphs)
                            print(f"使用正则表达式提取到 {len(filtered_paragraphs)} 个段落，总长度: {len(content)} 字符")
                    
                    # 方法4: 尝试直接从页面中提取可能的小说内容特征
                    if not content or len(content) < 500:
                        # 查找包含引号的长文本（小说对话）
                        quote_pattern = r'\"\'[^\"\']{100,}\"\''
                        quotes = re.findall(quote_pattern, response.text)
                        if quotes:
                            content = '\n\n'.join(quotes)
                            print(f"找到 {len(quotes)} 个长引号，总长度: {len(content)} 字符")
                    
                    # 最终处理
                    if content:
                        # 尝试Base64解码
                        decoded_content = ""
                        # 查找所有可能的Base64编码字符串（通常以'PHA+'开头）
                        base64_patterns = [
                            r'\'PHA\+([^\']+)\'',  # 单引号包围的Base64
                            r'\"PHA\+([^\"]+)\"',  # 双引号包围的Base64
                            r'PHA\+([^\s]+)',  # 直接的Base64
                        ]
                        
                        for pattern in base64_patterns:
                            matches = re.findall(pattern, content)
                            if matches:
                                print(f"找到 {len(matches)} 个Base64编码字符串")
                                for match in matches:
                                    try:
                                        # 添加缺失的填充字符
                                        padding = '=' * ((4 - len(match) % 4) % 4)
                                        decoded_bytes = base64.b64decode(match + padding)
                                        decoded_text = decoded_bytes.decode('utf-8', errors='ignore')
                                        # 从HTML中提取文本
                                        soup_decoded = BeautifulSoup(decoded_text, 'lxml')
                                        text = soup_decoded.get_text(strip=True)
                                        if text:
                                            decoded_content += text + '\n\n'
                                    except Exception as e:
                                        print(f"Base64解码失败: {e}")
                                break
                        
                        # 如果解码成功，使用解码后的内容
                        if decoded_content:
                            content = decoded_content
                            print(f"Base64解码后内容长度: {len(content)} 字符")
                        else:
                            # 移除HTML实体
                            content = re.sub(r'&[a-zA-Z]+;', '', content)
                            # 移除多余的空白
                            content = '\n\n'.join([line.strip() for line in content.split('\n') if line.strip()])
                            # 移除可能的重复内容
                            lines = content.split('\n')
                            unique_lines = []
                            seen = set()
                            for line in lines:
                                if line not in seen:
                                    seen.add(line)
                                    unique_lines.append(line)
                            content = '\n'.join(unique_lines)
                            # 清理乱码和特殊字符
                            content = re.sub(r'[\x00-\x1f\x7f-\xff]', '', content)
                            # 清理重复的标点符号
                            content = re.sub(r'([.!?,;])\1+', r'\1', content)
                            
                            # 对于pjxdd.com网站，进行额外的清理
                            if 'pjxdd.com' in current_url:
                                print("对pjxdd.com网站进行额外的内容清理")
                                # 移除可能的乱码和特殊符号
                                content = re.sub(r'[\u0000-\u001f\u007f-\u00ff]', '', content)
                                # 移除多余的空白字符
                                content = re.sub(r'\s+', ' ', content)
                                # 移除行首行尾的空白
                                content = '\n'.join([line.strip() for line in content.split('\n') if line.strip()])
                                print(f"清理后内容长度: {len(content)} 字符")
                    
                    print(f"最终提取内容长度: {len(content) if content else 0} 字符")

                    # baoshuism.com: 站点占位提示("内容正在更新，请稍后查看")视为章节未发布
                    if content and 'baoshuism.com' in current_url and \
                            any(m in content for m in ['内容正在更新', '请稍后查看']):
                        print("⚠️ 该章节在网站端暂无内容(站点占位提示)，跳过")
                        content = ''

                    # 检查内容是否可能是小说
                    if content and len(content) > 100:  # 增加阈值，确保提取到足够的内容
                        print("成功提取到小说内容")

                        # 使用指纹检测重复内容（防止分页循环）
                        import hashlib
                        content_fingerprint = hashlib.sha256(
                            (content[:200] + f"|{len(content)}").encode('utf-8')).hexdigest()
                        print(f"[多页合并] 第{page_index+1}页: 内容指纹 {content_fingerprint[:16]}...")

                        if self._last_page_fingerprint:
                            print(f"[多页合并] 第{page_index+1}页: 上一页指纹 {self._last_page_fingerprint[:16]}...")
                            if content_fingerprint == self._last_page_fingerprint:
                                print(f"[多页合并] 第{page_index+1}页: ⚠️ 指纹匹配！内容与前页重复，结束抓取")
                                break
                            else:
                                print(f"[多页合并] 第{page_index+1}页: ✅ 指纹不同，内容不重复")

                        self._last_page_fingerprint = content_fingerprint
                        # 将当前页内容添加到总内容
                        total_content += content + '\n\n'
                        print(f"[多页合并] 第{page_index+1}页: ✅ 成功合并，累计 {len(total_content)} 字符")
                    else:
                        print("提取的内容可能不是小说正文")
                        # 如果内容太短，可能是分页结束
                        if page_index > 0:
                            print("内容过短，结束分页抓取")
                            break
                        else:
                            # 对于第一页，如果内容太短，尝试其他方法
                            print("第一页内容过短，尝试其他提取方法")
                            # 尝试使用正则表达式提取长段落
                            if not content or len(content) < 100:
                                print("尝试使用正则表达式提取长段落")
                                # 移除HTML标签
                                clean_text = re.sub(r'<[^>]+>', '', response.text)
                                # 分割为段落
                                paragraphs = re.split(r'\n\s*\n', clean_text)
                                # 定义过滤关键词
                                filter_keywords = [
                                    '上一章', '下一章', '章节目录', '保存书签', '请勿开启浏览器阅读模式',
                                    '相邻推荐', '加入书架', '返回顶部', '首页', '末页', '书包网', '登录', '注册',
                                    '搜索', 'Copyright', '版权所有', '本站所有内容', '一秒记住新域名',
                                    '田园养包子', '相公太黏人', '蜜母', '小说海棠文无删节', '翠微居全集免费阅读',
                                    '番外+大结局', '最新章节', '27小说网', '全文阅读', '免费阅读',
                                    '快穿：心机BOSS日日撩', '快穿成大佬的死对头', '穿成路人甲替深情男配挡箭后',
                                    '学长今天回家吗？', '敢吗？到我怀里来', '神话同人', '杨戬', '莲花千里不如君',
                                    '开朗少年奸淫记', '异世界一支枪', '农女天降', '娘子又又又乌鸦嘴了'
                                ]
                                
                                # 过滤段落
                                filtered_paragraphs = []
                                
                                for para in paragraphs:
                                    para = para.strip()
                                    if (len(para) > 150 and 
                                        not any(keyword in para for keyword in filter_keywords) and
                                        'http' not in para and
                                        '.com' not in para and
                                        'www.' not in para):
                                        filtered_paragraphs.append(para)
                                
                                if filtered_paragraphs:
                                    content = '\n\n'.join(filtered_paragraphs)
                                    print(f"使用正则表达式提取到 {len(filtered_paragraphs)} 个段落，总长度: {len(content)} 字符")
                                    if len(content) > 100:
                                        total_content += content + '\n\n'
                                        print("成功从长段落提取到小说内容")
                    
                    # 检查是否有下一页
                    # 查找分页链接
                    has_next_page = False
                    # 注意: 不用 '下一章'/'下一章节' 作为分页标记——
                    # 它们指向的是"下一章"而非"当前章的下一页", 误判会把
                    # 下一章正文混入当前章。仅识别明确的"下一页"文本。
                    next_page_texts = ['下一页', '下一頁', '下一页>>', '>>', '下页']
                    for text in next_page_texts:
                        next_link = soup.find('a', string=lambda s: s and text in s)
                        if next_link:
                            has_next_page = True
                            break

                    # 如果没有找到明确的下一页链接，尝试通过URL模式判断
                    if not has_next_page:
                        # 检查当前页面是否包含明显的分页标记
                        page_links = soup.find_all('a', href=True)
                        for link in page_links:
                            href = link['href']
                            # 检查链接是否包含当前章节的分页模式（_N.html后缀）
                            if f'_{page_index+1}.html' in href:
                                has_next_page = True
                                break
                    
                    if not has_next_page:
                        print("未找到下一页，结束分页抓取")
                        break
                    
                    # 进入下一页
                    page_index += 1
                    success = True
                    break
                    
                except Exception as e:
                    print(f"抓取失败: {current_url}, 错误: {e}")
                    time.sleep(3)
            
            # 如果重试后仍然失败，结束分页抓取
            if not success:
                print(f"多次尝试后仍然无法抓取 {current_url}，结束分页抓取")
                break

        # 整章段落级去重 (云趣阁等站点分页会重复前页内容)
        if total_content:
            total_content = self.deduplicate_paragraphs(total_content)

        return total_content

    def get_novel_title(self, catalog_url):
        """从目录页面提取小说名称"""
        headers = {
            'User-Agent': self._fixed_ua,  # 会话固定UA (验证码cookie绑定UA)
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'DNT': '1',
            'Sec-GPC': '1',
            'Referer': catalog_url,
            'Host': catalog_url.split('/')[2],
            'Pragma': 'no-cache',
            'TE': 'trailers'
        }
        try:
            response = self._get_with_js_challenge(catalog_url, headers)
            
            # 使用与内容页面相同的编码处理
            # 方法A: 尝试使用requests的自动编码检测
            try:
                response.encoding = response.apparent_encoding
                text = response.text
                soup = BeautifulSoup(text, 'html.parser')
            except Exception as e:
                # 方法B: 尝试使用chardet检测编码
                try:
                    import chardet
                    result = chardet.detect(response.content)
                    encoding = result['encoding']

                    if encoding:
                        text = response.content.decode(encoding, errors='ignore')
                        soup = BeautifulSoup(text, 'html.parser')
                    else:
                        # 方法C: 尝试使用常见编码
                        encodings = ['utf-8', 'gbk', 'gb2312', 'iso-8859-1', 'utf-16', 'utf-16le', 'utf-16be']
                        for encoding in encodings:
                            try:
                                text = response.content.decode(encoding, errors='ignore')
                                if text and len(text) > 100:
                                    soup = BeautifulSoup(text, 'html.parser')
                                    break
                            except Exception as e:
                                pass
                except Exception as e:
                    # 最终 fallback: 使用ignore模式
                    text = response.content.decode('utf-8', errors='ignore')
                    soup = BeautifulSoup(text, 'html.parser')
            
            # 尝试从标题标签提取
            if soup.title:
                title = soup.title.string.strip() if soup.title.string else ""
                # 清理标题，移除可能的网站名称等
                for suffix in ['-书包网', '-小说', '-阅读', '-全文阅读', '最新章节', '-pjxdd.com', '-m.pjxdd.com', '-qingheks.com', '-ahxsw.com']:
                    if title.endswith(suffix):
                        title = title[:-len(suffix)]

                # 对于ahxsw.com网站，清理标题格式"小说名无防盗_小说名全文阅读_作者_安徽小说网"
                if 'ahxsw.com' in catalog_url:
                    # 取第一个下划线前的部分作为小说名
                    if '_' in title:
                        title = title.split('_')[0]
                    # 移除"无防盗"后缀
                    title = title.replace('无防盗', '').strip()

                # 云趣阁 (28zw.org / spscl.com) 详情页 <title> 格式:
                # "书名最新章节列表_书名刚刚更新(作者)_云趣阁" 或
                # "书名最新章节_txt全文阅读_作者_云趣阁"
                # 优先用 <h1> 或详情页书名容器提取; 失败则从 <title> 中正则提取纯书名
                if '28zw.org' in catalog_url or 'spscl.com' in catalog_url:
                    # 优先从详情页的书名容器提取 (最准确)
                    yq_selectors = [
                        'div.info h1', 'div.book-info h1', 'div.bookname h1',
                        'div.btitle h1', 'h1.bookTitle', 'h1.title',
                        'div#info h1', 'div.info_title', 'div.bookTitle',
                        'div.novel_title', 'div.book-title',
                    ]
                    yq_title = None
                    for sel in yq_selectors:
                        el = soup.select_one(sel)
                        if el:
                            t = el.get_text(strip=True)
                            if t and len(t) < 60 and '最新章节' not in t:
                                yq_title = t
                                break
                    if not yq_title:
                        h1 = soup.find('h1')
                        if h1:
                            t = h1.get_text(strip=True)
                            # 排除章节页 H1 (如 "楔子（第1页）")
                            if t and len(t) < 30 and '第' not in t and '页' not in t:
                                yq_title = t
                    if not yq_title:
                        # 从 <title> 正则提取纯书名:
                        # "美熟妇深渊堕落最新章节列表_..." -> "美熟妇深渊堕落"
                        m = re.match(r'^(.+?)最新章节', title)
                        if m and m.group(1):
                            yq_title = m.group(1).strip()
                    if yq_title:
                        # 移除残留的"txt"/"全文阅读"等
                        for kw in ['txt', 'TXT', '全文阅读', '免费阅读', '无弹窗', '最新章节']:
                            yq_title = yq_title.replace(kw, '').strip()
                        if yq_title:
                            print(f"[云趣阁] 从详情页提取到小说名称: {yq_title}")
                            return yq_title

                # 清理标题中的乱码和特殊字符
                title = re.sub(r'[\x00-\x1f\x7f-\xff]', '', title)
                title = re.sub(r'\s+', ' ', title)
                title = title.strip()
                if title:
                    print(f"从标题标签提取到小说名称: {title}")
                    return title
            
            # 尝试从常见的小说标题容器提取
            title_selectors = [
                '.book-title',
                '.novel-title',
                '.title',
                'h1',
                'h2',
                '.book-name',
                '.novel-name',
                '.book_title',
                '.novel_title',
                '.bookname',
                '.novelname',
                '.bookTitle',
                '.novelTitle',
                '.name',
                '.bookname',
                '.novelname',
                '.title-wrap',
                '.book-info h1',
                '.novel-info h1',
                '.book-detail h1',
                '.novel-detail h1'
            ]
            
            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    title = title_elem.get_text().strip()
                    # 清理标题中的乱码和特殊字符
                    title = re.sub(r'[\x00-\x1f\x7f-\xff]', '', title)
                    title = re.sub(r'\s+', ' ', title)
                    title = title.strip()
                    if title:
                        print(f"从选择器 {selector} 提取到小说名称: {title}")
                        return title
            
            # 尝试从meta标签提取
            meta_title = soup.find('meta', property='og:title') or soup.find('meta', {'name': 'title'})
            if meta_title:
                title = meta_title.get('content', '').strip()
                # 清理标题
                title = re.sub(r'[\x00-\x1f\x7f-\xff]', '', title)
                title = re.sub(r'\s+', ' ', title)
                title = title.strip()
                if title:
                    print(f"从meta标签提取到小说名称: {title}")
                    return title
            
            # 对于特定网站，使用默认名称
            if 'pjxdd.com' in catalog_url or 'qingheks.com' in catalog_url:
                return "小说"

            # 首次请求可能命中反爬挑战页 (标题为 loading/验证码占位), 等待后重试一次
            try:
                print("[书名] 未提取到有效标题 (可能命中反爬页), 3 秒后重试...")
                time.sleep(3)
                response = self._get_with_js_challenge(catalog_url, headers)
                response.encoding = response.apparent_encoding or 'utf-8'
                soup = BeautifulSoup(response.text, 'html.parser')
                t = (soup.title.get_text(strip=True) if soup.title else '') or ''
                if t and 'loading' not in t.lower() and '验证码' not in t \
                        and '访问频率' not in t and len(t) > 2:
                    # 清理常见站点后缀
                    title = re.sub(r'[\x00-\x1f\x7f-\xff]', '', t)
                    title = re.sub(r'[_\-|].*$', '', title)
                    title = re.sub(r'(最新章节|全文阅读|免费阅读|最新章节列表).*$', '', title)
                    title = title.strip()
                    if title:
                        print(f"重试后提取到小说名称: {title}")
                        return title
            except Exception:
                pass
            return "novel"
        except Exception as e:
            print(f"提取小说名称失败: {e}")
            # 对于特定网站，使用默认名称
            if 'pjxdd.com' in catalog_url or 'qingheks.com' in catalog_url:
                return "小说"
            return "novel"

    # ================== 断点续传 (检查点) ==================
    @staticmethod
    def _checkpoint_paths(output_file):
        """生成检查点文件路径 (与输出文件同目录)。
        安全: 先规范化(abspath)再取目录/文件名，禁止 ../ 路径穿越。"""
        out_abs = os.path.abspath(output_file)
        out_dir = os.path.dirname(out_abs)
        out_name = os.path.basename(out_abs)
        if not out_name:
            raise ValueError("输出文件名无效")
        return os.path.join(out_dir, out_name + '.checkpoint.json')

    def _load_checkpoint(self, output_file, catalog_url):
        """读取检查点。目录URL不匹配(不同小说)或文件损坏时返回 None"""
        ck_path = self._checkpoint_paths(output_file)
        try:
            ck = json.loads(Path(ck_path).read_text(encoding='utf-8'))
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return None
        if ck.get('catalog_url') != catalog_url:
            return None
        return ck

    def _save_checkpoint(self, output_file, catalog_url, completed, total):
        """保存检查点 (JSON 写入检查点文件)"""
        ck_path = self._checkpoint_paths(output_file)
        data = {
            'catalog_url': catalog_url,
            'output_file': output_file,
            'completed': completed,
            'total': total,
            'updated': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        Path(ck_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def _remove_checkpoint(self, output_file):
        """抓取全部完成后删除检查点"""
        ck_path = self._checkpoint_paths(output_file)
        try:
            Path(ck_path).unlink(missing_ok=True)
        except OSError as e:
            print(f"[断点续传] 删除检查点失败: {e}")

    def _count_written_chapters(self, output_file):
        """统计输出文件中已写的章节数 (检查点损坏/缺失时的兜底)"""
        try:
            with Path(output_file).open('r', encoding='utf-8') as f:
                return sum(1 for line in f if line.startswith('## '))
        except (FileNotFoundError, UnicodeDecodeError, OSError):
            return 0

    def _fetch_chapter_worker(self, chap):
        """并发抓取单章 (每个调用使用独立 Session, 避免共享 Session 的 cookie 竞态)。
        返回该章合并后的正文内容字符串。"""
        old_session = self.session
        new_session = requests.Session()
        new_session.headers.update(old_session.headers)
        new_session.keep_alive = True
        # 与主 Session 一致: 直连忽略系统代理, 保留显式配置的代理
        new_session.trust_env = False
        new_session.proxies.update(old_session.proxies)
        self.session = new_session
        try:
            return self.get_chapter_content(chap['url'])
        finally:
            self.session = old_session

    def run(self, catalog_url, output_file=None, sort_chapters=False, output_dir=None,
            resume=True, show_progress=True, chapter_range=None, threads=1, delay=1.0,
            stop_event=None):
        """完整抓取小说。
        resume=True 时自动检测检查点，从上次中断处继续（追加写入）。
        show_progress=True 时每章更新下载进度条。
        chapter_range: (start, end) 1-based 章节索引区间，None 表示抓取全部。
        threads: 并发抓取线程数 (1=串行)。并发时按章节顺序写入, 断点续传不受影响。
        delay: 章节间请求间隔秒数 (越小越快, 但可能触发站点反爬)。
        """
        # 提取小说名称
        novel_title = self.get_novel_title(catalog_url)
        print(f"提取到小说名称: {novel_title}")

        # 处理输出文件名 (安全: 只使用 basename, 禁止 ../ 路径穿越)
        if not output_file:
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', novel_title)
            if chapter_range:
                sr, er = chapter_range
                output_file = f"{safe_title}_第{sr}-{er}章.txt"
            else:
                output_file = f"{safe_title}.txt"
        else:
            output_file = os.path.basename(output_file)

        # 如果指定了输出目录，创建并使用它 (安全: 规范化并确认位于输出目录内)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            output_dir_abs = os.path.abspath(output_dir)
            output_file = os.path.abspath(os.path.join(output_dir_abs, output_file))
            if not output_file.startswith(output_dir_abs + os.sep):
                raise ValueError(f"输出路径越界: {output_file}")
            print(f"输出目录: {output_dir}")

        chapters = self.get_chapter_list(catalog_url, sort_chapters)

        # ===== 章节范围过滤 =====
        if chapter_range:
            sr, er = chapter_range
            total_all = len(chapters)
            start_idx = max(0, sr - 1)
            end_idx = min(total_all, er)
            if start_idx >= total_all:
                print(f"⚠️ 起始章节 {sr} 超出范围 (共 {total_all} 章)，抓取终止")
                return None
            end_idx = max(end_idx, start_idx + 1)
            chapters = chapters[start_idx:end_idx]
            total = len(chapters)
            print(f"[章节范围] 第 {sr} ~ {er} 章，实际 {total} 章 (全书共 {total_all} 章)")
        else:
            total = len(chapters)

        if total == 0:
            print("⚠️ 未提取到任何章节，抓取终止")
            return None

        # ===== 断点续传: 检测检查点 =====
        start = 0
        if resume:
            ck = self._load_checkpoint(output_file, catalog_url)
            if ck:
                done = int(ck.get('completed', 0))
                if done >= total:
                    print(f"[断点续传] 检查点显示上次已全部完成 ({done}/{total} 章)，从头重新抓取")
                    self._remove_checkpoint(output_file)
                elif done > 0:
                    start = done
                    print(f"[断点续传] 检测到上次进度: 已完成 {done}/{total} 章，从第 {done+1} 章继续")
                else:
                    print("[断点续传] 检查点无有效进度，从头开始")
            else:
                # 无有效检查点时, 用输出文件中已写章节数兜底
                fallback = self._count_written_chapters(output_file)
                if fallback >= total:
                    print(f"[断点续传] 输出文件已包含全部 {total} 章，从头重新抓取")
                elif fallback > 0:
                    start = fallback
                    print(f"[断点续传] 未找到有效检查点，输出文件已有 {fallback} 章，从第 {fallback+1} 章继续")
                else:
                    print("[断点续传] 未检测到该书的进度，从头开始")
        else:
            print("[断点续传] 已禁用，从头开始")
            self._remove_checkpoint(output_file)

        open_mode = 'a' if start > 0 else 'w'
        if start > 0:
            print(f"[断点续传] 以追加模式写入: {output_file}")

        # tanmixs 的 WAF 按 IP 限流: 多浏览器并发会更容易触发验证码(实测并发3线程反而更慢)
        # 强制串行 + 持久化 driver 复用是最优策略
        if 'tanmixs.com' in catalog_url and threads > 1:
            print("[并发] ⚠️ tanmixs.com WAF 限流敏感, 多浏览器并发会触发验证码, 已强制串行")
            threads = 1

        failed = []
        try:
            with Path(output_file).open(open_mode, encoding='utf-8') as f:
                if threads > 1 and (total - start) > 1:
                    # ===== 并发抓取: 并行请求章节, 按章节顺序写入 =====
                    # 保证文件顺序和断点续传正确性; 抓取完成顺序无关紧要
                    print(f"[并发] 启用 {threads} 线程并发抓取 (按章节顺序写入)")
                    from concurrent.futures import ThreadPoolExecutor
                    worker = self._fetch_chapter_worker
                    with ThreadPoolExecutor(max_workers=threads) as pool:
                        futures = {}
                        for i in range(start, total):
                            futures[i] = pool.submit(worker, chapters[i])
                        for i in range(start, total):
                            if stop_event is not None and stop_event.is_set():
                                print(f"\n⚠️ 用户停止! 进度检查点已保存 (输出: {output_file})")
                                return output_file
                            chap = chapters[i]
                            print(f"\n=== 正在抓取第 {i+1}/{total} 章: {chap['title']} ===")
                            try:
                                content = futures[i].result()
                            except KeyboardInterrupt:
                                raise
                            except Exception as e:
                                print(f"抓取异常: {e}")
                                content = ''
                            # 先成功抓到内容再写入标题+正文, 避免中断留下空标题章节
                            f.write(f"## {chap['title']}\n\n")
                            f.write(content + "\n\n")
                            if content:
                                print(f"成功: {len(content)} 字符")
                            else:
                                failed.append(i + 1)
                                print("失败: 未提取到内容")
                            # 每章完成后更新检查点（中断后可从断点续传）
                            self._save_checkpoint(output_file, catalog_url, i + 1, total)
                            if show_progress:
                                print_progress_bar(i + 1, total, extra=chap['title'][:20])
                else:
                    # ===== 串行抓取 (默认) =====
                    for i in range(start, total):
                        if stop_event is not None and stop_event.is_set():
                            print(f"\n⚠️ 用户停止! 进度检查点已保存 (输出: {output_file})")
                            return output_file
                        chap = chapters[i]
                        print(f"\n=== 正在抓取第 {i+1}/{total} 章: {chap['title']} ===")
                        try:
                            content = self.get_chapter_content(chap['url'])
                        except Exception as e:
                            print(f"抓取异常: {e}")
                            content = ''
                        # 先成功抓到内容再写入标题+正文, 避免中断留下空标题章节
                        f.write(f"## {chap['title']}\n\n")
                        f.write(content + "\n\n")
                        if content:
                            print(f"成功: {len(content)} 字符")
                        else:
                            failed.append(i + 1)
                            print("失败: 未提取到内容")
                        # 每章完成后更新检查点（中断后可从断点续传）
                        self._save_checkpoint(output_file, catalog_url, i + 1, total)
                        if show_progress:
                            print_progress_bar(i + 1, total, extra=chap['title'][:20])
                        if delay > 0:
                            time.sleep(delay)  # 请求间隔，尊重服务器
        except KeyboardInterrupt:
            print(f"\n⚠️ 用户中断! 进度检查点已保存，下次运行将自动从断点继续 (输出: {output_file})")
            return output_file

        self._remove_checkpoint(output_file)
        # 暴露抓取结果统计 (供多源回退判定使用)
        self.last_failed = failed
        self.last_total = total
        # 验证码监控报告 (类型/耗时/成功率/成本) 与告警
        if self._captcha_manager is not None:
            try:
                print(f"\n{self._captcha_manager.report()}")
                for alarm in self._captcha_manager.alarms():
                    print(alarm)
            except Exception:
                pass
        if failed:
            print(f"\n抓取结束: 共{total}章，{len(failed)}章失败(章节号: {failed})，已保存至{output_file}")
        else:
            print(f"\n抓取完成，共{total}章，已保存至{output_file}")
        return output_file


def get_base_url(url):
    """从完整URL中提取基础URL"""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _wait_driver_body(driver):
    """等待页面 body 就绪 (兼容 Selenium / Playwright 两种驱动引擎)"""
    if hasattr(driver, 'wait_for'):
        # Playwright 驱动: 内置显式等待
        try:
            driver.wait_for('tag name', 'body')
        except Exception:
            pass
    else:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, 'body')))


def print_progress_bar(current, total, width=40, extra=""):
    """终端下载进度条 (ASCII 安全, 无第三方依赖)"""
    if total <= 0:
        return
    pct = current / total
    filled = int(width * pct)
    bar = '#' * filled + '-' * (width - filled)
    sys.stdout.write(f"\r[{bar}] {current}/{total} ({pct*100:.1f}%) {extra}")
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")
        sys.stdout.flush()

def interactive_menu():
    """交互式菜单，返回 (url, mode, sort_chapters, resume, show_progress, chapter_range, threads, delay)。
    mode: 'list' 只看章节列表 / 'full' 完整抓取 / 'test' 快速测试(提取第1章前2页) / 'range' 自定义区间
    chapter_range: (start, end) 1-based 章节索引区间，或 None 表示不限制
    threads: 并发线程数 / delay: 章节间间隔秒数"""
    print("=== 小说爬虫 ===")
    print("请输入小说网站的目录页面URL:")
    print("例如: https://www.shubaoxs.net/book/391625/")
    print("     https://www.baoshuism.com/books/301597.html")
    print("     https://www.zhiruo.org/infos/5523629.html")

    catalog_url = input("\nURL: ").strip()
    if not catalog_url:
        print("错误: 请输入有效的URL")
        return None, None, False, True, True, None, 1, 1.0

    # 章节排序选项
    print("\n章节排序选项:")
    print("1. 启用排序 (按照章节号排序，自动从第1章排到最后一章)")
    print("2. 禁用排序 (保持原目录顺序)")
    sort_choice = input("请选择 (1/2，默认1): ").strip() or "1"
    sort_chapters = sort_choice == "1"

    # 操作选项
    print("\n操作选项:")
    print("1. 只查看章节列表")
    print("2. 完整抓取内容 (保存到 抓取结果/ 文件夹)")
    print("3. 快速测试 (提取第1章前2页内容，验证网站是否支持)")
    print("4. 自定义区间 (指定起始章节和结束章节，只抓取该区间)")
    op_choice = input("请选择 (1/2/3/4，默认2): ").strip() or "2"
    mode = {"1": "list", "2": "full", "3": "test", "4": "range"}.get(op_choice, "full")

    chapter_range = None
    if mode == "range":
        print("\n--- 自定义章节区间 ---")
        print("提示: 章节编号从 1 开始，排序后第1章=第一章")
        try:
            start_str = input("起始章节 (默认1): ").strip() or "1"
            end_str = input("结束章节 (默认20): ").strip() or "20"
            start_ch = int(start_str)
            end_ch = int(end_str)
            if start_ch < 1 or end_ch < start_ch:
                print("错误: 起始章节必须 >= 1，结束章节必须 >= 起始章节")
                return None, None, False, True, True, None, 1, 1.0
            chapter_range = (start_ch, end_ch)
            print(f"已选择: 第 {start_ch} 章 ~ 第 {end_ch} 章 (共 {end_ch - start_ch + 1} 章)")
        except ValueError:
            print("错误: 请输入有效的数字")
            return None, None, False, True, True, None, 1, 1.0

    resume = True
    show_progress = True
    threads = 1
    delay = 1.0
    if mode in ("full", "range"):
        # 断点续传选项
        print("\n断点续传选项 (中断后可继续抓取):")
        print("1. 启用 (检测到上次未完成的进度自动继续，推荐)")
        print("2. 禁用 (从头开始)")
        resume = input("请选择 (1/2，默认1): ").strip() != "2"

        # 下载进度条选项
        print("\n下载进度条选项:")
        print("1. 启用 (每章显示下载进度，推荐)")
        print("2. 禁用")
        show_progress = input("请选择 (1/2，默认1): ").strip() != "2"

        # 抓取速度选项
        print("\n抓取速度选项:")
        print("1. 标准 (串行，每章间隔1秒，最稳妥)")
        print("2. 快速 (3线程并发，间隔0.3秒，约3倍速)")
        print("3. 极速 (6线程并发，间隔0.1秒，最快，可能触发站点反爬)")
        speed_choice = input("请选择 (1/2/3，默认1): ").strip() or "1"
        if speed_choice == "2":
            threads, delay = 3, 0.3
        elif speed_choice == "3":
            threads, delay = 6, 0.1

    return catalog_url, mode, sort_chapters, resume, show_progress, chapter_range, threads, delay


# 计算默认输出目录:
# - 开发模式 (python 爬虫.py)                     : 项目根/抓取结果/
# - PyInstaller onefile (小说爬虫.exe)           : EXE 所在目录/抓取结果/
# 无论从哪个工作目录启动, 都会落到同一个可写输出目录, 避免生成多套重复结果
from _path_utils import (  # noqa: E402
    get_default_output_dir as _get_default_output_dir,
    resolve_output_dir as _resolve_output_dir_via_utils,
)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_OUTPUT_DIR = _get_default_output_dir()


def _resolve_output_dir(output_dir: str) -> str:
    """将输出目录解析为绝对路径；相对路径统一相对于 BASE_DIR
    (源码模式 = 项目根, EXE 模式 = EXE 所在目录)"""
    return _resolve_output_dir_via_utils(output_dir)


def run_crawl(catalog_url, mode="full", sort_chapters=True, output_dir=None,
              resume=True, show_progress=True, chapter_range=None, threads=1, delay=1.0,
              stop_event=None):
    """根据模式执行抓取任务，供命令行与交互式共用

    Args:
        catalog_url: 小说目录页 URL
        mode: list / full / test / range
        sort_chapters: 是否按章节数字排序
        output_dir: 输出目录（为 None 时使用默认：项目根/抓取结果）
        resume: 是否断点续传
        show_progress: 是否显示进度条
        chapter_range: (start, end) 1-based 章节索引区间，仅 range 模式使用
        threads: 并发抓取线程数 (1=串行)
        delay: 章节间请求间隔秒数
        stop_event: threading.Event，GUI 停止按钮设置后中断抓取
    """
    # 统一输出目录 -> 绝对路径, 避免多套结果目录
    if output_dir is None:
        output_dir = _DEFAULT_OUTPUT_DIR
    output_dir = _resolve_output_dir(output_dir)
    print(f"[输出目录] {output_dir}")
    # 调试日志: 抓取入口 (供事后排查)
    print(f"[调试] 抓取开始: {catalog_url} 模式={mode} 区间={chapter_range} "
          f"线程={threads} 延迟={delay} 续传={resume} 输出={output_dir}")

    # 安全校验: 仅允许公网 http/https URL
    try:
        validate_public_url(catalog_url)
    except ValueError as e:
        print(f"⚠️ URL 校验失败: {e}")
        return

    base_url = get_base_url(catalog_url)
    print(f"提取到基础URL: {base_url}")
    spider = NovelSpider(base_url)

    if mode == "list":
        chapters = spider.get_chapter_list(catalog_url, sort_chapters)
        print("\n=== 章节列表 ===")
        for i, chap in enumerate(chapters):
            print(f"  {i+1}. {chap['title']} -> {chap['url']}")
        print(f"\n共找到 {len(chapters)} 个章节")
        return

    if mode == "test":
        chapters = spider.get_chapter_list(catalog_url, sort_chapters)
        print(f"\n共找到 {len(chapters)} 个章节")
        if not chapters:
            print("⚠️ 未提取到章节，可能需要适配该网站结构")
            return
        print(f"第1章: {chapters[0]['title']}")
        print(f"最后章: {chapters[-1]['title']}")
        print("\n--- 提取第1章内容(前2页) ---")
        content = spider.get_chapter_content(chapters[0]['url'], max_pages=2)
        print(f"内容长度: {len(content)} 字符")
        if content:
            print(f"内容预览: {content[:200]}...")
        else:
            print("⚠️ 未提取到内容，可能需要调整内容选择器")
        return

    # mode == "full" or "range"
    # ===== 多源回退: 主源抓取失败(验证码拦死/章节大面积失败)时自动尝试备用源 =====
    # 备用源配置在 captcha_config.json 的 fallback_sources 字段:
    #   {"书目录URL": ["备用目录URL1", "备用目录URL2", ...]}
    # 或指向一个 JSON 文件路径
    sources = [catalog_url]
    try:
        if spider._captcha_manager is not None:
            fs = spider._captcha_manager.config.data.get('fallback_sources', {})
            if isinstance(fs, str) and os.path.exists(fs):
                fs = json.loads(Path(fs).read_text(encoding='utf-8'))
            if isinstance(fs, dict):
                for alt in fs.get(catalog_url, []):
                    if alt and alt not in sources:
                        sources.append(alt)
    except Exception as e:
        print(f"[多源回退] 配置读取失败: {e}")

    if len(sources) > 1:
        print(f"[多源回退] 共 {len(sources)} 个数据源 (主源 + {len(sources)-1} 个备用)")

    for src_idx, src in enumerate(sources):
        if src_idx > 0:
            print(f"[多源回退] ⚠️ 主源抓取异常, 切换备用源 {src_idx}/{len(sources)-1}: {src}")
        src_spider = NovelSpider(get_base_url(src))
        if mode == "range" and chapter_range:
            src_spider.run(src, sort_chapters=sort_chapters, output_dir=output_dir,
                           resume=resume, show_progress=show_progress,
                           chapter_range=chapter_range, threads=threads, delay=delay,
                           stop_event=stop_event)
        else:
            src_spider.run(src, sort_chapters=sort_chapters, output_dir=output_dir,
                           resume=resume, show_progress=show_progress,
                           threads=threads, delay=delay, stop_event=stop_event)
        # 成功判定: 失败章节占比 < 20% 且验证码触发率 < 50%
        failed = getattr(src_spider, 'last_failed', None)
        total_n = getattr(src_spider, 'last_total', 0)
        if failed is None:
            return  # run 内部异常终止(如无章节), 不再尝试备用源
        fail_ratio = len(failed) / max(total_n, 1)
        rate = 0.0
        if src_spider._captcha_manager is not None:
            try:
                rate = src_spider._captcha_manager.monitor.trigger_rate()
            except Exception:
                pass
        if fail_ratio < 0.2 and rate < 0.5:
            print(f"[多源回退] ✅ 源 {src_idx+1}/{len(sources)} 抓取成功 "
                  f"(失败率 {fail_ratio:.0%}, 验证码触发率 {rate:.0%})")
            return
        print(f"[多源回退] 源 {src_idx+1}/{len(sources)} 未达标 "
              f"(失败率 {fail_ratio:.0%}, 验证码触发率 {rate:.0%}), "
              + ("尝试下一个备用源..." if src_idx < len(sources) - 1 else "无更多备用源"))


def run_batch(url_list, threads=2, sort_chapters=True, resume=True,
              show_progress=True, output_dir=None, delay=1.0, stop_event=None):
    """批量抓取多本书 (书级并行)。

    方案说明:
      - 每本书独立抓取任务 (独立 spider/输出文件), 互不干扰
      - 书级并发: 多本书并行抓取 (默认2本), 速度随书数线性提升
      - 同域限流保护: 同一站点的书最多 1 本并行, 避免触发站点验证码/限流
      - 结束输出汇总报告: 每本书 状态/章节数/耗时
      - stop_event: threading.Event, 置位时不再提交新任务 (已运行任务自然结束)

    Args:
        url_list: 目录页 URL 列表
        threads: 同时抓取的书数 (1=串行)
        output_dir: 输出目录 (None=默认 抓取结果/)
        stop_event: 停止事件 (GUI 停止按钮使用)
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from collections import defaultdict
    from urllib.parse import urlparse

    # 调试日志: 批量入口
    print(f"[调试] 批量抓取开始: {len(url_list)} 本书, 并发 {threads}, 延迟 {delay}")

    # 同域分组 (限流保护: 同域最多1本并行)
    domain_map = defaultdict(list)
    for u in url_list:
        host = urlparse(u).netloc
        domain_map[host].append(u)
    print(f"[批量] 共 {len(url_list)} 本书, {len(domain_map)} 个站点, 书级并发 {threads}")

    def _crawl_one(url):
        t0 = time.time()
        try:
            # 输出到独立文件: 书级并发各自写文件, 无冲突
            run_crawl(url, mode="full", sort_chapters=sort_chapters,
                      output_dir=output_dir, resume=resume,
                      show_progress=show_progress, threads=1, delay=delay,
                      stop_event=stop_event)
            return url, '✅ 完成', time.time() - t0, None
        except Exception as e:
            return url, f'❌ 失败: {str(e)[:80]}', time.time() - t0, None

    # 同域信号量: 每个域名最多1个并发任务
    semaphores = {host: __import__('threading').Semaphore(1) for host in domain_map}
    results = []
    with ThreadPoolExecutor(max_workers=max(1, threads)) as pool:
        futures = {}
        for host, urls in domain_map.items():
            for u in urls:
                if stop_event is not None and stop_event.is_set():
                    print("[批量] ⚠️ 已收到停止信号, 不再提交新任务")
                    break
                # 包装: 同域信号量保护 (同一站点串行)
                def _guarded(u=u, host=host):
                    with semaphores[host]:
                        return _crawl_one(u)
                futures[pool.submit(_guarded)] = u
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append((futures[fut], f'❌ 异常: {str(e)[:80]}', 0, None))

    # 汇总报告
    print("\n========== 批量抓取汇总 ==========")
    for url, status, dur, _ in results:
        print(f"  {status} [{dur:.0f}秒] {url}")
    ok = sum(1 for _, st, _, _ in results if '✅' in st)
    print(f"===================================")
    print(f"[批量] 完成 {ok}/{len(results)} 本")
    return results


def _parse_batch_opts(argv, start_idx):
    """解析批量模式的公共参数: --threads/--no-resume/--no-progress/--output-dir/--delay

    Args:
        argv: sys.argv 列表
        start_idx: 从哪个位置开始解析

    Returns:
        dict: {threads, resume, show_progress, output_dir, delay}
    """
    opts = {'threads': 2, 'resume': True, 'show_progress': True,
            'output_dir': None, 'delay': 1.0}
    i = start_idx
    while i < len(argv):
        arg = argv[i]
        if arg == "--threads":
            try:
                opts['threads'] = max(1, min(int(argv[i + 1]), 8))
            except (ValueError, IndexError):
                print("⚠️ --threads 后需要数字")
                exit(2)
            i += 1
        elif arg == "--no-resume":
            opts['resume'] = False
        elif arg == "--no-progress":
            opts['show_progress'] = False
        elif arg == "--output-dir":
            if i + 1 < len(argv):
                opts['output_dir'] = argv[i + 1]
                i += 1
        elif arg == "--delay":
            try:
                opts['delay'] = max(0.0, float(argv[i + 1]))
            except (ValueError, IndexError):
                print("⚠️ --delay 后需要数字")
                exit(2)
            i += 1
        elif not arg.startswith('--'):
            pass  # URL 参数, 跳过
        else:
            print(f"⚠️ 未知参数: {arg}")
            exit(2)
        i += 1
    return opts


if __name__ == "__main__":
    import sys

    # ===== CLI 模式日志落盘: 所有 print 同时写入 日志/YYYY-MM-DD.log =====
    # GUI 模式由 task_manager.TaskLogRedirector 统一落盘, 此处仅 CLI 生效
    try:
        import 日志 as _app_log

        class _CliLogStdout:
            """CLI stdout 包装: 原样输出 + 逐行写日志文件"""

            def __init__(self):
                self._orig = sys.stdout

            def write(self, text):
                try:
                    self._orig.write(text)
                except Exception:
                    pass
                for line in text.split('\n'):
                    if line.strip():
                        try:
                            _app_log.info("CLI", line.strip())
                        except Exception:
                            pass

            def flush(self):
                try:
                    self._orig.flush()
                except Exception:
                    pass

            def isatty(self):
                return False

        if not isinstance(sys.stdout, _CliLogStdout):
            sys.stdout = _CliLogStdout()
    except Exception:
        pass

    # 命令行用法:
    #   python 爬虫.py                              # 交互式菜单
    #   python 爬虫.py <URL>                        # 完整抓取(默认排序+断点续传+进度条)
    #   python 爬虫.py <URL> --list                  # 只查看章节列表
    #   python 爬虫.py <URL> --test                  # 快速测试
    #   python 爬虫.py <URL> --no-sort               # 禁用排序
    #   python 爬虫.py <URL> --no-resume             # 禁用断点续传(从头抓)
    #   python 爬虫.py <URL> --no-progress           # 禁用进度条
    #   python 爬虫.py <URL> --output-dir <目录>      # 自定义输出目录
    #   python 爬虫.py <URL> --start 10 --end 20     # 自定义章节区间
    #   python 爬虫.py <URL> --threads N              # 并发线程数 (1=串行, 3=3线程)
    #   python 爬虫.py <URL> --delay N                # 章节间间隔秒数 (如 0.2)
    #   python 爬虫.py <URL> --fast                   # 快速模式 (4线程+0.2秒间隔)
    #   python 爬虫.py <URL> --no-sort --test        # 组合使用
    #   python 爬虫.py --batch books.txt [--threads 2]  # 批量抓取 (每行一个URL)
    #   python 爬虫.py <URL1> <URL2> <URL3> [--threads 2]  # 多本书批量抓取
    if len(sys.argv) > 1 and sys.argv[1] not in ("-h", "--help"):
        # ===== 批量模式: --batch 清单文件 或 多个 URL 参数 =====
        if sys.argv[1] == "--batch":
            if len(sys.argv) < 3:
                print("⚠️ --batch 后需要清单文件路径 (每行一个小说URL)")
                exit(2)
            batch_file = sys.argv[2]
            if not os.path.exists(batch_file):
                print(f"⚠️ 批量清单文件不存在: {batch_file}")
                exit(2)
            opts = _parse_batch_opts(sys.argv, 3)
            urls = [ln.strip() for ln in open(batch_file, encoding='utf-8')
                    if ln.strip() and not ln.strip().startswith('#')]
            print(f"[批量] 从 {batch_file} 加载 {len(urls)} 个小说URL")
            if urls:
                run_batch(urls, threads=opts['threads'], resume=opts['resume'],
                          show_progress=opts['show_progress'],
                          output_dir=opts['output_dir'], delay=opts['delay'])
            exit(0)

        # 收集所有非选项参数作为 URL (支持一次抓多本)
        # 排除裸数字参数 (如 --start 1 --end 3 中的 1/3, --threads 5 中的 5),
        # 避免被误当成附加 URL 而进入批量模式
        _is_numeric_arg = lambda a: bool(re.fullmatch(r'\d+(\.\d+)?', a))
        url_args = [a for a in sys.argv[1:]
                    if not a.startswith('--') and not _is_numeric_arg(a)]
        if len(url_args) > 1:
            opts = _parse_batch_opts(sys.argv, 1)
            run_batch(url_args, threads=opts['threads'], resume=opts['resume'],
                      show_progress=opts['show_progress'],
                      output_dir=opts['output_dir'], delay=opts['delay'])
            exit(0)

        catalog_url = sys.argv[1].strip()
        mode = "full"
        sort_chapters = True
        resume = True
        show_progress = True
        output_dir_arg = None
        chapter_range_arg = None
        threads_arg = 1
        delay_arg = 1.0
        i = 2
        argv = sys.argv
        while i < len(argv):
            arg = argv[i]
            if arg == "--list":
                mode = "list"
            elif arg == "--test":
                mode = "test"
            elif arg == "--no-sort":
                sort_chapters = False
            elif arg == "--sort":
                sort_chapters = True
            elif arg == "--no-resume":
                resume = False
            elif arg == "--resume":
                resume = True
            elif arg == "--no-progress":
                show_progress = False
            elif arg == "--progress":
                show_progress = True
            elif arg == "--fast":
                threads_arg = 4
                delay_arg = 0.2
            elif arg == "--threads":
                if i + 1 < len(argv):
                    try:
                        threads_arg = max(1, min(int(argv[i + 1]), 16))
                    except ValueError:
                        print("⚠️ --threads 后必须是数字")
                        exit(2)
                    i += 1
                else:
                    print("⚠️ --threads 后缺少线程数")
                    exit(2)
            elif arg == "--delay":
                if i + 1 < len(argv):
                    try:
                        delay_arg = max(0.0, float(argv[i + 1]))
                    except ValueError:
                        print("⚠️ --delay 后必须是数字")
                        exit(2)
                    i += 1
                else:
                    print("⚠️ --delay 后缺少秒数")
                    exit(2)
            elif arg == "--output-dir":
                if i + 1 < len(argv):
                    output_dir_arg = argv[i + 1]
                    i += 1
                else:
                    print("⚠️ --output-dir 后缺少目录参数")
                    exit(2)
            elif arg == "--start":
                if i + 1 < len(argv):
                    try:
                        start_n = int(argv[i + 1])
                        chapter_range_arg = (start_n, chapter_range_arg[1] if chapter_range_arg else start_n)
                    except ValueError:
                        print("⚠️ --start 后必须是数字")
                        exit(2)
                    i += 1
                else:
                    print("⚠️ --start 后缺少章节号")
                    exit(2)
            elif arg == "--end":
                if i + 1 < len(argv):
                    try:
                        end_n = int(argv[i + 1])
                        sr = chapter_range_arg[0] if chapter_range_arg else 1
                        chapter_range_arg = (sr, end_n)
                    except ValueError:
                        print("⚠️ --end 后必须是数字")
                        exit(2)
                    i += 1
                else:
                    print("⚠️ --end 后缺少章节号")
                    exit(2)
            else:
                print(f"⚠️ 未知参数: {arg}")
                exit(2)
            i += 1
        if chapter_range_arg:
            mode = "range"
        run_crawl(catalog_url, mode=mode, sort_chapters=sort_chapters,
                  output_dir=output_dir_arg,
                  resume=resume, show_progress=show_progress,
                  chapter_range=chapter_range_arg,
                  threads=threads_arg, delay=delay_arg)
    else:
        # 帮助信息
        if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
            print("用法:")
            print("  python 爬虫.py                         交互式菜单")
            print("  python 爬虫.py <URL>                   完整抓取(默认排序+断点续传+进度条)")
            print("  python 爬虫.py <URL> --list            只查看章节列表")
            print("  python 爬虫.py <URL> --test            快速测试(第1章前2页)")
            print("  python 爬虫.py <URL> --no-sort         禁用排序")
            print("  python 爬虫.py <URL> --no-resume       禁用断点续传(从头开始)")
            print("  python 爬虫.py <URL> --no-progress     禁用进度条")
            print("  python 爬虫.py <URL> --output-dir <目录>")
            print("                                         自定义输出目录 (默认: 项目根/抓取结果)")
            print("  python 爬虫.py <URL> --start N --end M 自定义章节区间 (如 --start 10 --end 20)")
            print("  python 爬虫.py <URL> --threads N       并发抓取线程数 (1=串行, 建议2~6)")
            print("  python 爬虫.py <URL> --delay N         章节间间隔秒数 (如 0.2)")
            print("  python 爬虫.py <URL> --fast            快速模式 (4线程+0.2秒间隔)")
            print("  python 爬虫.py -h / --help             显示帮助")
            exit(0)
        # 交互式菜单
        catalog_url, mode, sort_chapters, resume, show_progress, chapter_range, threads, delay = interactive_menu()
        if catalog_url:
            run_crawl(catalog_url, mode=mode, sort_chapters=sort_chapters,
                      resume=resume, show_progress=show_progress,
                      chapter_range=chapter_range,
                      threads=threads, delay=delay)