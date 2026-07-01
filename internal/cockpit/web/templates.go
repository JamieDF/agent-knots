package web

import "html/template"

// indexHTML is the agent list page. HTMX polls /api/agents every 2
// seconds to refresh the list.
const indexHTML = `<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>agentjam cockpit</title>
	<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
	<script src="https://unpkg.com/[email protected]" defer></script>
</head>
<body>
	<main class="container">
		<h1>&#9889; agentjam cockpit</h1>
		<div id="agent-list"
		     hx-get="/api/agents"
		     hx-trigger="every 2s"
		     hx-swap="innerHTML">
			<p><em>Loading...</em></p>
		</div>
	</main>
</body>
</html>`

// agentHTML is the single-agent detail page. A vanilla JS EventSource
// connects to the SSE endpoint for real-time events. Action buttons
// send POST requests to the control API.
const agentHTML = `<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>agentjam &mdash; {{.ID}}</title>
	<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
	<style>
		.event { padding: 0.25rem 0; border-bottom: 1px solid #333; font-size: 0.875rem; }
		.event small { color: #888; }
		.actions { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; margin: 1rem 0; }
		.actions input { margin: 0; flex: 1; min-width: 200px; }
		#events { max-height: 70vh; overflow-y: auto; }
		nav { display: flex; align-items: center; gap: 1rem; }
		nav h2 { margin: 0; }
	</style>
</head>
<body>
	<main class="container">
		<nav>
			<h2><a href="/">&larr;</a> {{.ID}}</h2>
		</nav>
		<div class="actions">
			<button class="secondary" onclick="doAction('assume')">Assume Control</button>
			<button class="secondary" onclick="doAction('relinquish')">Relinquish</button>
			<input type="text" id="msg" placeholder="Send a message..."
				onkeydown="if(event.key==='Enter')sendMsg()">
			<button onclick="sendMsg()">Send</button>
		</div>
		<div id="events">
			<p><em>Connecting to event stream...</em></p>
		</div>
	</main>
	<script>
		(function() {
			const eventsDiv = document.getElementById('events');
			const es = new EventSource('/api/agent/{{.ID}}/events');

			eventsDiv.innerHTML = '';

			es.onmessage = function(e) {
				const div = document.createElement('div');
				div.className = 'event';
				div.innerHTML = e.data;
				eventsDiv.prepend(div);
			};

			es.addEventListener('close', function() {
				eventsDiv.innerHTML += '<p><em>Session ended.</em></p>';
				es.close();
			});

			es.onerror = function() {
				// Browser auto-reconnects on transient errors.
			};

			window.doAction = function(action) {
				fetch('/api/agent/{{.ID}}/' + action, { method: 'POST' });
			};

			window.sendMsg = function() {
				const input = document.getElementById('msg');
				const msg = input.value.trim();
				if (!msg) return;
				fetch('/api/agent/{{.ID}}/send', {
					method: 'POST',
					headers: {'Content-Type': 'application/x-www-form-urlencoded'},
					body: 'message=' + encodeURIComponent(msg)
				});
				input.value = '';
			};
		})();
	</script>
</body>
</html>`

// loginHTML is the token-entry page.
const loginHTML = `<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>agentjam cockpit &mdash; login</title>
	<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
</head>
<body>
	<main class="container">
		<h2>&#9889; agentjam cockpit</h2>
		<p>Enter your access token to continue.</p>
		<form method="POST" action="/login">
			<input type="hidden" name="return" value="{{.Return}}">
			<label>Token
				<input type="password" name="token" placeholder="Access token" required autofocus>
			</label>
			<button type="submit">Connect</button>
		</form>
	</main>
</body>
</html>`

// Compile-time check that template.HTML is used.
var _ template.HTML
