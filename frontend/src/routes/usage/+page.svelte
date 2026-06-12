<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import { observabilityApi } from '$lib/api/client';
	import type { LlmUsageSummary } from '$lib/api/types';

	let summary = $state<LlmUsageSummary | null>(null);
	let error = $state<string | null>(null);
	let loading = $state(true);

	async function load() {
		loading = true;
		error = null;
		try {
			summary = await observabilityApi.llmUsage(30);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	onMount(load);

	const maxTotal = $derived(
		summary && summary.days.length ? Math.max(...summary.days.map((d) => d.total_tokens)) : 0
	);

	function fmt(n: number): string {
		return n.toLocaleString('en-US');
	}

	function usd(n: number): string {
		return `$${n.toFixed(n < 1 ? 4 : 2)}`;
	}
</script>

<svelte:head>
	<title>Lattice · Usage</title>
</svelte:head>

<header class="page-header">
	<div class="title">
		<h1>LLM Usage</h1>
		<span class="sub">DeepSeek tokens &amp; estimated cost — last 30 days</span>
	</div>
</header>

{#if error}
	<div class="err">load failed: {error}</div>
{:else if loading}
	<Card><div class="empty">loading…</div></Card>
{:else if summary}
	<div class="totals">
		<Card>
			<div class="stat">
				<span class="stat-label">Input tokens</span>
				<span class="stat-value">{fmt(summary.totals.input_tokens)}</span>
			</div>
		</Card>
		<Card>
			<div class="stat">
				<span class="stat-label">Output tokens</span>
				<span class="stat-value">{fmt(summary.totals.output_tokens)}</span>
			</div>
		</Card>
		<Card>
			<div class="stat">
				<span class="stat-label">Total tokens</span>
				<span class="stat-value">{fmt(summary.totals.total_tokens)}</span>
			</div>
		</Card>
		<Card>
			<div class="stat">
				<span class="stat-label">Est. cost</span>
				<span class="stat-value accent">{usd(summary.totals.est_cost_usd)}</span>
			</div>
		</Card>
	</div>

	<Card eyebrow="Daily breakdown">
		{#if summary.days.length === 0}
			<div class="empty">No LLM usage recorded yet.</div>
		{:else}
			<table class="usage-table">
				<thead>
					<tr>
						<th>Date</th>
						<th class="num">Input</th>
						<th class="num">Output</th>
						<th class="num">Total</th>
						<th class="num">Est. cost</th>
						<th class="bar-col"></th>
					</tr>
				</thead>
				<tbody>
					{#each summary.days as d (d.date)}
						<tr>
							<td class="mono">{d.date}</td>
							<td class="num">{fmt(d.input_tokens)}</td>
							<td class="num">{fmt(d.output_tokens)}</td>
							<td class="num">{fmt(d.total_tokens)}</td>
							<td class="num">{usd(d.est_cost_usd)}</td>
							<td class="bar-col">
								<div class="bar-track">
									<div
										class="bar-fill"
										style="width: {maxTotal ? (d.total_tokens / maxTotal) * 100 : 0}%"
									></div>
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
		<p class="note">
			Cost is an estimate at {usd(summary.input_usd_per_mtok)}/M input and
			{usd(summary.output_usd_per_mtok)}/M output tokens (DeepSeek cache-miss rates). Cache hits
			cost less, so the real bill is typically lower.
		</p>
	</Card>
{/if}

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
	.empty {
		font-size: 13px;
		color: var(--color-fg-dim);
		padding: 32px 0;
		text-align: center;
	}
	.totals {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 16px;
		margin-bottom: 20px;
	}
	@media (max-width: 720px) {
		.totals {
			grid-template-columns: repeat(2, 1fr);
		}
	}
	.stat {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.stat-label {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-fg-mute);
	}
	.stat-value {
		font-family: var(--font-mono, monospace);
		font-size: 22px;
		font-weight: 600;
		color: var(--color-fg);
	}
	.stat-value.accent {
		color: var(--color-accent);
	}
	.usage-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12.5px;
	}
	.usage-table th {
		text-align: left;
		font-weight: 500;
		font-size: 11px;
		color: var(--color-fg-mute);
		padding: 6px 10px;
		border-bottom: 1px solid var(--color-border);
	}
	.usage-table td {
		padding: 7px 10px;
		border-bottom: 1px solid var(--color-border);
		color: var(--color-fg-dim);
	}
	.usage-table .num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.usage-table .mono {
		font-family: var(--font-mono, monospace);
		color: var(--color-fg);
	}
	.bar-col {
		width: 120px;
	}
	.bar-track {
		height: 6px;
		border-radius: 3px;
		background: var(--color-bg-2);
		overflow: hidden;
	}
	.bar-fill {
		height: 100%;
		background: var(--color-accent);
		border-radius: 3px;
	}
	.note {
		margin: 14px 0 0;
		font-size: 11.5px;
		color: var(--color-fg-mute);
		line-height: 1.5;
	}
</style>
