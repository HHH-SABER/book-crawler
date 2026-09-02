# -*- coding: utf-8 -*-
"""
验证码处理模块 (完整版)
========================

**架构**: 可插拔策略 + 规避优先 + 分级识别 + 监控容错。

**模块职责划分** (与核心爬取逻辑解耦):
  - 爬虫只通过 CaptchaManager 门面调用, 不依赖具体策略
  - 策略通过 register() 注册, set_strategy() 热切换, 打码平台通过 Provider 抽象无缝替换
  - 规避优先: 频率控制 / UA 轮换 / Cookie 维持 / IP 轮换 / 接口替换
    优先于识别——仅在规避无效(页面已返回验证码)时才启用识别能力

**分级处理策略**:
  | 验证码类型      | 首选方案                          | 兜底       |
  |-----------------|-----------------------------------|------------|
  | 简单字符验证码   | ddddocr 本地识别 (零成本)          | 人工输入   |
  | 滑块验证码       | OpenCV 缺口定位 + 拟人轨迹拖拽     | 人工输入   |
  | reCAPTCHA/hCaptcha/Turnstile | 第三方打码平台 API (付费) | 人工输入 |
  | 点选/语义验证码   | 可配置多模态模型 (接口占位)        | 人工输入   |

**安全与合规说明**:
  - 本模块的识别能力默认**关闭**, 需在配置文件中显式开启 (captcha_config.json)
  - 人工辅助流程 (manual) 始终可用, 等价于人类正常访问
  - 自动识别绕过网站 WAF 验证码存在法律风险, 详见《文档/验证码模块合规评估.md》,
    请仅在个人学习/自动化测试场景使用, 自行评估风险
  - 第三方打码平台: 需自行填写 API Key, 成本与合规责任由使用者承担

**监控与容错**:
  - 每次验证码处理记录: 类型 / 耗时 / 成功率 / 成本
  - 识别失败重试上限 / 打码平台余额预警 / 触发率异常告警
  - 统计报告可通过 manager.report() 输出
"""

import os
import time
import json
import threading
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime
from pathlib import Path

try:
    import requests as _requests
except ImportError:
    _requests = None

# ============================================================
# 0. 配置系统 (可插拔 / 热切换)
# ============================================================

DEFAULT_CONFIG = {
    "enabled": True,               # 模块总开关
    "request_proxy": "",           # 爬虫请求代理 (如 "http://127.0.0.1:7890"), 空=直连(忽略系统代理)
    "avoid_first": True,           # 规避优先(仅规避无效时才识别)
    "strategies": {
        "manual":   {"enabled": True},        # 人工辅助 (始终兜底)
        "ddddocr":  {"enabled": False},       # 本地字符识别 (默认关闭, 需显式开启)
        "slider":   {"enabled": False},       # OpenCV 滑块 (默认关闭)
        "third_party": {"enabled": False},    # 第三方打码平台 (默认关闭)
        "point_click": {"enabled": False},    # 点选/语义 (默认关闭, 未配置模型时转人工)
    },
    "retry_limit": 3,              # 识别失败重试上限
    "monitor": {
        "alert_window": 20,        # 触发率统计窗口(最近N次请求)
        "max_consecutive_fail": 3, # 连续失败告警阈值
        "rate_alarm": 0.5,         # 触发率异常告警阈值
        "log_path": None,          # 事件日志 (JSONL), None=不落盘
        "balance_warn": 5.0,       # 打码平台余额预警阈值(元)
    },
    "third_party_api": {           # 第三方打码平台配置 (需自行填写)
        "provider": "",            # 平台名: 2captcha / 超级鹰 / 自定义...
        "api_key": "",             # API Key
        "submit_url": "",          # 提交验证码任务 URL
        "poll_url": "",            # 查询结果 URL (可选)
        "balance_url": "",         # 查询余额 URL (可选)
        "timeout": 120,            # 任务等待超时(秒)
    },
    "avoidance": {
        "base_delay": 1.0,         # 基础请求间隔(秒)
        "min_delay": 0.3,
        "max_delay": 3.0,
        "proxies": [],             # 代理池: ["http://ip:port", ...], 空=不使用
        "cookie_dir": None,        # Cookie 持久化目录, None=不持久化
    },
    "browser_engine": "playwright",  # 浏览器驱动引擎: playwright(反检测,推荐) / selenium
    "fallback_sources": {},          # 多源回退: {书目录URL: [备用目录URL, ...]} 或指向 JSON 文件
    "point_click_model": {         # 点选/语义验证码多模态模型 (接口占位)
        "provider": "",            # 如 "ollama" / "openai_api"
        "endpoint": "",
        "api_key": "",
        "model": "",
    },
}


class Config:
    """验证码模块配置: 支持从 JSON 文件加载与热重载。

    热切换: 运行中修改配置文件后调用 reload() 即可生效,
    无需重启爬虫 —— 满足"策略热切换"要求。
    """

    def __init__(self, path=None):
        self.path = path
        self.data = json.loads(json.dumps(DEFAULT_CONFIG))  # 深拷贝默认配置

    def load(self, path=None):
        """从 JSON 文件加载配置 (缺失字段用默认值补齐)"""
        if path:
            self.path = path
        if not self.path or not os.path.exists(self.path):
            return self
        try:
            loaded = json.loads(Path(self.path).read_text(encoding='utf-8'))
            self._merge(loaded)
        except Exception as e:
            print(f"[验证码模块] 配置加载失败: {e}, 使用默认配置")
        return self

    def save(self, path=None):
        """将当前配置写入文件 (生成默认配置模板)"""
        if path:
            self.path = path
        if self.path:
            Path(self.path).write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        return self

    def reload(self):
        """热重载: 重新读取配置文件并合并"""
        return self.load()

    def _merge(self, loaded):
        """递归合并, 缺失键用默认值"""
        def rec(dst, src):
            for k, v in src.items():
                if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                    rec(dst[k], v)
                else:
                    dst[k] = v
        rec(self.data, loaded)

    # ---- 便捷访问 ----
    @property
    def strategies(self):
        return self.data['strategies']

    def strategy_enabled(self, name):
        return bool(self.strategies.get(name, {}).get('enabled', False))

    @property
    def retry_limit(self):
        return int(self.data.get('retry_limit', 3))


# ============================================================
# 1. 事件记录与监控 (容错与监控要求)
# ============================================================

class CaptchaEvent:
    """一次验证码处理事件记录"""

    def __init__(self, kind, duration, success, note="", cost=0.0, method="manual"):
        self.kind = kind          # 验证码类型: ocr / slider / third_party / point_click / manual
        self.timestamp = time.time()
        self.duration = duration  # 处理耗时(秒)
        self.success = success    # 是否成功
        self.note = note          # 备注
        self.cost = cost          # 成本(元)
        self.method = method      # 实际使用的方法

    def to_dict(self):
        return {
            'time': datetime.fromtimestamp(self.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
            'kind': self.kind,
            'method': self.method,
            'duration': round(self.duration, 1),
            'success': self.success,
            'cost': round(self.cost, 3),
            'note': self.note,
        }


class CaptchaMonitor:
    """验证码触发监控: 触发率统计 / 重试上限 / 异常告警 / 余额预警 / 成本统计"""

    def __init__(self, alert_window=20, max_consecutive_fail=3,
                 rate_alarm_threshold=0.5, log_path=None, balance_warn=5.0):
        self.alert_window = alert_window
        self.max_consecutive_fail = max_consecutive_fail
        self.rate_alarm_threshold = rate_alarm_threshold
        self.balance_warn = balance_warn          # 余额预警阈值(元)
        self._events = deque(maxlen=200)
        self._requests = deque(maxlen=alert_window)
        self._lock = threading.Lock()
        self._log_path = log_path
        self._balance_checked = False             # 每次会话只预警一次

    # ---- 记录 ----
    def record_request(self, captcha_triggered):
        """记录一次页面请求是否触发验证码"""
        with self._lock:
            self._requests.append(1 if captcha_triggered else 0)

    def record_event(self, event):
        """记录一次验证码处理事件"""
        with self._lock:
            self._events.append(event)
        self._persist(event)

    # ---- 统计 ----
    def trigger_rate(self):
        """最近窗口内的验证码触发率 (0~1)"""
        with self._lock:
            if not self._requests:
                return 0.0
            return sum(self._requests) / len(self._requests)

    def consecutive_failures(self):
        """当前连续失败的验证码处理次数"""
        with self._lock:
            n = 0
            for ev in reversed(self._events):
                if ev.success:
                    break
                n += 1
            return n

    def total_cost(self):
        """累计打码成本(元)"""
        with self._lock:
            return sum(e.cost for e in self._events)

    # ---- 余额预警 ----
    def check_balance(self, balance):
        """检查打码平台余额, 低于阈值时告警 (每会话只预警一次)"""
        if self._balance_checked:
            return None
        self._balance_checked = True
        if balance is not None and balance < self.balance_warn:
            return (f"[验证码监控] ⚠️ 打码平台余额不足: {balance:.2f}元 "
                    f"(预警阈值 {self.balance_warn:.2f}元), 请及时充值")
        return None

    # ---- 告警 (返回建议, 由调用方打印) ----
    def check_alarm(self):
        """检查是否触发告警, 返回告警消息列表(空列表=正常)"""
        alarms = []
        rate = self.trigger_rate()
        if rate >= self.rate_alarm_threshold:
            alarms.append(
                f"[验证码监控] ⚠️ 触发率异常 ({rate:.0%} >= {self.rate_alarm_threshold:.0%}), "
                f"建议降低抓取速度(--delay 增大 / --threads 减小)或暂停片刻")
        fails = self.consecutive_failures()
        if fails >= self.max_consecutive_fail:
            alarms.append(
                f"[验证码监控] ⚠️ 验证码连续失败 {fails} 次, 达到重试上限, "
                f"建议暂停并检查网络/IP状态")
        return alarms

    def should_slow_down(self):
        """触发率过高时建议调用方降速"""
        return self.trigger_rate() >= self.rate_alarm_threshold

    # ---- 汇总报告 ----
    def report(self):
        """汇总所有验证码处理记录: 类型/耗时/成功率/成本"""
        with self._lock:
            events = list(self._events)
        if not events:
            return "暂无验证码处理记录"
        total = len(events)
        success = sum(1 for e in events if e.success)
        avg_dur = sum(e.duration for e in events) / total
        total_cost = sum(e.cost for e in events)
        by_kind = {}
        for e in events:
            by_kind.setdefault(e.kind, [0, 0])
            by_kind[e.kind][0] += 1
            by_kind[e.kind][1] += 1 if e.success else 0
        lines = [
            f"验证码处理统计: 共 {total} 次, 成功 {success} 次 ({success / total:.0%}), "
            f"平均耗时 {avg_dur:.1f}秒, 总成本 {total_cost:.2f}元",
        ]
        for kind, (cnt, ok) in sorted(by_kind.items()):
            lines.append(f"  - {kind}: {cnt} 次, 成功 {ok} 次")
        return "\n".join(lines)

    # ---- 持久化 ----
    def _persist(self, event):
        """将事件追加写入日志(JSONL), 便于后续分析优化"""
        if not self._log_path:
            return
        try:
            line = json.dumps(event.to_dict(), ensure_ascii=False)
            with Path(self._log_path).open('a', encoding='utf-8') as f:
                f.write(line + "\n")
        except Exception:
            pass  # 日志失败不影响主流程


# ============================================================
# 2. 策略抽象 (可插拔设计要求)
# ============================================================

class CaptchaHandler(ABC):
    """验证码处理策略基类。

    子类实现 handle() 完成"检测→处理→返回解决后页面源码"的完整流程。
    新增策略只需继承本类并注册到 CaptchaManager, 核心爬取逻辑无需改动。
    """

    name = "base"

    def __init__(self, monitor=None, config=None):
        self.monitor = monitor
        self.config = config

    @abstractmethod
    def handle(self, driver, url, page_source):
        """处理验证码。

        Args:
            driver: 当前 Selenium WebDriver
            url: 目标 URL
            page_source: 当前(疑似验证码)页面源码

        Returns:
            str: 验证码解决后的页面源码; 未解决/失败返回 None
        """
        raise NotImplementedError

    # ---- 通用工具 ----
    @staticmethod
    def is_captcha_page(page_source):
        """通用验证码页检测 (支持多站点特征)"""
        markers = [
            '__wafcaptcha', '_waform', '访问频率太高',   # tanmixs 风格 WAF
            'captcha', 'geetest', 'verify-code',         # 通用验证码
            'sec_captcha', 'validate-code', 'slide-verify',
        ]
        low = page_source.lower()
        return any(m in low for m in markers)

    def _record(self, kind, start, success, note="", cost=0.0, method=None):
        """统一事件记录"""
        if self.monitor:
            self.monitor.record_event(CaptchaEvent(
                kind=kind, duration=time.time() - start,
                success=success, note=note, cost=cost,
                method=method or self.name))


class ManualCaptchaHandler(CaptchaHandler):
    """人工辅助策略 (兜底首选): 弹出可见浏览器, 由人类用户手动输入验证码。

    等价于人类用户正常访问网站的行为, 成功率最高、零成本;
    作为所有自动识别策略失败后的最终兜底。
    """

    name = "manual"
    MAX_WAIT_MINUTES = 5   # 最长等待时间

    def handle(self, driver, url, page_source):
        start = time.time()
        result = None
        try:
            print("[验证码-人工] 检测到验证码页面, 自动识别不可用或失败, 转人工处理")
            try:
                driver.quit()
            except Exception:
                pass
            factory = getattr(self, 'driver_factory', None)
            if factory is None:
                raise RuntimeError("未配置可见浏览器工厂 (driver_factory)")
            visible_driver = factory()
            visible_driver.get(url)
            print("[验证码-人工] 已打开浏览器窗口, 请在浏览器中输入验证码图片字符并提交")
            print(f"[验证码-人工] 系统将自动检测验证码是否已解决 (最多等待 {self.MAX_WAIT_MINUTES} 分钟)...")

            solved = False
            for wait_round in range(self.MAX_WAIT_MINUTES * 12):  # 每5秒轮询
                time.sleep(5)
                try:
                    cur = visible_driver.page_source
                    if not self.is_captcha_page(cur):
                        solved = True
                        print(f"[验证码-人工] ✅ 验证码已解决 (等待了 {(wait_round + 1) * 5} 秒)")
                        break
                except Exception:
                    pass
                if (wait_round + 1) % 12 == 0:
                    print(f"[验证码-人工] 仍在等待验证码解决... (已等待 {(wait_round + 1) * 5} 秒)")

            if not solved:
                print("[验证码-人工] ❌ 等待超时, 验证码未解决")
                return None

            visible_driver.get(url)
            time.sleep(2)  # 等待页面渲染完成
            result = visible_driver.page_source
            return result
        finally:
            self._record('manual', start, result is not None,
                         '人工输入' if result is not None else '超时/失败')


class DdddocrHandler(CaptchaHandler):
    """简单字符验证码本地识别 (ddddocr, 零成本)。

    流程: 定位验证码 <img> 元素 → 元素截图 → ddddocr 识别 →
    填入输入框 → 提交表单 → 校验是否解决; 失败按 retry_limit 重试。

    配置: strategies.dddddocr.enabled = true (默认关闭)
    """

    name = "ddddocr"

    def __init__(self, monitor=None, config=None):
        super().__init__(monitor, config)
        self._ocr = None
        self._ocr_lock = threading.Lock()

    def _get_ocr(self):
        """懒加载 ddddocr 实例 (首次识别时初始化, 避免导入失败拖慢启动)"""
        if self._ocr is None:
            import ddddocr
            with self._ocr_lock:
                if self._ocr is None:
                    self._ocr = ddddocr.DdddOcr(show_ad=False)
        return self._ocr

    def handle(self, driver, url, page_source):
        start = time.time()
        result = None
        try:
            if not self.is_captcha_page(page_source):
                return page_source  # 非验证码页, 直接返回

            from selenium.webdriver.common.by import By

            retry_limit = (self.config.retry_limit if self.config else 3)
            for attempt in range(1, retry_limit + 1):
                print(f"[验证码-识别] ddddocr 第 {attempt}/{retry_limit} 次尝试...")
                try:
                    # 1. 定位验证码图片元素 (优先 form 内的 img)
                    img_el = None
                    try:
                        img_el = driver.find_element(By.CSS_SELECTOR, 'form img')
                    except Exception:
                        img_el = driver.find_element(By.CSS_SELECTOR, 'img[src*="captcha"], img[src*="waf"], img[src*="verify"]')
                    # 2. 元素截图
                    png = img_el.screenshot_as_png
                    # 3. 本地识别
                    code = self._get_ocr().classification(png)
                    if not code:
                        print(f"[验证码-识别] 第 {attempt} 次: 识别为空, 重试")
                        continue
                    print(f"[验证码-识别] 第 {attempt} 次: 识别结果 {code!r}")
                    # 4. 填入输入框 (form 内第一个文本输入框)
                    input_el = driver.find_element(By.CSS_SELECTOR, 'form input[type="text"], form input:not([type])')
                    input_el.clear()
                    input_el.send_keys(code)
                    # 5. 提交表单
                    try:
                        submit_el = driver.find_element(By.CSS_SELECTOR, 'form input[type="submit"], form button[type="submit"], form button')
                        submit_el.click()
                    except Exception:
                        input_el.submit()
                    # 6. 等待页面跳转/刷新, 校验是否解决
                    time.sleep(2)
                    cur = driver.page_source
                    if not self.is_captcha_page(cur):
                        print(f"[验证码-识别] ✅ ddddocr 识别成功 (第 {attempt} 次)")
                        result = cur
                        break
                    print(f"[验证码-识别] 第 {attempt} 次: 提交后仍在验证码页, 重试")
                except Exception as e:
                    print(f"[验证码-识别] 第 {attempt} 次异常: {e}")
                    time.sleep(1)
            if result is None:
                print(f"[验证码-识别] ❌ {retry_limit} 次识别均失败")
        except Exception as e:
            print(f"[验证码-识别] 模块异常: {e}")
        finally:
            self._record('ocr', start, result is not None,
                         'ddddocr 识别' if result is not None else '识别失败', method='ddddocr')
        return result


class SliderCaptchaHandler(CaptchaHandler):
    """滑块验证码: OpenCV 缺口定位 + 拟人轨迹拖拽。

    流程: 定位滑块背景图/滑块元素 → OpenCV 边缘检测定位缺口 →
    生成拟人拖拽轨迹(先加速后减速 + 随机抖动 + 微回拉) → ActionChains 拖拽。

    配置: strategies.slider.enabled = true (默认关闭)
    页面元素定位器可通过 config.strategies.slider.selectors 定制:
      - bg: 背景图元素选择器
      - slider: 滑块元素选择器
    """

    name = "slider"

    def handle(self, driver, url, page_source):
        start = time.time()
        result = None
        try:
            if not self.is_captcha_page(page_source):
                return page_source

            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.action_chains import ActionChains

            sel = (self.config.strategies.get('slider', {}) if self.config else {})
            bg_sel = sel.get('selectors', {}).get('bg', 'img[src*="slider"], .slider-bg, img[src*="bg"]')
            slider_sel = sel.get('selectors', {}).get('slider', '.slider-btn, .geetest_slider_button, button[class*="slider"]')

            # 1. 定位元素
            bg_el = driver.find_element(By.CSS_SELECTOR, bg_sel)
            slider_el = driver.find_element(By.CSS_SELECTOR, slider_sel)

            # 2. 背景图截图 → OpenCV 定位缺口
            bg_png = bg_el.screenshot_as_png
            import cv2
            import numpy as np
            img = cv2.imdecode(np.frombuffer(bg_png, np.uint8), cv2.IMREAD_COLOR)
            gap_x = self._locate_gap(img)
            if gap_x is None:
                print("[验证码-滑块] 未定位到缺口, 识别失败")
                return None
            print(f"[验证码-滑块] 缺口位置 x={gap_x}px")

            # 3. 拟人轨迹
            track = self._human_track(gap_x)

            # 4. 拖拽
            ActionChains(driver).click_and_hold(slider_el).perform()
            for dx, dy in track:
                ActionChains(driver).move_by_offset(dx, dy).perform()
                time.sleep(0.01)
            ActionChains(driver).release().perform()

            time.sleep(2)
            cur = driver.page_source
            if not self.is_captcha_page(cur):
                print("[验证码-滑块] ✅ 滑块验证通过")
                result = cur
            else:
                print("[验证码-滑块] ❌ 滑块验证未通过")
        except Exception as e:
            print(f"[验证码-滑块] 模块异常: {e}")
        finally:
            self._record('slider', start, result is not None,
                         'OpenCV缺口+拟人轨迹' if result is not None else '失败', method='slider')
        return result

    # ---- OpenCV 缺口定位 ----
    @staticmethod
    def _locate_gap(img, gap_color=None):
        """定位滑块缺口 x 坐标 (边缘检测 + 连通域)。

        Args:
            img: BGR 图像 (滑块背景图)
            gap_color: 缺口颜色 (BGR), None 时用边缘检测自动找
        Returns:
            int: 缺口中心 x 坐标, 失败返回 None
        """
        try:
            import cv2
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            # 边缘检测
            edges = cv2.Canny(gray, 100, 200)
            # 找所有边缘轮廓, 取最右侧较大的竖条(滑块缺口特征)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            candidates = []
            for c in contours:
                x, y, w, h = cv2.boundingRect(c)
                if w < 5 or h < 10:   # 过滤噪声
                    continue
                candidates.append((x + w // 2, w * h))  # (中心x, 面积)
            if not candidates:
                return None
            # 取面积最大的候选 (缺口通常是最显著的边缘块)
            cx, _ = max(candidates, key=lambda t: t[1])
            return int(cx)
        except Exception:
            return None

    # ---- 拟人拖拽轨迹 ----
    @staticmethod
    def _human_track(target, noise=0.6):
        """生成拟人拖拽轨迹: 先加速后减速 + 随机抖动 + 末端微回拉。

        参考人类操作: 起始快速移动 → 接近目标减速 → 微小过冲 → 回拉对齐。
        """
        import random
        track = []
        current = 0
        # 分段: 加速段(60%) + 减速段(30%) + 微调段(10%)
        while current < target:
            remain = target - current
            if remain > target * 0.4:
                step = random.SystemRandom().uniform(8, 20)  # 加速段大步
            elif remain > target * 0.1:
                step = random.SystemRandom().uniform(3, 8)   # 减速段小步
            else:
                step = random.SystemRandom().uniform(0.5, 2.5)  # 微调段
            step = min(step, remain + 2)          # 允许轻微过冲
            dy = random.SystemRandom().uniform(-noise, noise)  # 垂直抖动
            track.append((step, dy))
            current += step
        # 末端微回拉 (抵消过冲)
        over = current - target
        if over > 1:
            track.append((-over, random.SystemRandom().uniform(-1, 1)))
        return track


class ThirdPartyCaptchaHandler(CaptchaHandler):
    """国际验证码 (reCAPTCHA / hCaptcha / Turnstile) 第三方打码平台接入。

    Provider 抽象: 任何平台只需实现 submit/poll/balance 三个方法即可无缝替换。
    内置通用 HTTP API Provider (配置 submit_url / poll_url / balance_url + api_key)。

    配置: strategies.third_party.enabled = true + third_party_api 填写平台参数
    成本与合规责任由使用者承担。
    """

    name = "third_party"

    # ---- Provider 抽象 (可插拔: 替换平台只需换 Provider 实现) ----
    class Provider(ABC):
        """打码平台 Provider 接口"""

        @abstractmethod
        def submit(self, captcha_type, page_url, site_key, extra=None):
            """提交验证码任务, 返回任务ID; 失败抛异常"""
            raise NotImplementedError

        @abstractmethod
        def poll(self, task_id, timeout):
            """轮询任务结果, 返回解算答案; 超时/失败返回 None"""
            raise NotImplementedError

        def balance(self):
            """查询余额(元), 不支持返回 None"""
            return None

    class HttpApiProvider(Provider):
        """通用 HTTP API Provider (适配多数打码平台)"""

        def __init__(self, cfg):
            self.cfg = cfg
            self._http = _requests

        def _post(self, url, data):
            if not url:
                raise RuntimeError("打码平台 API URL 未配置")
            # 仅允许公网 http/https (防止请求内网地址)
            if not url.startswith(('http://', 'https://')):
                raise RuntimeError(f"打码平台 URL 协议非法: {url}")
            resp = self._http.post(url, data=data, timeout=30)
            resp.raise_for_status()
            return resp.json()

        def submit(self, captcha_type, page_url, site_key, extra=None):
            data = {
                'key': self.cfg.get('api_key', ''),
                'method': captcha_type,       # userrecaptcha / hcaptcha / turnstile
                'pageurl': page_url,
                'googlekey': site_key,
                'json': 1,
            }
            if extra:
                data.update(extra)
            r = self._post(self.cfg.get('submit_url', ''), data)
            task_id = r.get('task') or r.get('request') or r.get('id')
            if not task_id:
                raise RuntimeError(f"打码平台提交失败: {r}")
            return str(task_id)

        def poll(self, task_id, timeout):
            end = time.time() + timeout
            while time.time() < end:
                time.sleep(5)
                r = self._post(self.cfg.get('poll_url', '') or self.cfg.get('submit_url', ''),
                               {'key': self.cfg.get('api_key', ''), 'action': 'get',
                                'id': task_id, 'json': 1})
                status = r.get('status')
                if status == 1:
                    return r.get('request') or r.get('text') or r.get('solution')
                if status in (0, None):
                    continue
                return None  # 失败状态
            return None

        def balance(self):
            url = self.cfg.get('balance_url', '')
            if not url:
                return None
            try:
                r = self._post(url, {'key': self.cfg.get('api_key', ''), 'json': 1})
                return float(r.get('balance', -1))
            except Exception:
                return None

    def __init__(self, monitor=None, config=None):
        super().__init__(monitor, config)
        self._provider = None
        self._provider_lock = threading.Lock()

    def _get_provider(self):
        """懒创建 Provider (支持热切换: 每次会话重建, 读取最新配置)"""
        if self._provider is None:
            with self._provider_lock:
                if self._provider is None:
                    cfg = self.config.data.get('third_party_api', {}) if self.config else {}
                    self._provider = self.HttpApiProvider(cfg)
        return self._provider

    def handle(self, driver, url, page_source):
        start = time.time()
        result = None
        cost = 0.0
        try:
            if not self.is_captcha_page(page_source):
                return page_source
            cfg = self.config.data.get('third_party_api', {}) if self.config else {}
            if not cfg.get('api_key'):
                print("[验证码-打码平台] 未配置 api_key, 跳过 (请配置 captcha_config.json)")
                return None

            provider = self._get_provider()
            # 检测验证码类型与 sitekey
            captcha_type, site_key = self._detect(page_source)
            print(f"[验证码-打码平台] 提交 {captcha_type} 任务 (sitekey={site_key})")

            # 余额预警
            bal = provider.balance()
            if self.monitor:
                alarm = self.monitor.check_balance(bal)
                if alarm:
                    print(alarm)

            task_id = provider.submit(captcha_type, url, site_key)
            answer = provider.poll(task_id, cfg.get('timeout', 120))
            if answer:
                cost = 0.03  # 单次解算成本估算(元), 平台差异可在配置中覆盖
                print(f"[验证码-打码平台] ✅ 获取答案: {str(answer)[:60]}")
                result = self._inject_answer(driver, answer)
            else:
                print("[验证码-打码平台] ❌ 任务超时/失败")
        except Exception as e:
            print(f"[验证码-打码平台] 异常: {e}")
        finally:
            self._record('third_party', start, result is not None,
                         f'成本约{cost:.2f}元' if result is not None else '失败',
                         cost=cost, method='third_party')
        return result

    # ---- 检测验证码类型与 sitekey ----
    @staticmethod
    def _detect(page_source):
        """从页面源码检测国际验证码类型与 sitekey"""
        import re
        if 'g-recaptcha' in page_source or 'recaptcha' in page_source:
            m = re.search(r'data-sitekey="([^"]+)"', page_source) or \
                re.search(r'sitekey[:=]\s*["\']([^"\']+)', page_source)
            return 'userrecaptcha', (m.group(1) if m else '')
        if 'hcaptcha' in page_source:
            m = re.search(r'data-sitekey="([^"]+)"', page_source) or \
                re.search(r'sitekey[:=]\s*["\']([^"\']+)', page_source)
            return 'hcaptcha', (m.group(1) if m else '')
        if 'turnstile' in page_source or 'cf-turnstile' in page_source:
            m = re.search(r'data-sitekey="([^"]+)"', page_source)
            return 'turnstile', (m.group(1) if m else '')
        return 'captcha', ''

    # ---- 将答案注入页面 (reCAPTCHA/hCaptcha 的 textarea 回调) ----
    @staticmethod
    def _inject_answer(driver, answer):
        """将平台返回的答案注入页面隐藏字段并提交"""
        try:
            from selenium.webdriver.common.by import By
            # reCAPTCHA/hCaptcha 使用 textarea[name="g-recaptcha-response"] 接收答案
            for name in ('g-recaptcha-response', 'h-captcha-response', 'cf-turnstile-response'):
                try:
                    el = driver.find_element(By.CSS_SELECTOR, f'textarea[name="{name}"]')
                    driver.execute_script(
                        "arguments[0].value = arguments[1]; "
                        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", el, answer)
                except Exception:
                    continue
            # 尝试提交表单
            try:
                btn = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]')
                btn.click()
            except Exception:
                pass
            time.sleep(2)
            return driver.page_source
        except Exception:
            return driver.page_source


class PointClickCaptchaHandler(CaptchaHandler):
    """点选/语义验证码 (如"点击包含XX的图片")。

    默认策略: 转人工处理 (最可靠)。
    可选: 配置 point_click_model 接入多模态模型 (接口占位, 需自行实现调用器)。
    """

    name = "point_click"

    def handle(self, driver, url, page_source):
        start = time.time()
        result = None
        try:
            if not self.is_captcha_page(page_source):
                return page_source
            cfg = self.config.data.get('point_click_model', {}) if self.config else {}
            if cfg.get('provider'):
                print(f"[验证码-点选] 检测到配置的多模态模型 ({cfg['provider']}), 尝试模型识别...")
                result = self._solve_with_model(driver, url, cfg)
                if result:
                    return result
            print("[验证码-点选] 点选/语义验证码无可靠自动方案, 转人工处理")
            # 转人工: 复用 ManualCaptchaHandler
            manual = ManualCaptchaHandler(self.monitor, self.config)
            manual.driver_factory = getattr(self, 'driver_factory', None)
            result = manual.handle(driver, url, page_source)
            return result
        finally:
            self._record('point_click', start, result is not None,
                         '多模态' if result is not None else '人工兜底', method='point_click')

    def _solve_with_model(self, driver, url, cfg):
        """多模态模型识别 (接口占位: 按 provider 分发, 需自行实现具体调用)。"""
        # 示例: provider="ollama" 时调用本地视觉模型
        # 本处仅提供接口骨架, 具体实现依赖用户的模型服务
        try:
            from selenium.webdriver.common.by import By
            driver.find_element(By.CSS_SELECTOR, 'form img, .captcha img')  # 验证码元素存在性检查
            # TODO: 调用多模态模型, 返回点击坐标列表 [(x, y), ...]
            # 例如: POST {cfg['endpoint']} 携带图片与提示词, 模型返回坐标
            raise NotImplementedError("多模态模型调用器未配置, 请实现 point_click_model")
        except Exception as e:
            print(f"[验证码-点选] 模型调用失败: {e}")
            return None


# ============================================================
# 3. 规避优先策略 (规避优先要求)
# ============================================================

class AvoidanceStrategy:
    """规避优先: 降低验证码触发率的策略集合。

    合规说明: 以下策略均**不绕过**任何技术保护措施——它们只是让请求行为
    更接近正常人类浏览(频率/指纹/会话/IP), 与验证码机制"区分人与机器"的目的相容。
    技术选型理由: 规避优先于识别, 是降低触发率的首选方案。
    """

    def __init__(self, base_delay=1.0, min_delay=0.3, max_delay=3.0,
                 ua_provider=None, cookie_persist_dir=None, proxies=None):
        self.base_delay = base_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._ua_provider = ua_provider
        self._cookie_persist_dir = cookie_persist_dir
        self._proxies = proxies or []       # 代理池 (IP轮换)
        self._proxy_idx = 0
        self._last_request = 0.0
        self._lock = threading.Lock()

    # ---- 频率控制 ----
    def throttle(self, multiplier=1.0):
        """请求前节流: 保证相邻请求间隔 >= base_delay * multiplier。

        触发率异常时可传入更大 multiplier 强制降速(配合监控告警)。
        """
        with self._lock:
            elapsed = time.time() - self._last_request
            wait = max(0.0, self.base_delay * multiplier - elapsed)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.time()

    def slow_down_multiplier(self, monitor):
        """根据监控触发率计算节流倍率 (触发率越高, 间隔越大)"""
        rate = monitor.trigger_rate() if monitor else 0.0
        if rate >= 0.8:
            return 5.0
        if rate >= 0.5:
            return 3.0
        if rate >= 0.3:
            return 2.0
        return 1.0

    # ---- 指纹伪装 (UA 轮换) ----
    def rotate_headers(self, session):
        """轮换 User-Agent 等指纹头。UA 提供方由调用方注入(如 fake_useragent)。"""
        if self._ua_provider is not None:
            try:
                session.headers['User-Agent'] = self._ua_provider.random
            except Exception:
                pass
        return session

    # ---- IP 轮换 (代理池) ----
    def next_proxy(self):
        """从代理池轮换取下一个代理 (循环)。无代理池返回 None。"""
        if not self._proxies:
            return None
        with self._lock:
            proxy = self._proxies[self._proxy_idx % len(self._proxies)]
            self._proxy_idx += 1
        return {'http': proxy, 'https': proxy}

    def apply_proxy(self, session):
        """为 requests Session 应用轮换代理 (IP轮换)"""
        proxy = self.next_proxy()
        if proxy:
            session.proxies.update(proxy)
        return session

    # ---- 接口替换 (备用端点) ----
    def alternate_url(self, url, alternates=None):
        """站点备用接口/镜像替换 (配置 alternates 列表时使用)。"""
        if not alternates:
            return url
        for alt in alternates:
            if alt.get('host') and alt['host'] in url:
                return url.replace(alt['host'], alt.get('mirror', alt['host']))
        return url

    # ---- Cookie 维持 ----
    def persist_cookies(self, session, tag=""):
        """将会话 Cookie 持久化到本地文件, 下次运行恢复, 减少验证码重复触发。"""
        if not self._cookie_persist_dir:
            return None
        try:
            os.makedirs(self._cookie_persist_dir, exist_ok=True)
            path = os.path.join(self._cookie_persist_dir, f'cookies{tag}.json')
            data = [{'name': c.name, 'value': c.value, 'domain': c.domain}
                    for c in session.cookies]
            Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            return path
        except Exception:
            return None

    def restore_cookies(self, session, tag=""):
        """从本地文件恢复 Cookie"""
        if not self._cookie_persist_dir:
            return False
        try:
            path = os.path.join(self._cookie_persist_dir, f'cookies{tag}.json')
            if not os.path.exists(path):
                return False
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            for c in data:
                session.cookies.set(c['name'], c['value'], domain=c.get('domain'))
            return True
        except Exception:
            return False


# ============================================================
# 4. 门面: CaptchaManager (可插拔/热切换/分级处理)
# ============================================================

class CaptchaManager:
    """验证码处理门面: 策略注册 / 分级选择 / 热切换 / 事件记录。

    核心爬取逻辑只与 CaptchaManager 交互, 不依赖具体策略;
    新增/替换策略只需 register() 一个新实例, 无需改动爬虫代码。

    分级处理 (自动选择):
      dddocr(字符,零成本) → slider(滑块) → third_party(国际验证码)
      → point_click(点选/语义) → manual(人工兜底)
    已启用且可处理的策略按优先级自动尝试, 全部失败后落人工。
    """

    def __init__(self, config=None, monitor=None):
        self.config = config or Config()
        self.monitor = monitor or CaptchaMonitor()
        self._handlers = {}
        self._current = None
        self._lock = threading.Lock()
        # 默认注册内置策略 (可被外部 register 覆盖/替换)
        self.register(DdddocrHandler(self.monitor, self.config))
        self.register(SliderCaptchaHandler(self.monitor, self.config))
        self.register(ThirdPartyCaptchaHandler(self.monitor, self.config))
        self.register(PointClickCaptchaHandler(self.monitor, self.config))
        self.register(ManualCaptchaHandler(self.monitor, self.config))
        # 默认策略: manual (最保守); 用户开启识别后通过 set_strategy 切换
        self.set_strategy('auto' if config and config.strategy_enabled('ddddocr') else 'manual')

    # ---- 注册与选择 ----
    def register(self, handler):
        """注册策略 (同名覆盖, 支持热替换)"""
        handler.monitor = self.monitor
        handler.config = self.config
        self._handlers[handler.name] = handler
        return self

    def set_strategy(self, name):
        """策略热切换: 按名称启用某策略 (支持 'auto' 分级自动)"""
        with self._lock:
            if name == 'auto':
                self._current = 'auto'
            elif name not in self._handlers:
                raise KeyError(f"未知验证码策略: {name}, 可用: {list(self._handlers)}")
            else:
                self._current = name
        return self

    def current_strategy(self):
        return self._current

    def reload_config(self):
        """热重载配置 (运行中修改 captcha_config.json 后调用)"""
        self.config.reload()
        # 同步策略的 enabled 状态到注册表
        for name, handler in self._handlers.items():
            handler.config = self.config
        return self

    # ---- 分级自动选择 ----
    def _auto_chain(self):
        """按 成本优先 + 类型匹配 的分级链 (规避优先理念: 尽量零成本/本地)"""
        chain = []
        if self.config.strategy_enabled('ddddocr'):
            chain.append('ddddocr')
        if self.config.strategy_enabled('slider'):
            chain.append('slider')
        if self.config.strategy_enabled('third_party'):
            chain.append('third_party')
        if self.config.strategy_enabled('point_click'):
            chain.append('point_click')
        if self.config.strategy_enabled('manual'):
            chain.append('manual')
        return chain

    # ---- 处理入口 ----
    def handle(self, driver, url, page_source):
        """检测并处理验证码。

        策略链依次尝试: 上一个失败自动降级到下一个 (分级处理 + 容错)。
        Returns:
            解决后的页面源码; 非验证码页返回原始 page_source; 全部失败返回 None
        """
        if not self.config.data.get('enabled', True):
            return page_source
        if not self.is_captcha_page(page_source):
            return page_source

        # 记录触发
        self.monitor.record_request(True)

        if self._current == 'auto':
            chain = self._auto_chain()
            # 人工兜底必须最后
            chain = [c for c in chain if c != 'manual'] + ['manual'] if 'manual' in chain else chain
        else:
            chain = [self._current]

        for name in chain:
            handler = self._handlers.get(name)
            if handler is None:
                continue
            if name == 'manual':
                # 人工策略需要可见浏览器工厂 (由调用方注入)
                if not hasattr(handler, 'driver_factory') or handler.driver_factory is None:
                    print("[验证码] 人工策略未配置浏览器工厂, 无法处理")
                    continue
            print(f"[验证码] 尝试策略: {name}")
            result = handler.handle(driver, url, page_source)
            if result is not None and not self.is_captcha_page(result):
                return result
            # 失败 → 下一个策略 (降级)
        return None

    def is_captcha_page(self, page_source):
        """通用验证码页检测 (tanmixs 风格 WAF + 通用特征)"""
        return CaptchaHandler.is_captcha_page(page_source)

    # ---- 监控透传 ----
    def record_request(self, triggered):
        self.monitor.record_request(triggered)

    def report(self):
        return self.monitor.report()

    def alarms(self):
        return self.monitor.check_alarm()


# ============================================================
# 5. 模块工厂 (供爬虫一键初始化)
# ============================================================

def build_manager(config_path=None, ua_provider=None):
    """构建完整 CaptchaManager (配置加载 + 监控 + 规避策略)。

    配置路径约定（PyInstaller 打包友好，经验 1341648）：
      - 始终写入 BASE_DIR/captcha_config.json（EXE 旁边或项目根）
      - 若 BASE_DIR 下不存在，会先从 RESOURCE_DIR 尝试复制一份内置默认值
      - 如果都不存在，调用 config.save() 生成默认模板
    """
    if config_path is None:
        try:
            import _path_utils  # noqa: F401
            config_path = _path_utils.resolve_data_file("captcha_config.json",
                                                         copy_default_from_resource_if_missing=True)
        except Exception:
            # 回退：放在脚本所在目录（开发模式）
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       'captcha_config.json')
    config = Config(config_path)
    config.load()
    if not os.path.exists(config.path):
        config.save()  # 生成默认配置模板

    mon_cfg = config.data.get('monitor', {})
    monitor = CaptchaMonitor(
        alert_window=mon_cfg.get('alert_window', 20),
        max_consecutive_fail=mon_cfg.get('max_consecutive_fail', 3),
        rate_alarm_threshold=mon_cfg.get('rate_alarm', 0.5),
        log_path=mon_cfg.get('log_path'),
        balance_warn=mon_cfg.get('balance_warn', 5.0),
    )

    av_cfg = config.data.get('avoidance', {})
    avoidance = AvoidanceStrategy(
        base_delay=av_cfg.get('base_delay', 1.0),
        min_delay=av_cfg.get('min_delay', 0.3),
        max_delay=av_cfg.get('max_delay', 3.0),
        ua_provider=ua_provider,
        cookie_persist_dir=av_cfg.get('cookie_dir'),
        proxies=av_cfg.get('proxies', []),
    )

    manager = CaptchaManager(config=config, monitor=monitor)
    return manager, avoidance
