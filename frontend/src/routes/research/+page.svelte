<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import { researchApi } from '$lib/api/client';
	import type { ResearchPaper, ResearchPaperMeta } from '$lib/api/types';

	let papers = $state<ResearchPaperMeta[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let openFilename = $state<string | null>(null);
	let openPaper = $state<ResearchPaper | null>(null);
	let paperLoading = $state(false);

	onMount(async () => {
		try {
			papers = await researchApi.list();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	async function openDoc(filename: string) {
		if (openFilename === filename) {
			openFilename = null;
			openPaper = null;
			return;
		}
		openFilename = filename;
		openPaper = null;
		paperLoading = true;
		try {
			openPaper = await researchApi.get(filename);
		} catch {
			openPaper = null;
		} finally {
			paperLoading = false;
		}
	}

	function fmtDate(iso: string): string {
		if (!iso) return '';
		try {
			return new Date(iso).toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
		} catch {
			return iso;
		}
	}

	// Strip YAML frontmatter for display
	function bodyText(content: string): string {
		if (!content.startsWith('---')) return content;
		const end = content.indexOf('---', 3);
		return end === -1 ? content : content.slice(end + 3).trimStart();
	}
</script>

<svelte:head>
	<title>Lattice · Research</title>
</svelte:head>

<header class="page-header">
	<div class="title">
		<h1>Research</h1>
		<span class="sub">{papers.length} paper{papers.length !== 1 ? 's' : ''}</span>
	</div>
</header>

{#if error}
	<div class="err">{error}</div>
{:else if loading}
	<div class="empty">loading…</div>
{:else if papers.length === 0}
	<div class="empty">
		<p>No research papers saved yet.</p>
		<p class="hint">Ask the bot to research a topic — e.g. <em>"Research ways to improve HRV"</em> — and it will save a paper here.</p>
	</div>
{:else}
	<div class="paper-list">
		{#each papers as p (p.filename)}
			<Card padded={false}>
				<button
					class="paper-header"
					class:open={openFilename === p.filename}
					onclick={() => openDoc(p.filename)}
				>
					<div class="paper-meta">
						<span class="paper-title">{p.title}</span>
						<div class="paper-tags">
							{#if p.topic}
								<span class="tag topic">{p.topic}</span>
							{/if}
							{#if p.date}
								<span class="tag date">{fmtDate(p.date)}</span>
							{/if}
							{#if p.sources?.length}
								<span class="tag sources">{p.sources.length} source{p.sources.length !== 1 ? 's' : ''}</span>
							{/if}
						</div>
					</div>
					<span class="chevron" class:rotated={openFilename === p.filename}>›</span>
				</button>

				{#if openFilename === p.filename}
					<div class="paper-body">
						{#if paperLoading}
							<div class="body-loading">loading…</div>
						{:else if openPaper}
							<div class="markdown">{@html renderMarkdown(bodyText(openPaper.content))}</div>
							{#if openPaper.sources?.length}
								<div class="sources-section">
									<div class="sources-label">Sources</div>
									<ul class="sources-list">
										{#each openPaper.sources as src (src)}
											<li><span class="src-url">{src}</span></li>
										{/each}
									</ul>
								</div>
							{/if}
						{/if}
					</div>
				{/if}
			</Card>
		{/each}
	</div>
{/if}

<script lang="ts" module>
	// Minimal markdown renderer — headings, bold, italic, code, lists, paragraphs.
	// No external dep; good enough for LLM-generated research papers.
	function renderMarkdown(md: string): string {
		let html = md
			// escape HTML first
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			// headings
			.replace(/^#### (.+)$/gm, '<h4>$1</h4>')
			.replace(/^### (.+)$/gm, '<h3>$1</h3>')
			.replace(/^## (.+)$/gm, '<h2>$1</h2>')
			.replace(/^# (.+)$/gm, '<h1>$1</h1>')
			// bold + italic
			.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
			.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
			.replace(/\*(.+?)\*/g, '<em>$1</em>')
			// inline code
			.replace(/`([^`]+)`/g, '<code>$1</code>')
			// hr
			.replace(/^---+$/gm, '<hr>')
			// unordered list items
			.replace(/^[\*\-] (.+)$/gm, '<li>$1</li>')
			// numbered list items
			.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

		// wrap consecutive <li> in <ul>
		html = html.replace(/(<li>.*<\/li>\n?)+/g, (block) => `<ul>${block}</ul>`);

		// paragraphs: double newline → <p>
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

<style>
	.page-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		margin-bottom: 28px;
	}
	.title {
		display: flex;
		align-items: baseline;
		gap: 16px;
	}
	.title h1 {
		margin: 0;
		font-size: 28px;
		font-weight: 600;
		letter-spacing: -0.02em;
	}
	.sub {
		font-size: 13px;
		color: var(--color-fg-mute);
	}
	.err {
		padding: 10px 14px;
		border-radius: var(--r-sm);
		background: var(--bad-12);
		color: var(--color-bad);
		font-size: 12px;
		border: 1px solid rgba(201, 106, 106, 0.3);
	}
	.empty {
		text-align: center;
		padding: 60px 20px;
		color: var(--color-fg-dim);
		font-size: 13px;
	}
	.empty p { margin: 0 0 8px; }
	.hint { font-size: 12px; color: var(--color-fg-dim); }
	.hint em { font-style: italic; color: var(--color-fg-mute); }

	.paper-list {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.paper-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: 14px 18px;
		background: none;
		border: none;
		cursor: pointer;
		text-align: left;
		gap: 12px;
		transition: background 120ms;
		border-radius: var(--r-md);
	}
	.paper-header:hover {
		background: var(--color-bg-2);
	}
	.paper-header.open {
		border-bottom: 1px solid var(--color-border-2);
		border-radius: var(--r-md) var(--r-md) 0 0;
		background: var(--color-bg-2);
	}

	.paper-meta {
		display: flex;
		flex-direction: column;
		gap: 6px;
		flex: 1;
		min-width: 0;
	}
	.paper-title {
		font-size: 14px;
		font-weight: 600;
		color: var(--color-fg);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.paper-tags {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
	}
	.tag {
		font-size: 11px;
		padding: 2px 8px;
		border-radius: 999px;
		border: 1px solid var(--color-border);
		background: var(--color-bg-1);
		color: var(--color-fg-mute);
	}
	.tag.topic {
		color: var(--color-accent);
		background: var(--accent-12);
		border-color: rgba(93, 208, 200, 0.35);
	}

	.chevron {
		font-size: 20px;
		color: var(--color-fg-dim);
		transition: transform 200ms;
		flex-shrink: 0;
		line-height: 1;
	}
	.chevron.rotated {
		transform: rotate(90deg);
	}

	.paper-body {
		padding: 20px 24px 24px;
	}
	.body-loading {
		font-size: 12px;
		color: var(--color-fg-dim);
		font-style: italic;
	}

	/* markdown rendering */
	.markdown :global(h1) { font-size: 18px; font-weight: 700; margin: 0 0 12px; color: var(--color-fg); }
	.markdown :global(h2) { font-size: 15px; font-weight: 600; margin: 20px 0 8px; color: var(--color-fg); border-bottom: 1px solid var(--color-border-2); padding-bottom: 4px; }
	.markdown :global(h3) { font-size: 13px; font-weight: 600; margin: 16px 0 6px; color: var(--color-fg-mute); text-transform: uppercase; letter-spacing: 0.06em; }
	.markdown :global(h4) { font-size: 13px; font-weight: 600; margin: 12px 0 4px; color: var(--color-fg); }
	.markdown :global(p) { font-size: 13px; line-height: 1.7; color: var(--color-fg-mute); margin: 0 0 10px; }
	.markdown :global(ul) { padding-left: 20px; margin: 0 0 10px; }
	.markdown :global(li) { font-size: 13px; line-height: 1.6; color: var(--color-fg-mute); margin-bottom: 4px; }
	.markdown :global(strong) { color: var(--color-fg); font-weight: 600; }
	.markdown :global(em) { font-style: italic; }
	.markdown :global(code) { font-family: var(--font-mono); font-size: 11.5px; background: var(--color-bg-1); border: 1px solid var(--color-border); border-radius: 3px; padding: 1px 5px; color: var(--color-accent); }
	.markdown :global(hr) { border: none; border-top: 1px solid var(--color-border-2); margin: 16px 0; }

	.sources-section {
		margin-top: 20px;
		padding-top: 16px;
		border-top: 1px solid var(--color-border-2);
	}
	.sources-label {
		font-size: 10.5px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--color-fg-dim);
		margin-bottom: 8px;
	}
	.sources-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.src-url {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--color-fg-mute);
		word-break: break-all;
	}
</style>
