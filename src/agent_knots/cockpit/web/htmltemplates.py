"""Static HTML string templates — the login page and the (dev-mode-only,
pre-Vite-build) inline SPA shell fallback."""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agent-knots — login</title>
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
  width: 104px; height: 56px; border-radius: 12px; background: var(--card2);
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 14px;
}}
.logo-ink {{ fill: var(--ink); }}
.logo-accent {{ fill: var(--acc); }}
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
  <div class="logo">
    <svg width="88" height="43" viewBox="0 0 1024 496" xmlns="http://www.w3.org/2000/svg">
      <path class="logo-accent" d="M415.333 21.708C448.132 19.168 488.54 31.4663 516.145 48.893C505.066 58.3913 493.279 67.4231 482.171 76.9376C468.658 88.5128 454.347 98.0544 438.882 106.833C430.318 106.12 421.853 105.37 413.239 106.419C366.157 112.153 334.959 143.68 318.872 187.226C293.855 254.942 311.003 345.597 378.65 382.191C394.368 390.694 411.931 393.342 429.544 391.993C432.937 391.733 437.656 391.291 440.802 392.649C458.437 401.702 474.38 414.363 489.641 426.947C498.336 434.117 507.331 441.495 515.831 448.958C514.082 450.051 512.116 451.143 510.321 452.189C486.402 465.815 459.758 473.965 432.309 476.05C383.914 479.982 335.695 462.341 298.98 430.87C193.064 340.084 197.638 147.787 306.856 61.4483C339.452 35.6803 374.407 24.898 415.333 21.708Z"/>
      <path class="logo-ink" d="M661.832 21.701C672.24 20.7038 691.729 22.5186 701.912 24.7167C759.166 37.0757 796.299 67.732 827.699 115.567C819.74 115.876 809.98 115.641 801.92 115.653L751.728 115.712L724.513 115.71C707.959 115.672 706.485 114.967 691.54 108.616C683.5 105.2 664.937 105.512 656.021 106.719C610.376 112.893 577.962 147.536 543.705 174.775C526.783 188.197 512.662 197.955 493.677 207.981C441.877 234.883 394.763 230.218 338.315 230.394C341.704 205.528 350.2 181.139 366.563 161.708C379.556 144.279 396.924 146.959 415.72 143.802C494.356 130.593 535.401 48.6324 613.22 29.6271C631.555 25.1494 642.972 23.1478 661.832 21.701Z"/>
      <path class="logo-ink" d="M339.341 267.729C365.185 267.21 400.911 266.583 426.044 269.315C467.453 274.459 504.744 293.289 537.681 318.608C580.852 351.796 630.23 407.236 691.163 389.772C698.904 387.553 707.113 382.997 715.147 382.519C728.232 381.74 741.493 382.108 754.583 382.119L828.647 382.169C818.063 400.013 805.273 414.312 790.312 428.453C774.287 443.135 755.824 454.91 735.753 463.249C668.396 490.98 596.409 473.114 540.091 430.199C513.779 410.149 489.845 386.487 461.005 370.155C445.929 361.617 429.597 355.254 412.327 353.261C403.204 352.208 392.669 352.87 384.268 349.178C366.442 341.343 354.965 322.011 347.818 304.817C345.52 299.29 337.087 273.073 339.341 267.729Z"/>
      <path class="logo-accent" d="M643.822 140.584C644.635 140.544 645.449 140.515 646.263 140.497C657.176 140.278 673.926 144.698 685.595 145.155C702.845 145.83 720.481 145.581 737.725 145.594L904.997 145.53L957.418 145.487C966.829 145.476 976.582 145.892 985.934 145.634C1027.32 144.494 1023.71 231.64 985.067 231.023C971.053 230.798 956.248 230.98 942.125 230.93C881.025 230.063 819.139 230.465 757.99 230.405L709.371 230.398C686.372 230.442 666.392 231.078 643.736 226.009C615.641 219.724 592.495 208.527 568.679 192.705C593.351 170.79 612.751 152.505 643.822 140.584Z"/>
      <path class="logo-accent" d="M689.473 267.725C690.244 267.684 691.015 267.651 691.787 267.626C711.415 267.022 733.391 267.641 753.269 267.666L872.41 267.733L947.239 267.696C960.713 267.678 973.867 267.387 987.356 268.02C1008.17 268.996 1011.58 292.38 1012.14 308.917C1012.63 323.556 1008.16 349.752 989.732 351.872C978.7 353.141 965.691 352.482 954.395 352.463L885.25 352.472L763.161 352.426C742.199 352.405 716.247 351.653 695.616 352.668C685.497 353.155 675.407 354.098 665.373 355.493C658.719 356.441 652.092 357.8 645.409 358.467C642.091 358.797 637.073 356.095 634.095 354.555C609.642 341.913 588.906 323.144 568.326 305.142C608.845 277.584 641.473 269.342 689.473 267.725Z"/>
      <path class="logo-ink" d="M28.2127 145.632C49.5642 145.14 72.0164 145.489 93.4491 145.49L211.18 145.507C204.641 166.952 197.817 186.098 195.023 208.904C194.613 212.253 193.83 228.684 192.523 230.166L87.0486 230.214C68.7565 230.211 50.1594 230.293 31.8589 229.957C29.7147 229.918 23.6371 228.859 21.984 227.755C16.2275 223.912 12.3889 217.212 10.7734 210.453C6.79234 193.797 7.13222 170.26 15.4175 154.889C18.2263 149.678 22.7689 147.072 28.2127 145.632Z"/>
      <path class="logo-ink" d="M35.61 267.718C87.7861 267.111 140.843 267.818 193.123 267.633C195.171 300.824 201.525 321.198 211.302 352.464L184.75 352.425L81.5471 352.452L49.8683 352.45C42.912 352.449 25.4742 353.493 20.5832 348.571C4.05541 331.939 6.54101 292.142 19.7391 274.103C23.6468 268.762 29.6254 268.237 35.61 267.718Z"/>
    </svg>
  </div>
  <h2>agent-knots</h2>
  <p class="sub">Paste the access token printed by<br><code>agent-knots launch --web</code></p>
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
<title>agent-knots</title>
<style>
:root {{ --bg: #12141a; --surface: #1c1e26; --surface-raised: #242630; --fg: #e4e4e8; --fg-soft: #a0a0b0; --muted: #6b6b80; --border: #2a2a3a; --running: #9ece6a; --blocked: #e0af68; --assumed: #e0af68; --info: #7aa2f7; --done: #9ece6a; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font: 14px/1.5 system-ui, sans-serif; background: var(--bg); color: var(--fg); height: 100vh; overflow: hidden; }}
#app {{ display: flex; flex-direction: column; height: 100%; }}
.topbar {{ display: flex; align-items: center; gap: 16px; padding: 10px 20px; border-bottom: 1px solid var(--border); background: var(--surface); }}
.topbar-brand {{ font-weight: 700; font-size: 16px; display: flex; align-items: center; gap: 8px; }}
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
    <div class="topbar-brand">
      <svg width="20" height="10" viewBox="0 0 1024 496" xmlns="http://www.w3.org/2000/svg">
        <path fill="#6964FE" d="M516.145 48.893C488.54 31.4663 448.132 19.168 415.333 21.708C374.407 24.898 339.452 35.6803 306.856 61.4483C197.638 147.787 193.064 340.084 298.98 430.87C335.695 462.341 383.914 479.982 432.309 476.05C459.758 473.965 486.402 465.815 510.321 452.189C512.116 451.143 514.082 450.051 515.831 448.958C507.331 441.495 498.336 434.117 489.641 426.947C474.38 414.363 458.437 401.702 440.802 392.649C437.797 391.352 433.358 391.697 430.01 391.957C429.852 391.969 429.697 391.981 429.544 391.993C411.931 393.342 394.368 390.694 378.65 382.191C311.003 345.597 293.855 254.942 318.872 187.226C334.959 143.68 366.157 112.153 413.239 106.419C421.643 105.396 429.905 106.085 438.256 106.781L438.882 106.833C454.347 98.0544 468.658 88.5128 482.171 76.9376C493.279 67.4231 505.066 58.3913 516.145 48.893Z"/>
        <path fill="#DFE2E8" d="M701.912 24.7167C691.729 22.5186 672.24 20.7038 661.832 21.701C642.972 23.1478 631.555 25.1494 613.22 29.6271C535.401 48.6324 494.356 130.593 415.72 143.802C396.924 146.959 379.556 144.279 366.563 161.708C350.2 181.139 341.704 205.528 338.315 230.394C345.92 230.37 353.356 230.434 360.657 230.497C407.543 230.902 448.856 231.258 493.677 207.981C512.662 197.955 526.783 188.197 543.705 174.775C577.962 147.536 610.376 112.893 656.021 106.719C664.937 105.512 683.5 105.2 691.54 108.616C706.485 114.967 707.959 115.672 724.513 115.71L751.728 115.712L801.92 115.653C804.389 115.649 807.018 115.669 809.706 115.689C815.791 115.734 822.178 115.781 827.699 115.567C796.299 67.732 759.166 37.0757 701.912 24.7167Z"/>
        <path fill="#DFE2E8" d="M426.044 269.315C400.911 266.583 365.185 267.21 339.341 267.729C337.087 273.073 345.52 299.29 347.818 304.817C354.965 322.011 366.442 341.343 384.268 349.178C392.669 352.87 403.204 352.208 412.327 353.261C429.597 355.254 445.929 361.617 461.005 370.155C489.845 386.487 513.779 410.149 540.091 430.199C596.409 473.114 668.396 490.98 735.753 463.249C755.824 454.91 774.287 443.135 790.312 428.453C805.273 414.312 818.063 400.013 828.647 382.169L754.583 382.119C751.481 382.116 748.37 382.094 745.254 382.071C735.219 381.998 725.132 381.925 715.147 382.519C707.113 382.997 698.904 387.553 691.163 389.772C640.664 404.245 598.102 368.645 560.431 337.137C552.648 330.627 545.074 324.291 537.681 318.608C504.744 293.289 467.453 274.459 426.044 269.315Z"/>
        <path fill="#6964FE" d="M646.263 140.497C645.449 140.515 644.635 140.544 643.822 140.584C612.751 152.505 593.351 170.79 568.679 192.705C592.495 208.527 615.641 219.724 643.736 226.009C664.223 230.593 682.521 230.511 702.842 230.421C704.994 230.412 707.169 230.402 709.371 230.398L757.99 230.405C774.298 230.421 790.659 230.404 807.044 230.387C852.093 230.341 897.32 230.294 942.125 230.93C947.245 230.948 952.454 230.936 957.683 230.923C966.878 230.902 976.133 230.88 985.067 231.023C1023.71 231.64 1027.32 144.494 985.934 145.634C980.202 145.792 974.318 145.697 968.456 145.602C964.754 145.542 961.06 145.483 957.418 145.487L904.997 145.53L737.725 145.594C733.924 145.591 730.104 145.601 726.273 145.611C712.725 145.646 699.042 145.681 685.595 145.155C680.233 144.945 673.799 143.898 667.351 142.849C659.765 141.616 652.162 140.379 646.263 140.497Z"/>
        <path fill="#6964FE" d="M691.787 267.626C691.015 267.651 690.244 267.684 689.473 267.725C641.473 269.342 608.845 277.584 568.326 305.142C588.906 323.144 609.642 341.913 634.095 354.555C634.232 354.626 634.374 354.699 634.519 354.775C637.532 356.337 642.244 358.782 645.409 358.467C652.092 357.8 658.719 356.441 665.373 355.493C675.407 354.098 685.497 353.155 695.616 352.668C710.384 351.941 727.877 352.12 744.316 352.288C750.843 352.355 757.203 352.42 763.161 352.426L885.25 352.472L954.395 352.463C957.157 352.468 960.021 352.511 962.934 352.554C971.934 352.689 981.397 352.831 989.732 351.872C1008.16 349.752 1012.63 323.556 1012.14 308.917C1011.58 292.38 1008.17 268.996 987.356 268.02C976.955 267.532 966.753 267.593 956.45 267.655C953.391 267.673 950.324 267.692 947.239 267.696L872.41 267.733L753.269 267.666C746.847 267.658 740.206 267.588 733.496 267.517C719.437 267.369 705.074 267.217 691.787 267.626Z"/>
        <path fill="#DFE2E8" d="M74.5261 145.43C59.0387 145.357 43.3491 145.283 28.2127 145.632C22.7689 147.072 18.2263 149.678 15.4175 154.889C7.13222 170.26 6.79234 193.797 10.7734 210.453C12.3889 217.212 16.2275 223.912 21.984 227.755C23.6371 228.859 29.7147 229.918 31.8589 229.957C47.0712 230.236 62.4885 230.227 77.7652 230.217C80.8664 230.215 83.9619 230.214 87.0486 230.214L192.523 230.166C193.83 228.684 194.613 212.253 195.023 208.904C197.817 186.098 204.641 166.952 211.18 145.507L93.4491 145.49C87.2104 145.49 80.8853 145.46 74.5261 145.43Z"/>
        <path fill="#DFE2E8" d="M129.458 267.566C98.0967 267.461 66.697 267.356 35.61 267.718C29.6254 268.237 23.6468 268.762 19.7391 274.103C6.54101 292.142 4.05541 331.939 20.5832 348.571C24.8303 352.845 38.5382 352.62 46.6286 352.488C47.8551 352.468 48.9525 352.45 49.8683 352.45L81.5471 352.452L184.75 352.425L211.302 352.464C201.525 321.198 195.171 300.824 193.123 267.633C171.992 267.708 150.734 267.637 129.458 267.566Z"/>
      </svg>
      agent-knots
    </div>
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
