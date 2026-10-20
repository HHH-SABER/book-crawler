// 小说爬虫 · 凭据中继 — MV3 service worker (P1, 2026-10-20)
//
// 职责 (与爬虫的分工纪律见 文档/浏览器插件可行性方案.md):
//   ① 从真实浏览器读目标域 Cookie (含 HttpOnly / JS 算出的 —— 这是爬虫拿不到的)
//   ② POST 给本机爬虫 /api/v1/ext/cookies (爬虫写入域 COOKIE 库, 三引擎受益)
//   ③ 每 5 分钟按爬虫侧白名单自动同步一轮 (白名单以爬虫为准)
// 本插件不做解析/不做存储 —— 只是"环境提供者 + 搬运工"。

const 默认端口 = 8760;

async function 取配置() {
  const s = await chrome.storage.local.get(['port', 'token']);
  return { port: s.port || 默认端口, token: s.token || '' };
}

async function 调接口(path, method = 'GET', body) {
  const { port, token } = await 取配置();
  if (!token) throw new Error('还没填 token（点右上角设置，从程序"远控"页复制）');
  const resp = await fetch(`http://127.0.0.1:${port}/api/v1/ext${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    let detail = '';
    try { detail = (await resp.json()).detail || ''; } catch (e) { detail = await resp.text(); }
    throw new Error(detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

async function 推送域名(domain) {
  const cookies = await chrome.cookies.getAll({ domain });
  if (!cookies || cookies.length === 0) throw new Error('这个站点没有可推送的 Cookie');
  return 调接口('/cookies', 'POST', {
    domain,
    cookies: cookies.map((c) => ({
      name: c.name,
      value: c.value,
      expirationDate: c.expirationDate,
    })),
  });
}

// ---- 周期同步: 白名单以爬虫侧为准, 逐域推送 (失败静默, 不打扰用户) ----
chrome.alarms.create('凭据同步', { periodInMinutes: 5 });
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== '凭据同步') return;
  try {
    const wl = await 调接口('/whitelist');
    for (const d of wl.domains || []) {
      try { await 推送域名(d); } catch (e) { /* 单域失败不影响其他域 */ }
    }
  } catch (e) { /* 爬虫没开 / token 未配置: 静默 */ }
});

// ---- popup 消息入口 ----
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === 'ping') {
        sendResponse({ ok: true, data: await 调接口('/ping') });
      } else if (msg.type === 'push') {
        sendResponse({ ok: true, data: await 推送域名(msg.domain) });
      } else if (msg.type === 'whitelist') {
        sendResponse({ ok: true, data: await 调接口('/whitelist') });
      } else if (msg.type === 'addWhitelist') {
        const cur = await 调接口('/whitelist');
        const 新 = Array.from(new Set([...(cur.domains || []), msg.domain]));
        sendResponse({ ok: true, data: await 调接口('/whitelist', 'POST', { domains: 新 }) });
      } else {
        sendResponse({ ok: false, error: '未知消息: ' + msg.type });
      }
    } catch (e) {
      sendResponse({ ok: false, error: String(e.message || e) });
    }
  })();
  return true;
});
