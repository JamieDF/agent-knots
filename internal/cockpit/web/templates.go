package web

// cockpitHTML is the full SPA shell — exact CSS from the mockups,
// canvas 3-panel layout, hash-based routing, SSE event streaming.
// No external dependencies beyond Google Fonts (DM Sans/DM Mono).
const cockpitHTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>agentjam cockpit</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg: oklch(9% 0.005 260);
  --surface: oklch(14% 0.006 260);
  --surface-raised: oklch(18% 0.008 260);
  --surface-hover: oklch(20% 0.008 260);
  --fg: oklch(92% 0.003 260);
  --fg-soft: oklch(78% 0.005 260);
  --muted: oklch(58% 0.012 260);
  --muted-2: oklch(42% 0.012 260);
  --border: oklch(22% 0.006 260);
  --border-subtle: oklch(16% 0.004 260);
  --running: oklch(72% 0.16 155);
  --blocked: oklch(76% 0.14 65);
  --assumed: oklch(76% 0.16 75);
  --info: oklch(68% 0.12 235);
  --done: oklch(64% 0.06 155);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; overflow: hidden; }
body { font-family: 'DM Sans', system-ui, sans-serif; background: var(--bg); color: var(--fg); }
.mono { font-family: 'DM Mono', monospace; font-variant-numeric: tabular-nums; }
a { color: inherit; text-decoration: none; }
button { font-family: inherit; cursor: pointer; border: 0; background: none; color: inherit; }

.topbar { height: 52px; border-bottom: 1px solid var(--border-subtle); display: flex; align-items: center; padding: 0 20px; gap: 24px; background: var(--bg); flex-shrink: 0; z-index: 50; }
.topbar-brand { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; }
.topbar-sep { width: 1px; height: 20px; background: var(--border-subtle); }
.topbar-nav { display: flex; gap: 2px; }
.topbar-nav a { font-size: 13px; color: var(--muted); padding: 5px 10px; border-radius: 6px; }
.topbar-nav a:hover, .topbar-nav a.active { color: var(--fg); background: var(--surface); }
.topbar-meta { display: flex; align-items: center; gap: 18px; font-size: 12px; color: var(--muted); }
.topbar-actions { margin-left: auto; display: flex; gap: 8px; }

.canvas { flex: 1; display: grid; grid-template-columns: 240px 1fr 320px; overflow: hidden; }
.left-panel { border-right: 1px solid var(--border-subtle); overflow-y: auto; padding: 18px 14px; }
.center-panel { overflow-y: auto; padding: 24px 28px; }
.right-panel { border-left: 1px solid var(--border-subtle); overflow-y: auto; padding: 18px; }

.panel-label { font-size: 10px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 10px; }
.panel-item { font-size: 12px; padding: 4px 6px; border-radius: 5px; color: var(--muted); cursor: pointer; display: flex; align-items: center; gap: 6px; }
.panel-item:hover, .panel-item.active { color: var(--fg); background: var(--surface); }
.panel-pip { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.panel-pip.running { background: var(--running); box-shadow: 0 0 6px var(--running); }

.status-pip { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.status-pip.running { background: var(--running); box-shadow: 0 0 8px var(--running); animation: glow 2s ease-in-out infinite; }
@keyframes glow { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
.mode-pill { display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px; border-radius: 99px; font-size: 10px; font-weight: 600; border: 1px solid var(--border-subtle); background: var(--surface); color: var(--muted); }
.mode-pill .pill-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--running); }
.mode-pill.assumed { background: oklch(76% 0.16 75 / 0.1); border-color: oklch(76% 0.16 75 / 0.3); color: var(--assumed); }
.mode-pill.assumed .pill-dot { background: var(--assumed); }

.agent-card { background: var(--surface); border: 1px solid var(--border-subtle); border-radius: 12px; padding: 18px; cursor: pointer; transition: background .15s; margin-bottom: 14px; }
.agent-card:hover { background: var(--surface-raised); border-color: var(--border); }
.agent-card-head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 10px; }
.agent-card-id { font: 12px 'DM Mono', monospace; color: var(--muted-2); display: flex; align-items: center; gap: 8px; }
.agent-card-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; font-size: 12px; color: var(--muted); margin: 8px 0; }
.agent-card-meta span { display: flex; justify-content: space-between; }
.agent-card-meta .val { color: var(--fg-soft); font: 12px 'DM Mono', monospace; }
.agent-card-action { margin-top: 8px; font-size: 12px; color: var(--fg-soft); border-top: 1px solid var(--border-subtle); padding-top: 8px; }

.prose-row { display: flex; gap: 10px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid var(--border-subtle); }
.prose-avatar { width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font: 10px 'DM Mono', monospace; font-weight: 700; flex-shrink: 0; margin-top: 2px; }
.prose-avatar.agent { background: oklch(68% 0.12 235 / 0.15); border: 1px solid oklch(68% 0.12 235 / 0.3); color: var(--info); }
.prose-avatar.thinking { background: var(--surface-raised); border: 1px solid var(--border); color: var(--muted); }
.prose-content { flex: 1; min-width: 0; }
.prose-text { font-size: 13px; line-height: 1.5; color: var(--fg); word-break: break-word; }
.prose-text code { font: 11px 'DM Mono', monospace; background: var(--surface-raised); padding: 1px 4px; border-radius: 3px; }
.prose-thinking-text { font-size: 12px; color: var(--muted); font-style: italic; line-height: 1.5; }
.prose-ts { font: 11px 'DM Mono', monospace; color: var(--muted-2); flex-shrink: 0; padding-top: 3px; }

.tool-card { background: var(--surface); border: 1px solid var(--border-subtle); border-radius: 10px; margin: 6px 0 6px 34px; overflow: hidden; }
.tool-card-head { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--border-subtle); font-size: 12px; }
.tool-icon { width: 22px; height: 22px; border-radius: 5px; display: flex; align-items: center; justify-content: center; font: 10px 'DM Mono', monospace; font-weight: 700; flex-shrink: 0; }
.tool-icon.edit { background: oklch(76% 0.14 65 / 0.15); color: var(--blocked); }
.tool-icon.read { background: oklch(68% 0.12 235 / 0.15); color: var(--info); }
.tool-icon.run { background: oklch(72% 0.16 155 / 0.15); color: var(--running); }
.tool-icon.other { background: var(--surface-raised); color: var(--muted); }
.tool-label { font-weight: 500; color: var(--fg); }
.tool-sub { color: var(--muted); font: 11px 'DM Mono', monospace; margin-left: 4px; }
.tool-ts { margin-left: auto; font: 11px 'DM Mono', monospace; color: var(--muted-2); }

.btn { padding: 6px 14px; border-radius: 7px; font-size: 12px; font-weight: 500; cursor: pointer; display: inline-flex; align-items: center; gap: 7px; transition: all 0.15s; }
.btn-ghost { background: transparent; color: var(--muted); border: 1px solid var(--border-subtle); }
.btn-ghost:hover { background: var(--surface); color: var(--fg); }
.btn-primary { background: var(--fg); color: var(--bg); }
.btn-primary:hover { opacity: 0.88; }
.btn-assume { background: oklch(76% 0.16 75 / 0.15); color: var(--assumed); border: 1px solid oklch(76% 0.16 75 / 0.3); }
.btn-assume:hover { background: oklch(76% 0.16 75 / 0.25); }

.focus-header { height: 52px; border-bottom: 1px solid var(--border-subtle); display: flex; align-items: center; padding: 0 20px; gap: 14px; flex-shrink: 0; }
.focus-body { flex: 1; display: grid; grid-template-columns: 260px 1fr 320px; overflow: hidden; }
.focus-center { overflow-y: auto; padding-bottom: 100px; }
.focus-left { border-right: 1px solid var(--border-subtle); overflow-y: auto; padding: 14px; }
.focus-right { border-left: 1px solid var(--border-subtle); overflow-y: auto; padding: 14px; }

.chat-input-area { position: fixed; bottom: 0; left: 0; right: 0; background: var(--bg); border-top: 1px solid var(--border-subtle); padding: 12px 20px; z-index: 60; }
.chat-row { display: flex; align-items: center; gap: 10px; }
.chat-input { flex: 1; background: var(--surface); border: 1px solid var(--border); color: var(--fg); font: 13px 'DM Sans', sans-serif; padding: 10px 14px; border-radius: 8px; resize: none; outline: none; }
.chat-input:focus { border-color: var(--info); }
.send-btn { width: 38px; height: 38px; border-radius: 8px; background: var(--info); color: var(--bg); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.send-btn:hover { opacity: 0.85; }
.send-btn svg { width: 16px; height: 16px; }

.ctx-label { font-size: 10px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; }
.ctx-row { font-size: 12px; display: flex; justify-content: space-between; margin-bottom: 6px; color: var(--muted); }
.ctx-row .val { color: var(--fg-soft); }

@media (max-width: 900px) {
  .canvas { grid-template-columns: 1fr; }
  .focus-body { grid-template-columns: 1fr; }
  .left-panel, .right-panel, .focus-left, .focus-right { display: none; }
}</style>
</head>
<body>

<header class="topbar">
  <div class="topbar-brand"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>agentjam</div>
  <div class="topbar-sep"></div>
  <nav class="topbar-nav" id="topnav">
    <a href="#overview" class="active" data-nav="overview">Overview</a>
    <a href="#tasks" data-nav="tasks">Tasks</a>
  </nav>
  <div class="topbar-meta" id="topbar-stats">
    <span id="stat-agents">0 agents</span>
    <span id="stat-tokens">0 tokens</span>
    <span id="stat-cost">$0.000</span>
  </div>
</header>

<div class="canvas">
  <aside class="left-panel" id="left-panel">
    <div class="panel-label">Agents</div>
    <div id="agent-sidebar"><span style="color:var(--muted);font-size:12px">Loading…</span></div>
  </aside>
  <div class="center-panel" id="center-panel"></div>
  <aside class="right-panel" id="right-panel">
    <div class="ctx-label">Info</div>
    <span style="color:var(--muted);font-size:12px">Click an agent to focus</span>
  </aside>
</div>

<div class="chat-input-area" id="chat-area" style="display:none">
  <div class="chat-row">
    <textarea class="chat-input" id="chat-input" placeholder="Tell the agent what to do…" rows="1" data-agent-id=""></textarea>
    <button class="send-btn" id="send-btn" onclick="sendChatMsg()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
  </div>
</div>

<script>
var focusedID = null, sseMap = {};

function route() {
  var h = location.hash || '#overview', p = h.replace('#','').split('/');
  document.querySelectorAll('#topnav a').forEach(function(a){ a.classList.toggle('active', a.getAttribute('data-nav')===p[0]); });
  document.getElementById('chat-area').style.display = 'none';
  if (p[0] === 'agent' && p[1]) renderFocus(p[1]);
  else if (p[0] === 'tasks') renderTasks();
  else renderOverview();
}
window.addEventListener('hashchange', route);

function renderOverview() {
  var c = document.getElementById('center-panel');
  c.style.padding = '24px 28px';
  c.innerHTML = '<div id="agent-cards"></div>';
  document.getElementById('right-panel').innerHTML = '<div class="ctx-label">Info</div><span style="font-size:12px;color:var(--muted)">Click an agent to focus</span>';
  refreshCards(); setInterval(refreshCards, 2000);
}

function refreshCards() {
  fetch('/api/agents').then(function(r){ return r.text(); }).then(function(html) {
    var g = document.getElementById('agent-cards'); if (!g) return;
    g.innerHTML = html;
    var cs = g.querySelectorAll('.agent-card'), tk = 0, co = 0;
    cs.forEach(function(c){ tk += parseInt(c.getAttribute('data-tokens'))||0; co += parseFloat(c.getAttribute('data-cost'))||0; });
    document.getElementById('stat-agents').textContent = cs.length + ' agents';
    document.getElementById('stat-tokens').textContent = (tk >= 1000 ? (tk/1000).toFixed(1)+'k' : tk) + ' tokens';
    document.getElementById('stat-cost').textContent = '$' + co.toFixed(3);
    // Update sidebar
    var sb = document.getElementById('agent-sidebar'); sb.innerHTML = '';
    cs.forEach(function(c){ var id = c.getAttribute('data-id'); if (id) sb.innerHTML += '<div class="panel-item" onclick="location.href=\'#agent/'+id+'\'"><span class="panel-pip running"></span><span class="mono">'+id.substring(0,12)+'</span></div>'; });
  });
}

function renderFocus(id) {
  focusedID = id;
  var c = document.getElementById('center-panel');
  c.style.padding = '0';
  c.innerHTML =
    '<div class="focus-header">' +
      '<a href="#overview" class="btn btn-ghost" style="width:30px;height:30px;padding:0;display:flex;align-items:center;justify-content:center">&larr;</a>' +
      '<div style="display:flex;align-items:center;gap:10px">' +
        '<span class="status-pip running"></span>' +
        '<span class="mono" style="font-size:14px;font-weight:600">' + id.substring(0,20) + '</span>' +
        '<span class="mode-pill" id="mode-pill"><span class="pill-dot"></span>watching</span>' +
      '</div>' +
      '<div style="margin-left:auto;display:flex;gap:8px">' +
        '<button class="btn btn-assume" onclick="doAction(\'assume\')">Assume</button>' +
        '<button class="btn btn-ghost" onclick="doAction(\'relinquish\')">Relinquish</button>' +
      '</div>' +
    '</div>' +
    '<div class="focus-body">' +
      '<div class="focus-left"><div class="ctx-label">Status</div><div style="font-size:12px;margin-bottom:10px;color:var(--running)">running</div><div class="ctx-label">Mode</div><div style="font-size:12px;color:var(--fg-soft);margin-bottom:10px">agent</div></div>' +
      '<div class="focus-center" id="focus-events"><p style="font-size:12px;color:var(--muted);padding:20px">Connecting to event stream…</p></div>' +
      '<div class="focus-right"><div class="ctx-label">Stats</div><div class="ctx-row"><span>Tokens</span><span class="val mono" id="focus-tokens">—</span></div><div class="ctx-row"><span>Cost</span><span class="val mono" id="focus-cost">—</span></div></div>' +
    '</div>';
  document.getElementById('chat-area').style.display = 'block';
  document.getElementById('chat-input').setAttribute('data-agent-id', id);
  document.getElementById('right-panel').innerHTML = '';
  startSSE(id);
}

function startSSE(id) {
  if (sseMap[id]) sseMap[id].close();
  var es = new EventSource('/api/agent/' + id + '/events'), d = document.getElementById('focus-events');
  sseMap[id] = es;
  es.onmessage = function(e) { if (!d) return; if (d.querySelector('p')) d.innerHTML = ''; var r = document.createElement('div'); r.innerHTML = e.data; d.prepend(r); };
  es.addEventListener('close', function() { if (d) d.innerHTML += '<p style="font-size:12px;color:var(--muted);padding:10px">Session ended.</p>'; es.close(); });
}

function renderTasks() {
  document.getElementById('center-panel').innerHTML = '<p style="color:var(--muted);padding:20px;font-size:14px">Tasks coming soon.</p>';
}

function doAction(a) { if (focusedID) fetch('/api/agent/' + focusedID + '/' + a, {method:'POST'}); }
function sendChatMsg() {
  var i = document.getElementById('chat-input'), m = i.value.trim();
  if (!m) return;
  fetch('/api/agent/' + i.getAttribute('data-agent-id') + '/send', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:'message=' + encodeURIComponent(m)});
  i.value = '';
}
document.getElementById('chat-input').addEventListener('keydown', function(e) { if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendChatMsg(); } });
route();
</script>
</body>
</html>`

// loginHTML is the token-entry page. Serves as the auth gateway before
// the cockpit SPA is loaded. On successful auth, redirect to /.
const loginHTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agentjam cockpit — login</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root { --bg: oklch(9% 0.005 260); --surface: oklch(14% 0.006 260); --fg: oklch(92% 0.003 260); --fg-soft: oklch(78% 0.005 260); --muted: oklch(58% 0.012 260); --border: oklch(22% 0.006 260); --info: oklch(68% 0.12 235); }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font: 14px/1.5 'DM Sans', system-ui, sans-serif; background: var(--bg); color: var(--fg); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
.login-box { width: 380px; }
h2 { font-size: 22px; font-weight: 600; margin-bottom: 20px; }
label { display: block; font-size: 13px; color: var(--fg-soft); margin-bottom: 6px; }
input { width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface); color: var(--fg); font-size: 15px; margin-bottom: 16px; }
input:focus { outline: none; border-color: var(--info); }
button { width: 100%; padding: 10px; border-radius: 8px; border: none; font-size: 14px; font-weight: 600; cursor: pointer; background: var(--fg); color: var(--bg); }
button:hover { opacity: 0.88; }
</style>
</head>
<body>
<div class="login-box">
  <h2>&#9889; agentjam cockpit</h2>
  <p style="color:var(--muted);font-size:13px;margin-bottom:20px">Enter your access token.</p>
  <form method="POST" action="/login">
    <input type="hidden" name="return" value="{{.Return}}">
    <label>Token</label>
    <input type="password" name="token" placeholder="Access token" required autofocus>
    <button type="submit">Connect</button>
  </form>
</div>
</body>
</html>`
