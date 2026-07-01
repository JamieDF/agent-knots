package web

// cssCommon is embedded in every page — a minimal dark theme.
const cssCommon = `
	:root { --bg:#111; --fg:#eee; --dim:#888; --border:#333; }
	* { box-sizing:border-box; margin:0; padding:0; }
	body { background:var(--bg); color:var(--fg);
		font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
		padding:1rem; }
	a { color:#6cf; text-decoration:none; } a:hover { text-decoration:underline; }
	main { max-width:900px; margin:0 auto; }
	h1,h2 { margin-bottom:.5rem; }
	h1 a,h2 a { color:var(--fg); text-decoration:none; }
	button { background:#333; color:var(--fg); border:1px solid var(--border);
		padding:.4rem .8rem; border-radius:4px; cursor:pointer; font-size:.85rem; }
	button:hover { background:#444; }
	button.primary { background:#2a5a8a; border-color:#3a7ab0; }
	input[type=text],input[type=password] {
		background:#222; color:var(--fg); border:1px solid var(--border);
		padding:.4rem .6rem; border-radius:4px; font-size:.85rem; }
	code { background:#222; padding:.1rem .3rem; border-radius:3px;
		font:13px/1.4 ui-monospace,monospace; color:#8e8; }
	pre { background:#222; padding:.5rem; border-radius:4px; overflow-x:auto; }
	mark { background:#2a5a2a; padding:.1rem .3rem; border-radius:3px;
		font-size:.8rem; }
	article { border:1px solid var(--border); border-radius:6px;
		padding:.75rem 1rem; margin-bottom:.5rem; }
	article summary { cursor:pointer; font-size:1rem; }
	article summary small { color:var(--dim); }
	article p { color:#bbb; font-size:.85rem; margin-top:.3rem; }
	.dim { color:var(--dim); }
`

// indexHTML is the agent list page. Vanilla JS fetch() polls
// /api/agents every 2 seconds — no external dependencies.
const indexHTML = `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>agentjam cockpit</title>
	<style>` + cssCommon + `</style>
</head>
<body>
	<main>
		<h1>&#9889; agentjam cockpit</h1>
		<div id="agent-list"><p class="dim">Loading...</p></div>
	</main>
	<script>
		async function refresh() {
			try {
				const r = await fetch('/api/agents');
				if (r.ok) {
					document.getElementById('agent-list').innerHTML = await r.text();
				}
			} catch(e) {}
		}
		refresh();
		setInterval(refresh, 2000);
	</script>
</body>
</html>`

// agentHTML is the single-agent detail page. A vanilla JS EventSource
// connects to the SSE endpoint for real-time events.
const agentHTML = `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>agentjam &mdash; {{.ID}}</title>
	<style>` + cssCommon + `
		.event { padding:.25rem 0; border-bottom:1px solid var(--border); font-size:.85rem; }
		.event small { color:var(--dim); }
		.actions { display:flex; gap:.5rem; flex-wrap:wrap; align-items:center; margin:1rem 0; }
		.actions input { flex:1; min-width:200px; }
		#events { max-height:70vh; overflow-y:auto; }
		nav { display:flex; align-items:center; gap:1rem; }
		nav h2 { margin:0; }
	</style>
</head>
<body>
	<main>
		<nav><h2><a href="/">&larr;</a> {{.ID}}</h2></nav>
		<div class="actions">
			<button onclick="doAction('assume')">Assume</button>
			<button onclick="doAction('relinquish')">Relinquish</button>
			<input type="text" id="msg" placeholder="Send a message..."
				onkeydown="if(event.key==='Enter')sendMsg()">
			<button onclick="sendMsg()">Send</button>
		</div>
		<div id="events"><p class="dim">Connecting...</p></div>
	</main>
	<script>
		(function() {
			var d = document.getElementById('events');
			var es = new EventSource('/api/agent/{{.ID}}/events');
			d.innerHTML = '';
			es.onmessage = function(e) {
				var row = document.createElement('div');
				row.className = 'event';
				row.innerHTML = e.data;
				d.prepend(row);
			};
			es.addEventListener('close', function() {
				d.innerHTML += '<p class="dim">Session ended.</p>';
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
	<style>` + cssCommon + `
		form { max-width:400px; }
		label { display:block; margin-bottom:.5rem; }
		input[type=password] { width:100%; margin-bottom:.75rem; }
	</style>
</head>
<body>
	<main>
		<h2>&#9889; agentjam cockpit</h2>
		<p class="dim">Enter your access token to continue.</p>
		<form method="POST" action="/login">
			<input type="hidden" name="return" value="{{.Return}}">
			<label>Token</label>
			<input type="password" name="token" placeholder="Access token" required autofocus>
			<button type="submit" class="primary">Connect</button>
		</form>
	</main>
</body>
</html>`
