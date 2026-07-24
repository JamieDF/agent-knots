"""Static HTML string templates — the login page and the (dev-mode-only,
pre-Vite-build) inline SPA shell fallback."""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agent-knots cockpit — login</title>
<style>
:root {{
  --bg: #eceef2; --dot: #cdd2db; --card: #ffffff; --card2: #fafbfc;
  --line: #eef0f3; --line2: #dcdfe5; --ink: #23262b; --ink2: #5a6069; --mut: #8a8f99;
  --acc: #6c5ce7; --acc-ink: #ffffff; --err: #e05252;
  --shadow-lg: 0 16px 44px rgba(30, 35, 50, .22);
  --font: 'DM Sans', system-ui, sans-serif; --font-mono: 'DM Mono', monospace;
}}
body[data-theme="dark"] {{
  --bg: #191b20; --dot: #2c3038; --card: #23262d; --card2: #1e2126;
  --line: #2e323a; --line2: #3a3f48; --ink: #dfe2e8; --ink2: #aab0ba; --mut: #767c87;
  --acc: #8f7ff2; --acc-ink: #191b20; --err: #e06a6a;
  --shadow-lg: 0 16px 44px rgba(0, 0, 0, .5);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font: 14px/1.5 var(--font); color: var(--ink); min-height: 100vh;
  display: flex; align-items: center; justify-content: center;
  background-color: var(--bg);
  background-image: radial-gradient(var(--dot) 1px, transparent 1px);
  background-size: 22px 22px;
}}
.login-card {{
  width: 380px; max-width: 90vw; background: var(--card); border: 1px solid var(--line);
  border-radius: 16px; box-shadow: var(--shadow-lg); padding: 28px;
}}
.logo {{
  width: 48px; height: 48px; border-radius: 12px; background: var(--card2);
  display: flex; align-items: center; justify-content: center; font-size: 22px;
  margin: 0 auto 14px;
}}
h2 {{ font-size: 17px; font-weight: 700; text-align: center; }}
.sub {{ color: var(--mut); font-size: 12.5px; margin: 6px 0 22px; text-align: center; }}
.sub code {{ font-family: var(--font-mono); background: var(--card2); padding: 1px 5px; border-radius: 4px; }}
label {{ display: block; font-size: 10.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--mut); margin-bottom: 6px; }}
input {{
  width: 100%; padding: 9px 12px; border-radius: 8px; border: 1px solid var(--line2);
  background: var(--card2); color: var(--ink); font-size: 14px; margin-bottom: 16px; font-family: inherit;
}}
input:focus {{ outline: none; border-color: var(--acc); }}
button {{
  width: 100%; padding: 10px; border-radius: 8px; border: none; font-size: 13.5px; font-weight: 700;
  cursor: pointer; background: var(--acc); color: var(--acc-ink); font-family: inherit;
}}
button:hover {{ opacity: 0.9; }}
.error {{ color: var(--err); font-size: 12.5px; margin-bottom: 12px; }}
.note {{ color: var(--mut); font-size: 10.5px; margin-top: 16px; text-align: center; }}
</style>
</head>
<body>
<script>
(function() {{
  var t = localStorage.getItem('agent-knots-theme');
  if (t === 'dark') document.body.setAttribute('data-theme', 'dark');
}})();
</script>
<div class="login-card">
  <div class="logo">&#9889;</div>
  <h2>agent-knots cockpit</h2>
  <p class="sub">Paste the access token printed by<br><code>agent-knots cockpit launch --web</code></p>
  <form method="POST" action="/login">
    <input type="hidden" name="return" value="{return_url}">
    <label>Access token</label>
    <input type="password" name="token" placeholder="Access token" required autofocus>
    <div class="error">{error}</div>
    <button type="submit">Continue</button>
  </form>
  <div class="note">local-only · token stored as a cookie</div>
</div>
</body>
</html>"""

SPA_SHELL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agent-knots cockpit</title>
<style>
:root {{ --bg: #12141a; --surface: #1c1e26; --surface-raised: #242630; --fg: #e4e4e8; --fg-soft: #a0a0b0; --muted: #6b6b80; --border: #2a2a3a; --running: #9ece6a; --blocked: #e0af68; --assumed: #e0af68; --info: #7aa2f7; --done: #9ece6a; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font: 14px/1.5 system-ui, sans-serif; background: var(--bg); color: var(--fg); height: 100vh; overflow: hidden; }}
#app {{ display: flex; flex-direction: column; height: 100%; }}
.topbar {{ display: flex; align-items: center; gap: 16px; padding: 10px 20px; border-bottom: 1px solid var(--border); background: var(--surface); }}
.topbar-brand {{ font-weight: 700; font-size: 16px; }}
.topbar-nav {{ display: flex; gap: 8px; }}
.topbar-nav a {{ color: var(--fg-soft); text-decoration: none; padding: 4px 10px; border-radius: 4px; font-size: 13px; }}
.topbar-nav a.active {{ background: var(--surface-raised); color: var(--fg); }}
.topbar-stats {{ margin-left: auto; display: flex; gap: 16px; font-size: 13px; color: var(--fg-soft); }}
#agents-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; padding: 20px; overflow-y: auto; flex: 1; }}
.agent-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px; cursor: pointer; }}
.agent-card:hover {{ border-color: var(--info); }}
.agent-card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
.status-pip {{ width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }}
.status-pip.running {{ background: var(--running); box-shadow: 0 0 6px var(--running); animation: glow 2s infinite; }}
@keyframes glow {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:0.6 }} }}
.mode-pill {{ display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 12px; font-size: 11px; background: var(--surface-raised); color: var(--fg-soft); }}
.mode-pill.assumed {{ background: oklch(38% 0.04 75); color: var(--assumed); }}
.agent-card-id {{ font: 12px monospace; color: var(--muted); margin-bottom: 6px; }}
.agent-card-action {{ font-size: 12px; color: var(--fg-soft); }}
.agent-card-stats {{ display: flex; gap: 12px; font-size: 11px; color: var(--muted); margin-top: 8px; }}
.empty-state {{ display: flex; align-items: center; justify-content: center; height: 100%; color: var(--muted); font-size: 16px; }}
</style>
</head>
<body>
<div id="app">
  <div class="topbar">
    <div class="topbar-brand">⚡ agent-knots</div>
    <div class="topbar-nav">
      <a href="#" data-view="overview" class="active">Overview</a>
      <a href="#" data-view="tasks">Tasks</a>
    </div>
    <div class="topbar-stats">
      <span id="stat-agents">0 agents</span>
      <span id="stat-tokens">0 tokens</span>
      <span id="stat-cost">$0.00</span>
    </div>
  </div>
  <div id="agents-grid">
    <div class="empty-state">No agents running. Start one with: agent-knots session start</div>
  </div>
</div>
<script>
// Minimal SPA shell — the full SPA will be built with Vite+React.
// For now, this shell polls /api/agents and renders basic agent cards.
let focusedAgent = null;

async function refresh() {{
  try {{
    const res = await fetch('/api/agents');
    const data = await res.json();
    renderCards(data.agents);
    updateStats(data.agents);
  }} catch(e) {{}}
}}

function renderCards(agents) {{
  const grid = document.getElementById('agents-grid');
  if (!agents.length) {{
    grid.innerHTML = '<div class="empty-state">No agents running. Start one with: agent-knots session start</div>';
    return;
  }}
  grid.innerHTML = agents.map(a => `
    <div class="agent-card" onclick="focusAgent('${{a.id}}')" data-agent-id="${{a.id}}">
      <div class="agent-card-header">
        <div class="status-pip ${{a.running ? 'running' : ''}}"></div>
        <div class="mode-pill ${{a.mode === 'assistant' ? 'assumed' : ''}}">${{a.mode}}</div>
      </div>
      <div class="agent-card-id">${{a.id}}</div>
      <div class="agent-card-action">${{a.running ? 'running...' : 'idle'}}</div>
      <div class="agent-card-stats">
        <span>${{a.tokens_used}} tok</span>
        <span>$${{a.cost_usd.toFixed(2)}}</span>
      </div>
    </div>
  `).join('');
}}

function updateStats(agents) {{
  document.getElementById('stat-agents').textContent = agents.length + ' agent' + (agents.length !== 1 ? 's' : '');
  const tokens = agents.reduce((s,a) => s + a.tokens_used, 0);
  const cost = agents.reduce((s,a) => s + a.cost_usd, 0);
  document.getElementById('stat-tokens').textContent = tokens + ' tokens';
  document.getElementById('stat-cost').textContent = '$' + cost.toFixed(2);
}}

function focusAgent(id) {{
  focusedAgent = id;
  // Will be replaced by React SPA routing
  window.location.hash = '#agent/' + id;
}}

// Poll every 2s.
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>"""
