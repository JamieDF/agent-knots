package web

// cssBase is the shared dark-theme design foundation.
// Design tokens from the mockup index.html: DM Sans + DM Mono, oklch color space.
const cssBase = `
:root {
	--bg:            oklch(9% 0.005 260);
	--surface:       oklch(14% 0.006 260);
	--surface-raised: oklch(18% 0.008 260);
	--surface-hover: oklch(20% 0.008 260);
	--fg:            oklch(92% 0.003 260);
	--fg-soft:       oklch(78% 0.005 260);
	--muted:         oklch(58% 0.012 260);
	--muted-2:       oklch(42% 0.012 260);
	--border:        oklch(22% 0.006 260);
	--border-subtle: oklch(16% 0.004 260);
	--info:          oklch(68% 0.12 235);
	--running:       oklch(72% 0.16 155);
	--blocked:       oklch(75% 0.13 85);
	--error:         oklch(65% 0.16 20);
	--assumed:       oklch(75% 0.13 85);
}
* { box-sizing:border-box; margin:0; padding:0; }
body {
	font: 14px/1.5 "DM Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
	background: var(--bg); color: var(--fg);
	min-height: 100vh; -webkit-font-smoothing: antialiased;
	padding: 56px 32px;
}
.mono { font: 12px/1.5 "DM Mono", "JetBrains Mono", monospace; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
a { color: inherit; text-decoration: none; }
a:hover { color: var(--info); }
.wrap { max-width: 1080px; margin: 0 auto; }

/* Cards */
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.card {
	display: block; background: var(--surface); border: 1px solid var(--border-subtle);
	border-radius: 12px; padding: 18px; transition: background .15s, border-color .15s;
}
.card:hover { background: var(--surface-raised); border-color: var(--border); }
.card-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.card-id { font: 12px "DM Mono", monospace; color: var(--muted-2); }
.card-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; font-size: 12px; color: var(--muted); margin: 8px 0; }
.card-meta span { display: flex; justify-content: space-between; }
.card-meta .val { color: var(--fg-soft); }
.card-action { margin-top: 8px; font-size: 12px; color: var(--fg-soft); border-top: 1px solid var(--border-subtle); padding-top: 8px; }

/* Badges */
.badge {
	font-size: 10px; padding: 3px 8px; border-radius: 99px; font-weight: 500;
	letter-spacing: 0.02em; white-space: nowrap;
}
.badge-agent { background: oklch(68% 0.12 235 / 0.15); color: oklch(80% 0.12 235); }
.badge-assistant { background: oklch(75% 0.13 85 / 0.15); color: oklch(82% 0.13 85); }
.badge-stopped { background: var(--surface-raised); color: var(--muted); }
.badge-running { background: oklch(72% 0.16 155 / 0.15); color: oklch(82% 0.16 155); }
.badge-blocked { background: oklch(75% 0.13 85 / 0.15); color: oklch(82% 0.13 85); }

/* Status dots */
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
.dot-running { background: var(--running); }
.dot-blocked { background: var(--blocked); }
.dot-stopped { background: var(--muted-2); }
.dot-assumed { background: var(--assumed); animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:.4 } }

/* Buttons */
.btn {
	display: inline-flex; align-items: center; gap: 6px;
	font: 12px/1.4 "DM Sans", sans-serif; padding: 6px 14px; border-radius: 6px;
	border: 1px solid var(--border); background: var(--surface-raised); color: var(--fg);
	cursor: pointer; transition: background .15s;
}
.btn:hover { background: var(--surface-hover); }
.btn-primary { background: oklch(68% 0.12 235 / 0.2); border-color: oklch(68% 0.12 235 / 0.3); color: oklch(80% 0.12 235); }
.btn-amber { background: oklch(75% 0.13 85 / 0.15); border-color: oklch(75% 0.13 85 / 0.3); color: oklch(82% 0.13 85); }

/* Header */
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 32px; }
.page-header h1 { font-size: 26px; font-weight: 600; letter-spacing: -0.015em; }
.page-header .stats { display: flex; gap: 20px; font-size: 12px; color: var(--muted); }
.page-header .stats .n { font: 16px "DM Mono", monospace; color: var(--fg); }

/* Agent focus: event stream */
.event-row { display: flex; gap: 10px; padding: 4px 0; font-size: 13px; border-bottom: 1px solid var(--border-subtle); }
.event-row .ts { font: 11px "DM Mono", monospace; color: var(--muted-2); min-width: 70px; padding-top: 1px; }
.event-row .icon { width: 16px; text-align: center; padding-top: 1px; font-size: 12px; }
.event-row .content { flex: 1; min-width: 0; word-break: break-word; }
.event-thinking { color: var(--info); font-style: italic; }
.event-message { color: var(--fg); }
.event-tool { color: var(--assumed); }
.event-tool .tool-name { font: 11px "DM Mono", monospace; background: var(--surface); padding: 1px 5px; border-radius: 3px; }
.event-error { color: var(--error); }
.event-state { color: var(--info); }
.event-progress { color: var(--muted); }

/* Action bar */
.action-bar { display: flex; gap: 8px; align-items: center; margin-bottom: 20px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.action-bar input[type=text] {
	flex: 1; min-width: 200px; padding: 6px 10px; border-radius: 6px; border: 1px solid var(--border);
	background: var(--surface); color: var(--fg); font-size: 13px;
}
.action-bar input::placeholder { color: var(--muted); }

/* Context banner for assumed mode */
.context-banner {
	background: oklch(75% 0.13 85 / 0.08); border: 1px solid oklch(75% 0.13 85 / 0.15);
	border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; font-size: 12px; color: var(--fg-soft);
}

/* Input, form */
input[type=password] {
	padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border);
	background: var(--surface); color: var(--fg); font-size: 14px; width: 100%;
}
input[type=password]:focus { outline: none; border-color: var(--info); }

/* Responsive */
@media (max-width: 640px) {
	body { padding: 24px 16px; }
	.card-grid { grid-template-columns: 1fr; }
	.page-header { flex-direction: column; align-items: flex-start; gap: 12px; }
}
`

// indexHTML is the agent list / overview page. Card grid with live status.
const indexHTML = `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>agentjam cockpit</title>
	<link rel="preconnect" href="https://fonts.googleapis.com">
	<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
	<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
	<style>` + cssBase + `</style>
</head>
<body>
	<div class="wrap">
		<header class="page-header">
			<h1>&#9889; agentjam cockpit</h1>
			<div class="stats" id="header-stats">
				<div><span class="n" id="agent-count">—</span> agents</div>
				<div><span class="n" id="token-count">—</span> tokens</div>
				<div><span class="n" id="cost-total">—</span> cost</div>
			</div>
		</header>
		<div id="agent-grid" class="card-grid"><p style="color:var(--muted)">Loading...</p></div>
	</div>
	<script>
		async function refresh() {
			try {
				const r = await fetch('/api/agents');
				if (!r.ok) return;
				const c = document.getElementById('agent-grid');
				// Track open details (if we use any).
				const openIds = new Set();
				c.querySelectorAll('details[open]').forEach(d => {
					const id = d.getAttribute('data-id');
					if (id) openIds.add(id);
				});
				c.innerHTML = await r.text();
				c.querySelectorAll('details').forEach(d => {
					if (openIds.has(d.getAttribute('data-id'))) d.open = true;
				});

				// Update header stats.
				updateStats(c);
			} catch(e) {}
		}
		function updateStats(c) {
			const cards = c.querySelectorAll('.card');
			let agents = cards.length;
			let tokens = 0, cost = 0;
			cards.forEach(card => {
				const t = parseInt(card.getAttribute('data-tokens')) || 0;
				const co = parseFloat(card.getAttribute('data-cost')) || 0;
				tokens += t;
				cost += co;
			});
			document.getElementById('agent-count').textContent = agents;
			document.getElementById('token-count').textContent = tokens >= 1000 ? (tokens/1000).toFixed(1)+'k' : tokens;
			document.getElementById('cost-total').textContent = '$'+cost.toFixed(3);
		}
		refresh();
		setInterval(refresh, 2000);
	</script>
</body>
</html>`

// agentHTML is the single-agent detail page with SSE event stream.
const agentHTML = `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>agentjam &mdash; {{.ID}}</title>
	<link rel="preconnect" href="https://fonts.googleapis.com">
	<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
	<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
	<style>` + cssBase + `</style>
</head>
<body>
	<div class="wrap">
		<header class="page-header">
			<h1><a href="/">&larr;</a> <span class="mono">{{.ID}}</span></h1>
		</header>
		<div class="context-banner" style="display:none" id="context">
			Agent context will appear here.
		</div>
		<div class="action-bar">
			<button class="btn btn-amber" onclick="doAction('assume')">Assume Control</button>
			<button class="btn" onclick="doAction('relinquish')">Relinquish</button>
			<button class="btn btn-primary" onclick="doAction('pause')">Pause</button>
			<input type="text" id="msg" placeholder="Send a message..."
				onkeydown="if(event.key==='Enter')sendMsg()">
			<button class="btn btn-primary" onclick="sendMsg()">Send</button>
		</div>
		<div id="events"><p style="color:var(--muted)">Connecting...</p></div>
	</div>
	<script>
		(function() {
			var d = document.getElementById('events');
			var es = new EventSource('/api/agent/{{.ID}}/events');
			d.innerHTML = '';
			es.onmessage = function(e) {
				var row = document.createElement('div');
				row.className = 'event-row';
				row.innerHTML = e.data;
				d.prepend(row);
				// Keep last 500 events.
				while (d.children.length > 500) d.lastChild.remove();
			};
			es.addEventListener('close', function() {
				d.innerHTML += '<p style="color:var(--muted)">Session ended.</p>';
				es.close();
			});
			window.doAction = function(a) {
				fetch('/api/agent/{{.ID}}/' + a, {method:'POST'});
			};
			window.sendMsg = function() {
				var i = document.getElementById('msg');
				if(!i.value.trim()) return;
				fetch('/api/agent/{{.ID}}/send', {
					method:'POST',
					headers:{'Content-Type':'application/x-www-form-urlencoded'},
					body:'message=' + encodeURIComponent(i.value)
				});
				i.value = '';
			};
		})();
	</script>
</body>
</html>`

// loginHTML is the token-entry page.
const loginHTML = `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>agentjam cockpit &mdash; login</title>
	<link rel="preconnect" href="https://fonts.googleapis.com">
	<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
	<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
	<style>` + cssBase + `
		.login-form { max-width: 400px; margin: 80px auto; }
		.login-form label { display: block; font-size: 13px; color: var(--fg-soft); margin-bottom: 6px; }
		.login-form input { margin-bottom: 14px; }
	</style>
</head>
<body>
	<div class="wrap">
		<div class="login-form">
			<h2 style="margin-bottom:20px">&#9889; agentjam cockpit</h2>
			<p style="color:var(--muted); margin-bottom:20px; font-size:13px;">Enter your access token to continue.</p>
			<form method="POST" action="/login">
				<input type="hidden" name="return" value="{{.Return}}">
				<label>Token</label>
				<input type="password" name="token" placeholder="Access token" required autofocus>
				<button type="submit" class="btn btn-primary" style="width:100%">Connect</button>
			</form>
		</div>
	</div>
</body>
</html>`
