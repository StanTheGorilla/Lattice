<script lang="ts">
	import { tick } from 'svelte';
	import { fly } from 'svelte/transition';
	import { chatApi } from '$lib/api/client';
	import type { ChatMessage } from '$lib/api/types';

	type ChatMsg = ChatMessage & {
		tools?: { name: string; ok: boolean }[];
		actions?: string[];
	};

	// crypto.randomUUID() only exists in secure contexts (HTTPS/localhost). On a
	// plain-HTTP LAN address (http://<pi-ip>:8000) it's undefined and throws,
	// which would break the whole page at init. getRandomValues IS available in
	// insecure contexts, so fall back to it; Math.random as a last resort.
	function newSessionId(): string {
		const c = globalThis.crypto;
		if (c && typeof c.randomUUID === 'function') return c.randomUUID();
		const bytes = new Uint8Array(16);
		if (c && typeof c.getRandomValues === 'function') {
			c.getRandomValues(bytes);
		} else {
			for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
		}
		return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
	}

	let messages = $state<ChatMsg[]>([]);
	let input = $state('');
	let sending = $state(false);
	let sessionId = $state<string>(newSessionId());
	let bottomEl: HTMLDivElement | undefined = $state();
	let inputEl: HTMLTextAreaElement | undefined = $state();

	async function send() {
		const text = input.trim();
		if (!text || sending) return;
		input = '';
		messages = [...messages, { role: 'user', content: text }];
		sending = true;
		await tick();
		autogrow();
		bottomEl?.scrollIntoView({ behavior: 'smooth' });
		try {
			const res = await chatApi.send(sessionId, text);
			sessionId = res.session_id;
			messages = [
				...messages,
				{
					role: 'assistant',
					content: res.reply,
					tools: res.tool_calls.map((tc) => ({ name: tc.name, ok: tc.ok })),
					actions: res.actions_taken
				}
			];
		} catch (e) {
			messages = [
				...messages,
				{ role: 'assistant', content: `⚠ ${e instanceof Error ? e.message : String(e)}` }
			];
		} finally {
			sending = false;
			await tick();
			bottomEl?.scrollIntoView({ behavior: 'smooth' });
			inputEl?.focus();
		}
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			send();
		}
	}

	function autogrow() {
		if (!inputEl) return;
		inputEl.style.height = 'auto';
		inputEl.style.height = `${Math.min(inputEl.scrollHeight, 160)}px`;
	}

	function renderMarkdown(md: string): string {
		let html = md
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/^#### (.+)$/gm, '<h4>$1</h4>')
			.replace(/^### (.+)$/gm, '<h3>$1</h3>')
			.replace(/^## (.+)$/gm, '<h2>$1</h2>')
			.replace(/^# (.+)$/gm, '<h1>$1</h1>')
			.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
			.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
			.replace(/\*(.+?)\*/g, '<em>$1</em>')
			.replace(/`([^`]+)`/g, '<code>$1</code>')
			.replace(/^---+$/gm, '<hr>')
			.replace(/^[\*\-] (.+)$/gm, '<li>$1</li>')
			.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
		html = html.replace(/(<li>.*<\/li>\n?)+/g, (b) => `<ul>${b}</ul>`);
		html = html
			.split(/\n{2,}/)
			.map((block) => {
				block = block.trim();
				if (!block) return '';
				if (/^<(h[1-4]|ul|hr|li)/.test(block)) return block;
				return `<p>${block.replace(/\n/g, '<br>')}</p>`;
			})
			.join('\n');
		return html;
	}
</script>

<svelte:head>
	<title>Lattice · Chat</title>
</svelte:head>

<div class="chat-layout">
	<header class="chat-header">
		<h1>Chat</h1>
		<span class="session-id">session · {sessionId.slice(0, 8)}</span>
	</header>

	<div class="messages">
		{#if messages.length === 0}
			<div class="empty">
				<p>Ask anything — your biometrics, habits, plans, research.</p>
				<div class="suggestions">
					{#each ['How am I doing today?', 'What should I focus on this morning?', 'Research ways to improve my HRV', 'Log a latte'] as s (s)}
						<button class="suggestion" onclick={() => { input = s; send(); }}>{s}</button>
					{/each}
				</div>
			</div>
		{/if}

		{#each messages as msg, i (i)}
			<div class="message {msg.role}" in:fly={{ y: 8, duration: 200 }}>
				{#if msg.role === 'user'}
					<div class="bubble user-bubble">{msg.content}</div>
				{:else}
					{#if msg.tools && msg.tools.length > 0}
						<div class="tools-row">
							{#each msg.tools as t (t.name)}
								<span class="tool-chip" class:tool-fail={!t.ok}>{t.name}</span>
							{/each}
						</div>
					{/if}
					{#if msg.actions && msg.actions.length > 0}
						<div class="tools-row">
							{#each msg.actions as a (a)}
								<span class="action-chip">✓ {a}</span>
							{/each}
						</div>
					{/if}
					<div class="bubble assistant-bubble markdown">
						{@html renderMarkdown(msg.content)}
					</div>
				{/if}
			</div>
		{/each}

		{#if sending}
			<div class="message assistant" in:fly={{ y: 8, duration: 200 }}>
				<div class="bubble assistant-bubble thinking">
					<span class="dot"></span><span class="dot"></span><span class="dot"></span>
				</div>
			</div>
		{/if}

		<div bind:this={bottomEl}></div>
	</div>

	<div class="input-bar">
		<textarea
			bind:this={inputEl}
			bind:value={input}
			onkeydown={onKeydown}
			oninput={autogrow}
			placeholder="Message… (Enter to send, Shift+Enter for newline)"
			rows="1"
			disabled={sending}
		></textarea>
		<button class="send-btn" onclick={send} disabled={sending || !input.trim()}>
			{sending ? '…' : '↑'}
		</button>
	</div>
</div>

<style>
	:global(.chat-layout) {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 48px);
		max-width: 760px;
		margin: 0 auto;
	}
	.chat-header {
		display: flex;
		align-items: baseline;
		gap: 14px;
		padding-bottom: 16px;
		border-bottom: 1px solid var(--color-border-2);
		flex-shrink: 0;
	}
	.chat-header h1 {
		margin: 0;
		font-size: 22px;
		font-weight: 600;
		letter-spacing: -0.02em;
	}
	.session-id {
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--color-fg-dim);
	}
	.messages {
		flex: 1;
		overflow-y: auto;
		padding: 20px 0;
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
	.empty {
		margin: auto;
		text-align: center;
		color: var(--color-fg-dim);
		font-size: 13px;
		padding: 40px 0;
	}
	.empty p { margin: 0 0 20px; }
	.suggestions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		justify-content: center;
	}
	.suggestion {
		font-size: 12px;
		padding: 6px 14px;
		border: 1px solid var(--color-border);
		border-radius: 999px;
		background: var(--color-bg-2);
		color: var(--color-fg-mute);
		cursor: pointer;
		transition: all 120ms;
	}
	.suggestion:hover {
		color: var(--color-fg);
		border-color: var(--color-accent);
		background: var(--accent-12);
	}
	.message {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.message.user { align-items: flex-end; }
	.message.assistant { align-items: flex-start; }
	.bubble {
		max-width: 85%;
		padding: 10px 14px;
		border-radius: 14px;
		font-size: 13px;
		line-height: 1.6;
	}
	.user-bubble {
		background: var(--color-accent);
		color: #0a0a0f;
		font-weight: 500;
		border-bottom-right-radius: 4px;
	}
	.assistant-bubble {
		background: var(--color-bg-2);
		border: 1px solid var(--color-border);
		color: var(--color-fg-mute);
		border-bottom-left-radius: 4px;
	}
	.thinking {
		display: flex;
		gap: 4px;
		align-items: center;
		padding: 12px 16px;
	}
	.dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--color-fg-dim);
		animation: blink 1.2s infinite;
	}
	.dot:nth-child(2) { animation-delay: 0.2s; }
	.dot:nth-child(3) { animation-delay: 0.4s; }
	@keyframes blink {
		0%, 80%, 100% { opacity: 0.3; }
		40% { opacity: 1; }
	}
	.tools-row {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-bottom: 2px;
	}
	.tool-chip {
		font-size: 10px;
		padding: 2px 7px;
		border-radius: 999px;
		background: var(--accent-12);
		border: 1px solid rgba(93, 208, 200, 0.25);
		color: var(--color-accent);
		font-family: var(--font-mono);
	}
	.tool-chip.tool-fail {
		opacity: 0.55;
		border-color: rgba(201, 106, 106, 0.3);
		color: #c96a6a;
		background: rgba(201, 106, 106, 0.08);
	}
	.action-chip {
		font-size: 10px;
		padding: 2px 7px;
		border-radius: 999px;
		background: rgba(70, 200, 140, 0.1);
		border: 1px solid rgba(70, 200, 140, 0.3);
		color: #46c88c;
		font-family: var(--font-mono);
	}
	/* markdown inside assistant bubble */
	.markdown :global(h1), .markdown :global(h2), .markdown :global(h3) {
		color: var(--color-fg);
		font-weight: 600;
		margin: 10px 0 4px;
	}
	.markdown :global(h2) { font-size: 13px; }
	.markdown :global(h3) { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-fg-mute); }
	.markdown :global(p) { margin: 0 0 8px; }
	.markdown :global(p:last-child) { margin: 0; }
	.markdown :global(ul) { padding-left: 18px; margin: 0 0 8px; }
	.markdown :global(li) { margin-bottom: 3px; }
	.markdown :global(strong) { color: var(--color-fg); font-weight: 600; }
	.markdown :global(code) {
		font-family: var(--font-mono);
		font-size: 11px;
		background: var(--color-bg-1);
		border: 1px solid var(--color-border);
		border-radius: 3px;
		padding: 1px 4px;
		color: var(--color-accent);
	}
	.input-bar {
		display: flex;
		gap: 8px;
		align-items: flex-end;
		padding: 14px 0 0;
		border-top: 1px solid var(--color-border-2);
		flex-shrink: 0;
	}
	textarea {
		flex: 1;
		resize: none;
		padding: 10px 14px;
		border: 1px solid var(--color-border);
		border-radius: 12px;
		background: var(--color-bg-2);
		color: var(--color-fg);
		font-size: 13px;
		font-family: inherit;
		outline: none;
		transition: border-color 120ms;
		max-height: 160px;
		overflow-y: auto;
		line-height: 1.5;
	}
	textarea:focus {
		border-color: var(--color-accent);
		box-shadow: var(--ring);
	}
	textarea::placeholder { color: var(--color-fg-dim); }
	.send-btn {
		width: 40px;
		height: 40px;
		border-radius: 10px;
		border: none;
		background: var(--color-accent);
		color: #0a0a0f;
		font-size: 18px;
		font-weight: 700;
		cursor: pointer;
		flex-shrink: 0;
		transition:
			opacity var(--t-fast) var(--ease),
			background var(--t-fast) var(--ease),
			transform var(--t-fast) var(--ease);
	}
	.send-btn:hover:not(:disabled) {
		background: #74d8d1;
	}
	.send-btn:active:not(:disabled) {
		transform: scale(0.94);
	}
	.send-btn:disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}
</style>
