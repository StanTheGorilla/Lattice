<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import { algorithmsApi } from '$lib/api/client';
	import { toast } from '$lib/toast.svelte';
	import type { AlgorithmRow } from '$lib/api/types';

	let items = $state<AlgorithmRow[]>([]);
	let error = $state<string | null>(null);

	async function load() {
		try {
			items = await algorithmsApi.list();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(load);

	async function remove(name: string) {
		if (!confirm(`Delete algorithm "${name}"? The AI will no longer have access to it.`)) return;
		try {
			await algorithmsApi.remove(name);
			await load();
			toast.info(`Deleted algo_${name}`);
		} catch (e) {
			toast.error('Delete failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

	function fmtDate(iso: string): string {
		return (iso ?? '').slice(0, 10);
	}
</script>

<svelte:head>
	<title>Lattice · Algorithms</title>
</svelte:head>

<div class="page-header">
	<div class="title">
		<h1>Algorithms</h1>
		<span class="sub">{items.length} saved · authored by the AI assistant</span>
	</div>
</div>

{#if error}
	<div class="err">Failed to load: {error}</div>
{/if}

{#if items.length === 0 && !error}
	<Card>
		<div class="empty">
			No algorithms saved yet. The assistant creates these automatically to avoid
			recomputing the same logic across sessions. You can also ask it to create one.
		</div>
	</Card>
{:else}
	{#each items as algo (algo.id)}
		<Card>
			<div class="algo-row">
				<div class="algo-body">
					<div class="algo-name">algo_{algo.name}</div>
					<p class="algo-desc">{algo.description}</p>
					<span class="algo-meta">
						saved {fmtDate(algo.created_at)}
						{#if algo.updated_at !== algo.created_at}
							· updated {fmtDate(algo.updated_at)}
						{/if}
					</span>
				</div>
				<Button variant="ghost" size="sm" onclick={() => remove(algo.name)}>delete</Button>
			</div>
		</Card>
	{/each}
{/if}

<style>
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		margin-bottom: 24px;
	}
	.title h1 {
		margin: 0 0 2px;
		font-size: 22px;
		font-weight: 600;
		letter-spacing: -0.02em;
	}
	.sub {
		font-size: 12px;
		color: var(--color-fg-dim);
		font-family: var(--font-mono);
	}
	.err {
		color: var(--color-bad);
		font-size: 13px;
		margin-bottom: 16px;
	}
	.empty {
		color: var(--color-fg-mute);
		font-size: 13px;
		padding: 8px 0;
	}
	.algo-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}
	.algo-body {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}
	.algo-name {
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--color-accent);
		font-weight: 600;
	}
	.algo-desc {
		margin: 0;
		font-size: 14px;
		color: var(--color-fg);
		line-height: 1.5;
	}
	.algo-meta {
		font-size: 11px;
		color: var(--color-fg-dim);
		font-family: var(--font-mono);
	}
</style>
