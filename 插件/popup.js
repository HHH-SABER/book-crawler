// popup 逻辑: 当前站域识别 + 推送/白名单 + 设置
let 当前域 = '';

function 设状态(文字, 是错 = false) {
  const el = document.getElementById('status');
  el.textContent = 文字;
  el.className = 'status ' + (是错 ? 'err' : 'ok');
}

function 发消息(msg) {
  return new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve));
}

async function 初始化() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab && tab.url && /^https?:/.test(tab.url)) {
    当前域 = new URL(tab.url).hostname;
  }
  document.getElementById('domain').textContent = 当前域 || '当前标签不是普通网页';

  const s = await chrome.storage.local.get(['port', 'token']);
  document.getElementById('port').value = s.port || 8760;
  document.getElementById('token').value = s.token || '';
}

document.getElementById('push').onclick = async () => {
  if (!当前域) return 设状态('当前标签不是普通网页', true);
  设状态('推送中…');
  const r = await 发消息({ type: 'push', domain: 当前域 });
  if (r && r.ok) 设状态(`✅ 已推送 ${r.data.count} 条 Cookie（${r.data.domain}）`);
  else 设状态('❌ ' + ((r && r.error) || '失败'), true);
};

document.getElementById('add').onclick = async () => {
  if (!当前域) return 设状态('当前标签不是普通网页', true);
  设状态('加入白名单…');
  const r1 = await 发消息({ type: 'addWhitelist', domain: 当前域 });
  if (!r1 || !r1.ok) return 设状态('❌ ' + ((r1 && r1.error) || '加白名单失败'), true);
  设状态('推送中…');
  const r2 = await 发消息({ type: 'push', domain: 当前域 });
  if (r2 && r2.ok) 设状态(`✅ 已加入白名单并推送 ${r2.data.count} 条 Cookie`);
  else 设状态('❌ ' + ((r2 && r2.error) || '推送失败'), true);
};

document.getElementById('save').onclick = async () => {
  const port = parseInt(document.getElementById('port').value, 10) || 8760;
  const token = document.getElementById('token').value.trim();
  await chrome.storage.local.set({ port, token });
  设状态('测试连通…');
  const r = await 发消息({ type: 'ping' });
  if (r && r.ok) 设状态('✅ 已连接小说爬虫，白名单 ' + (r.data.whitelist || []).length + ' 个域');
  else 设状态('❌ 连不上：' + ((r && r.error) || '未知错误') + '（程序开着吗？token 对吗？）', true);
};

初始化();
