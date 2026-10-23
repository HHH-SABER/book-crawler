// popup 逻辑: 抓取当前页面 + 推送/白名单 + 设置
// 2026-10-23 夸克报错修复: 夸克的 chrome.tabs 实现不完整 (部分对象缺 id /
// 直接 reject), 原代码在初始化时未捕获 → 打开 popup 就抛
// "Cannot read properties of undefined (reading 'id')"。现在:
//   · 所有 chrome.* 调用各自 try/catch + 兜底值;
//   · 初始化整体 try/catch, 失败也要让界面可用;
//   · 所有事件处理器外层包 try, 任何异常都落成状态行提示。

let 当前域 = '';
let 当前网址 = '';

function 设状态(文字, 是错 = false) {
  const el = document.getElementById('status');
  if (!el) return;
  el.textContent = 文字;
  el.className = 'status ' + (是错 ? 'err' : 'ok');
}

function 取元素(id) {
  return document.getElementById(id) || null;
}

function 发消息(msg) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(msg, (r) => {
        // 读取 lastError 避免 "Unchecked runtime.lastError" 噪音
        const 错误 = chrome.runtime && chrome.runtime.lastError;
        if (错误) return resolve({ ok: false, error: 错误.message || String(错误) });
        resolve(r);
      });
    } catch (e) {
      resolve({ ok: false, error: String((e && e.message) || e) });
    }
  });
}

async function 取当前标签() {
  // 夸克等浏览器可能: 返回非数组 / 元素缺 url / 直接 reject —— 全部兜住
  try {
    const 结果 = await chrome.tabs.query({ active: true, currentWindow: true });
    const 列表 = Array.isArray(结果) ? 结果 : [];
    return 列表[0] || null;
  } catch (e) {
    return null;
  }
}

async function 初始化() {
  try {
    const tab = await 取当前标签();
    if (tab && tab.url && /^https?:/.test(tab.url)) {
      try {
        当前网址 = tab.url;
        当前域 = new URL(tab.url).hostname;
      } catch (e) {
        当前域 = '';
        当前网址 = '';
      }
    }
    const 域框 = 取元素('domain');
    if (域框) {
      域框.textContent = 当前域 ? `${当前域}\n${当前网址}` : '当前标签不是普通网页';
    }

    let s = {};
    try {
      s = (await chrome.storage.local.get(
        ['port', 'token', 'lastMode', 'lastStart', 'lastEnd'])) || {};
    } catch (e) {
      s = {};
    }
    const 端口框 = 取元素('port');
    const token框 = 取元素('token');
    if (端口框) 端口框.value = s.port || 8760;
    if (token框) token框.value = s.token || '';
    if (s.lastMode === 'range') {
      const 模式 = 取元素('mode');
      const 区间行 = 取元素('rangeRow');
      if (模式) 模式.value = 'range';
      if (区间行) 区间行.style.display = 'flex';
    }
    if (s.lastStart && 取元素('start')) 取元素('start').value = s.lastStart;
    if (s.lastEnd && 取元素('end')) 取元素('end').value = s.lastEnd;
  } catch (e) {
    设状态('⚠️ 初始化异常（' + String((e && e.message) || e) + '），功能可能受限', true);
  }
}

function 绑定(id, 处理器) {
  const el = 取元素(id);
  if (!el) return;
  el.onclick = async (ev) => {
    try {
      await 处理器(ev);
    } catch (e) {
      设状态('❌ ' + String((e && e.message) || e), true);
    }
  };
}

const 模式框 = 取元素('mode');
if (模式框) {
  模式框.onchange = (e) => {
    const 行 = 取元素('rangeRow');
    if (行) 行.style.display = e.target.value === 'range' ? 'flex' : 'none';
  };
}

绑定('crawl', async () => {
  if (!当前网址) return 设状态('当前标签不是普通网页，无法抓取', true);
  const 模式 = (取元素('mode') && 取元素('mode').value) || 'full';
  const 起 = parseInt((取元素('start') || {}).value, 10) || 0;
  const 止 = parseInt((取元素('end') || {}).value, 10) || 0;
  if (模式 === 'range' && (!起 || !止 || 止 < 起)) {
    return 设状态('章节区间要填两个正整数，且结束 ≥ 开始', true);
  }
  try {
    await chrome.storage.local.set({
      lastMode: 模式, lastStart: 起 || '', lastEnd: 止 || '',
    });
  } catch (e) {
    /* 记不住偏好不影响本次抓取 */
  }

  设状态('正在交给小说爬虫…');
  const r = await 发消息({ type: 'crawl', url: 当前网址, mode: 模式, start: 起, end: 止 });
  if (r && r.ok) {
    设状态((r.data && r.data.唤起)
      ? '✅ 程序未运行，已唤起并开始抓取（看任务列表）'
      : '✅ 已提交抓取任务，切到程序看任务列表');
  } else {
    设状态('❌ ' + ((r && r.error) || '抓取请求失败'), true);
  }
});

绑定('push', async () => {
  if (!当前域) return 设状态('当前标签不是普通网页', true);
  设状态('推送中…');
  const r = await 发消息({ type: 'push', domain: 当前域 });
  if (r && r.ok) 设状态(`✅ 已推送 ${r.data.count} 条 Cookie（${r.data.domain}）`);
  else 设状态('❌ ' + ((r && r.error) || '失败'), true);
});

绑定('add', async () => {
  if (!当前域) return 设状态('当前标签不是普通网页', true);
  设状态('加入白名单…');
  const r1 = await 发消息({ type: 'addWhitelist', domain: 当前域 });
  if (!r1 || !r1.ok) return 设状态('❌ ' + ((r1 && r1.error) || '加白名单失败'), true);
  设状态('推送中…');
  const r2 = await 发消息({ type: 'push', domain: 当前域 });
  if (r2 && r2.ok) 设状态(`✅ 已加入白名单并推送 ${r2.data.count} 条 Cookie`);
  else 设状态('❌ ' + ((r2 && r2.error) || '推送失败'), true);
});

绑定('save', async () => {
  const port = parseInt((取元素('port') || {}).value, 10) || 8760;
  const token = (((取元素('token') || {}).value) || '').trim();
  try {
    await chrome.storage.local.set({ port, token });
  } catch (e) {
    设状态('⚠️ 设置没存上：' + String((e && e.message) || e), true);
    return;
  }
  设状态('测试连通…');
  const r = await 发消息({ type: 'ping' });
  if (r && r.ok) 设状态('✅ 已连接小说爬虫，白名单 ' + (r.data.whitelist || []).length + ' 个域');
  else 设状态('❌ 连不上：' + ((r && r.error) || '未知错误') + '（程序开着吗？token 对吗？）', true);
});

初始化();
