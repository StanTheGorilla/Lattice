<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import { memoryApi, pendingActionsApi, journalApi } from '$lib/api/client';
	import { toast } from '$lib/toast.svelte';
	import type { Memory, PendingAction, AIJournalEntry } from '$lib/api/types';

	let items = $state<Memory[]>([]);
	let error = $state<string | null>(null);

	let actions = $state<PendingAction[]>([]);
	let journal = $state<AIJournalEntry[]>([]);

	let newContent = $state('');
	let creating = $state(false);
	let createError = $state<string | null>(null);

	async function load() {
		try {
			const res = await memoryApi.list();
			items = res.items;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function loadActions() {
		try {
			actions = (await pendingActionsApi.list()).items;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function loadJournal() {
		try {
			journal = (await journalApi.list()).items;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(() => {
		load();
		loadActions();
		loadJournal();
	});

	async function resolveAction(id: number) {
		try {
			await pendingActionsApi.update(id, { status: 'done' });
			await loadActions();
			toast.info('resolved');
		} catch (e) {
			toast.error('update failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

	async function removeAction(id: number) {
		if (!confirm('delete this commitment?')) return;
		try {
			await pendingActionsApi.remove(id);
			await loadActions();
			toast.info('deleted');
		} catch (e) {
			toast.error('delete failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

	async function retireEntry(id: number) {
		try {
			await journalApi.update(id, { active: false });
			await loadJournal();
			toast.info('retired');
		} catch (e) {
			toast.error('update failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

	async function removeEntry(id: number) {
		if (!confirm('delete this journal entry?')) return;
		try {
			await journalApi.remove(id);
			await loadJournal();
			toast.info('deleted');
		} catch (e) {
			toast.error('delete failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

	async function addMemory(e: Event) {
		e.preventDefault();
		const content = newContent.trim();
		if (!content) return;
		creating = true;
		createError = null;
		try {
			await memoryApi.create(content);
			newContent = '';
			await load();
		} catch (err) {
			createError = err instanceof Error ? err.message : String(err);
		} finally {
			creating = false;
		}
	}

	async function remove(id: number) {
		if (!confirm('forget this memory?')) return;
		try {
			await memoryApi.remove(id);
			await load();
			toast.info('forgotten');
		} catch (e) {
			toast.error('delete failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

	function savedDate(iso: string): string {
		return (iso || '').slice(0, 10);
	}
</script>

<svelte:head>
	<title>Lattice · Memory</title>
</svelte:head>

<header class="page-header">
	<div class="title">
		<h1>Memory</h1>
		<span class="sub">{items.length} saved · what the assistant remembers about you</span>
	</div>
</header>

{#if error}
	<div class="err">load failed: {error}</div>
{/if}

<div class="layout">
	<div class="main-col">
		{#if items.length === 0}
			<Card>
				<div class="empty">Nothing remembered yet — the assistant saves durable facts here as you chat.</div>
			</Card>
		{:else}
			{#each items as m (m.id)}
				<Card>
					<div class="mem-row">
						<div class="mem-body">
							<p class="mem-content">{m.content}</p>
							<span class="sub">saved {savedDate(m.created_at)}</span>
						</div>
						<Button variant="ghost" size="sm" onclick={() => remove(m.id)}>forget</Button>
					</div>
				</Card>
			{/each}
		{/if}

		<div class="section-head">
			<h2>Open commitments</h2>
			<span class="sub">{actions.length} · things the assistant said it would do</span>
		</div>
		{#if actions.length === 0}
			<Card>
				<div class="empty">No open commitments.</div>
			</Card>
		{:else}
			{#each actions as a (a.id)}
				<Card>
					<div class="mem-row">
						<div class="mem-body">
							<p class="mem-content">{a.summary}</p>
							{#if a.detail}
								<span class="sub">{a.detail}</span>
							{/if}
							<span class="sub">status: {a.status} · {savedDate(a.created_at)}</span>
						</div>
						<div class="row-actions">
							{#if a.status === 'open'}
								<Button variant="ghost" size="sm" onclick={() => resolveAction(a.id)}>resolve</Button>
							{/if}
							<Button variant="ghost" size="sm" onclick={() => removeAction(a.id)}>delete</Button>
						</div>
					</div>
				</Card>
			{/each}
		{/if}

		<div class="section-head">
			<h2>AI journal</h2>
			<span class="sub">{journal.length} · self-authored guidance</span>
		</div>
		{#if journal.length === 0}
			<Card>
				<div class="empty">No journal entries yet.</div>
			</Card>
		{:else}
			{#each journal as j (j.id)}
				<Card>
					<div class="mem-row">
						<div class="mem-body">
							<p class="mem-content">{j.entry}</p>
							<span class="sub">
								{j.kind} · weight {j.weight} · {j.active ? 'active' : 'retired'}
							</span>
						</div>
						<div class="row-actions">
							{#if j.active}
								<Button variant="ghost" size="sm" onclick={() => retireEntry(j.id)}>retire</Button>
							{/if}
							<Button variant="ghost" size="sm" onclick={() => removeEntry(j.id)}>delete</Button>
						</div>
					</div>
				</Card>
			{/each}
		{/if}
	</div>

	<aside class="form-col">
		<Card eyebrow="New memory">
			<form onsubmit={addMemory} class="form">
				<label class="field">
					<span class="label">Fact to remember</span>
					<textarea
						class="raw-input"
						rows="3"
						bind:value={newContent}
						placeholder="Prefers morning workouts"
						disabled={creating}
					></textarea>
				</label>
				{#if createError}
					<div class="err">{createError}</div>
				{/if}
				<Button type="submit" variant="primary" disabled={creating || !newContent.trim()}>
					{creating ? 'saving…' : 'Add memory'}
				</Button>
			</form>
		</Card>
	</aside>
</div>

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
		margin-bottom: 12px;
		padding: 10px 14px;
		border-radius: var(--r-sm);
		background: var(--bad-12);
		color: var(--color-bad);
		font-size: 12px;
		border: 1px solid rgba(201, 106, 106, 0.3);
	}
	.layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 320px;
		gap: 20px;
	}
	@media (max-width: 1000px) {
		.layout {
			grid-template-columns: 1fr;
		}
	}
	.main-col {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
	.empty {
		font-size: 13px;
		color: var(--color-fg-dim);
		padding: 32px 0;
		text-align: center;
	}
	.section-head {
		display: flex;
		align-items: baseline;
		gap: 12px;
		margin-top: 12px;
	}
	.section-head h2 {
		margin: 0;
		font-size: 16px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.row-actions {
		display: flex;
		gap: 6px;
		flex-shrink: 0;
	}
	.mem-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
	}
	.mem-body {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.mem-content {
		margin: 0;
		font-size: 14px;
		color: var(--color-fg);
		line-height: 1.4;
	}
	.form {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 5px;
	}
	.label {
		font-size: 11px;
		color: var(--color-fg-mute);
		font-weight: 500;
	}
	.raw-input {
		padding: 8px 10px;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		background: var(--color-bg-2);
		color: var(--color-fg);
		font-size: 12.5px;
		font-family: inherit;
		outline: none;
		resize: vertical;
		transition: border-color 120ms, background 120ms;
	}
	.raw-input:focus {
		border-color: var(--color-accent);
		background: var(--color-bg-1);
	}
</style>
