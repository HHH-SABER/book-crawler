# -*- coding: utf-8 -*-
"""
反检测浏览器驱动适配层 (Playwright 实现)
========================================

**用途**: 为爬虫提供与 Selenium 兼容接口的 Playwright 驱动,
配合 stealth 初始化脚本消除自动化指纹, 显著降低 WAF 验证码触发率
(规避优先原则: 让验证码不出现, 而非出现后去识别)。

**设计**:
  - 接口兼容: 实现了爬虫/验证码模块用到的 Selenium 方法子集
    (get / page_source / find_element / execute_script / quit 等),
    使核心代码无需改动即可切换引擎
  - 反检测: 页面加载前注入 stealth 脚本 (webdriver 标记/指纹伪装)
  - 复用系统 Chrome (channel='chrome'), 无需下载浏览器
  - 懒加载: 模块导入不启动浏览器, 首次 get() 才启动

**与 Selenium 的差异处理**:
  - WebDriverWait → 使用内置 wait_for() / wait_for_selector()
  - ActionChains 拖拽 → 使用内置 drag_track() (拟人轨迹分步执行)
  - element.clear()/send_keys()/click() → PwElement 包装兼容
"""

import time

# ============================================================
# stealth 初始化脚本 (在页面任何脚本执行前注入)
# ============================================================
STEALTH_JS = r"""
// 1. 移除 webdriver 自动化标记
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
// 2. 伪造 Chrome 插件特征 (自动化浏览器通常无插件)
Object.defineProperty(navigator, 'plugins', {
  get: () => {
    const data = [
      {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
      {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
      {name: 'Native Client', filename: 'internal-nacl-plugin'},
    ];
    data.item = (i) => data[i];
    data.namedItem = (n) => data.find(x => x.name === n) || null;
    data.refresh = () => {};
    Object.defineProperty(data, 'length', {value: data.length});
    return data;
  }
});
// 3. 伪造 languages / UA 相关属性
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
// 4. 伪造 permissions (自动化环境权限行为异常)
const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
if (originalQuery) {
  window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
      ? Promise.resolve({state: Notification.permission})
      : originalQuery(parameters)
  );
}
// 5. 隐藏 CDP 相关痕迹
if (window.cdc_) delete window.cdc_;
"""


# ============================================================
# 元素包装 (兼容 Selenium WebElement 常用接口)
# ============================================================

class PwElement:
    """Playwright Locator 包装: 提供爬虫/验证码模块所需接口"""

    def __init__(self, locator):
        self._loc = locator

    # ---- 截图 (验证码识别用) ----
    @property
    def screenshot_as_png(self):
        return self._loc.screenshot()

    # ---- 文本操作 ----
    def clear(self):
        self._loc.fill('')
        return self

    def send_keys(self, text):
        self._loc.fill(text)
        return self

    def click(self):
        self._loc.click(timeout=8000)
        return self

    def submit(self):
        """提交所在表单"""
        self._loc.evaluate("(el) => { const f = el.closest('form'); if (f) f.submit(); }")
        return self

    def get_attribute(self, name):
        return self._loc.get_attribute(name)

    @property
    def text(self):
        return self._loc.inner_text()

    @property
    def is_visible(self):
        try:
            return self._loc.is_visible()
        except Exception:
            return False

    # ---- 拖拽 (滑块) ----
    def drag_track(self, driver, track):
        """按拟人轨迹拖拽本元素"""
        driver.drag_track(self._loc, track)


# ============================================================
# Playwright 驱动 (Selenium 兼容子集)
# ============================================================

class PlaywrightDriver:
    """Playwright 驱动的 Selenium 兼容封装

    用法与 Selenium WebDriver 基本一致:
        d = PlaywrightDriver(visible=False)
        d.get(url)
        src = d.page_source
        el = d.find_element('css selector', 'form img')
        png = el.screenshot_as_png
        d.quit()
    """

    def __init__(self, visible=False, user_data_dir=None, timeout=30000):
        """
        Args:
            visible: False=无头模式, True=显示浏览器窗口 (验证码人工处理时)
            user_data_dir: 浏览器用户数据目录 (会话持久化, 复用 Cookie)
            timeout: 页面加载超时(毫秒)
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("未安装 playwright, 请执行: pip install playwright")
        self._pw = sync_playwright().start()
        self._browser = None
        self._context = None
        self._page = None
        self._visible = visible
        self._user_data_dir = user_data_dir
        self._timeout = timeout
        self._started = False

    # ---- 生命周期 ----
    def _ensure_started(self):
        """懒启动浏览器 (首次 get 时)"""
        if self._started:
            return
        from playwright.sync_api import sync_playwright as _sp  # noqa: F401
        launch_args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-gpu',
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-extensions',
        ]
        if self._user_data_dir:
            # 会话持久化必须用 launch_persistent_context (不能通过 args 传 --user-data-dir)
            try:
                self._context = self._pw.chromium.launch_persistent_context(
                    user_data_dir=self._user_data_dir,
                    channel='chrome', headless=not self._visible,
                    args=launch_args,
                    viewport={'width': 800, 'height': 600},
                    user_agent=('Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 '
                                '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'),
                    locale='zh-CN',
                )
            except Exception:
                self._context = self._pw.chromium.launch_persistent_context(
                    user_data_dir=self._user_data_dir,
                    headless=not self._visible, args=launch_args,
                    viewport={'width': 800, 'height': 600},
                    locale='zh-CN',
                )
            self._browser = None
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        else:
            try:
                self._browser = self._pw.chromium.launch(
                    channel='chrome', headless=not self._visible, args=launch_args)
            except Exception:
                self._browser = self._pw.chromium.launch(
                    headless=not self._visible, args=launch_args)
            self._context = self._browser.new_context(
                viewport={'width': 800, 'height': 600},
                user_agent=('Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'),
                locale='zh-CN',
            )
            self._page = self._context.new_page()
        self._page.set_default_timeout(self._timeout)
        # 注入反检测脚本 (stealth)
        self._page.add_init_script(STEALTH_JS)
        self._started = True

    def get(self, url):
        """访问页面 (等待 DOMContentLoaded)"""
        self._ensure_started()
        try:
            self._page.goto(url, wait_until='domcontentloaded', timeout=self._timeout)
        except Exception:
            pass  # 超时/网络错误不阻断, 由调用方检查 page_source
        return self

    # ---- 页面属性 ----
    @property
    def page_source(self):
        self._ensure_started()
        return self._page.content()

    @property
    def current_url(self):
        self._ensure_started()
        return self._page.url

    # ---- 元素查找 (兼容 Selenium By) ----
    def find_element(self, by, value):
        """by: 'css selector' / 'id' / 'tag name' / 'name' (Selenium By 常量字符串)"""
        self._ensure_started()
        css = self._by_to_css(by, value)
        return PwElement(self._page.locator(css).first)

    def find_elements(self, by, value):
        self._ensure_started()
        css = self._by_to_css(by, value)
        return [PwElement(loc) for loc in self._page.locator(css).all()]

    @staticmethod
    def _by_to_css(by, value):
        """Selenium By 常量 → CSS 选择器"""
        b = str(by).lower()
        if 'css' in b:
            return value
        if 'id' in b:
            return f'#{value}'
        if 'tag' in b:
            return value
        if 'name' in b:
            return f'[name="{value}"]'
        if 'class' in b:
            return f'.{value}'
        return value

    # ---- 显式等待 (替代 WebDriverWait) ----
    def wait_for(self, by, value, timeout_ms=20000):
        """等待元素出现 (替代 WebDriverWait + presence_of_element_located)"""
        self._ensure_started()
        css = self._by_to_css(by, value)
        self._page.wait_for_selector(css, timeout=timeout_ms, state='attached')
        return self.find_element(by, value)

    # ---- JS 执行 ----
    def execute_script(self, script, *args):
        self._ensure_started()
        # Selenium 习惯写 "return x", Playwright evaluate 需要表达式;
        # 兼容处理: 剥离单行脚本的 return 前缀
        expr = script
        stripped = expr.lstrip()
        if stripped.startswith('return ') and '\n' not in stripped:
            expr = stripped[len('return '):]
        return self._page.evaluate(expr, *args)

    # ---- 滑块拖拽 (拟人轨迹, 替代 ActionChains) ----
    def drag_track(self, locator_or_el, track):
        """按轨迹序列分步拖拽元素: 每次 move 产生独立鼠标事件,
        更接近真实人类的拖拽行为 (Selenium ActionChains 一次合成全部事件)。"""
        self._ensure_started()
        loc = locator_or_el._loc if isinstance(locator_or_el, PwElement) else locator_or_el
        box = loc.bounding_box()
        if not box:
            raise RuntimeError("无法获取元素位置, 拖拽失败")
        start_x = box['x'] + box['width'] / 2
        start_y = box['y'] + box['height'] / 2
        mouse = self._page.mouse
        mouse.move(start_x, start_y)
        mouse.down()
        time.sleep(0.05)
        x, y = start_x, start_y
        for dx, dy in track:
            x += dx
            y += dy
            mouse.move(x, y)
            time.sleep(0.01)  # 每个事件间隔, 模拟真实事件流
        mouse.up()

    # ---- 关闭 ----
    def quit(self):
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            self._pw.stop()
        except Exception:
            pass
        self._started = False
        self._context = None
        self._browser = None
        self._page = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.quit()


# ============================================================
# 工厂: 统一驱动创建入口
# ============================================================

def create_driver(engine='playwright', visible=False, user_data_dir=None):
    """创建浏览器驱动 (引擎可配置)。

    Args:
        engine: 'playwright' (反检测, 推荐) / 'selenium' (兼容旧流程)
        visible: 是否可见模式 (验证码人工处理时需要)
        user_data_dir: 会话持久化目录

    Returns:
        Selenium WebDriver 或 PlaywrightDriver (接口兼容)
    """
    if engine == 'playwright':
        return PlaywrightDriver(visible=visible, user_data_dir=user_data_dir)
    # 引擎: selenium
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    options = Options()
    if not visible:
        options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--window-size=800,600')
    if user_data_dir:
        options.add_argument(f'--user-data-dir={user_data_dir}')
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30)
    driver.set_script_timeout(30)
    return driver
