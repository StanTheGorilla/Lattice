<script lang="ts">
	import { onMount } from 'svelte';
	import { planning } from '$lib/api/client';
	import type { AreaOut, DecisionOut, InitiativeOut, PlanOut } from '$lib/api/types';
	import Pill from '$lib/components/ui/Pill.svelte';

	let plans = $state<PlanOut[]>([]);
	let areas = $state<AreaOut[]>([]);
	let initiatives = $state<InitiativeOut[]>([]);
	let decisions = $state<DecisionOut[]>([]);
	let loading = $state(true);

	// expanded plan body
	let expandedPlan = $state<number | null>(null);

	// status action in flight
	let actioning = $state<number | null>(null);

	onMount(async () => {
		[plans, areas, initiatives, decisions] = await Promise.all([
			planning.listPlans(),
			planning.listAreas(),
			planning.listInitiatives(),
			planning.listDecisions({ status: 'open' })
		]);
		loading = false;
	});

	function areaName(id: number): string {
		return areas.find((a) => a.id === id)?.name ?? '—';
	}

	function areaInits(areaId: number) {
		return initiatives.filter(
			(i) => i.area_id === areaId && (i.status === 'active' || i.status === 'paused')
		);
	}

	const activeInitCount = $derived(initiatives.filter((i) => i.status === 'active').length);

	async function setStatus(init: InitiativeOut, newStatus: string) {
		if (actioning === init.id) return;
		actioning = init.id;
		try {
			const updated = await planning.patchInitiative(init.id, { status: newStatus });
			initiatives = initiatives.map((i) => (i.id === init.id ? updated : i));
		} finally {
			actioning = null;
		}
	}

	async function archivePlan(id: number) {
		await planning.patchPlan(id, { status: 'completed' });
		plans = plans.filter((p) => p.id !== id);
	}

	function daysUntil(iso: string): number {
		return Math.ceil((new Date(iso).getTime() - Date.now()) / 86400000);
	}

	function deadlineTone(iso: string): 'bad' | 'warn' | 'neutral' {
		const d = daysUntil(iso);
		if (d <= 3) return 'bad';
		if (d <= 14) return 'warn';
		return 'neutral';
	}

	function statusTone(s: string): 'accent' | 'warn' | 'neutral' {
		if (s === 'active') return 'accent';
		if (s === 'paused') return 'warn';
		return 'neutral';
	}
</script>

<div class="page">
	<div class="page-header">
		<h1 class="page-title">Protocol</h1>
		{#if activeInitCount > 0}
			<span class="count-pill">{activeInitCount} active</span>
		{/if}
	</div>

	{#if loading}
		<div class="loading">Loading…</div>
	{:else}
		<!-- ── AI Protocols ── -->
		<section class="section">
			<div class="section-label">Protocols</div>

			{#if plans.length === 0}
				<div class="empty-hint">
					No active protocols. Tell Lattice in chat: <em>"Create a protocol to improve my HRV"</em> and it will research your data and build one.
				</div>
			{:else}
				{#each plans as plan (plan.id)}
					<div class="plan-card">
						<div class="plan-header">
							<span class="plan-goal">{plan.goal}</span>
							<div class="plan-meta">
								{#if plan.metric && plan.target_value != null}
									<span class="meta-chip">{plan.metric} → {plan.target_value}</span>
								{/if}
								{#if plan.target_date}
									<span class="meta-chip">by {plan.target_date}</span>
								{/if}
								<button class="expand-btn" onclick={() => expandedPlan = expandedPlan === plan.id ? null : plan.id}>
									{expandedPlan === plan.id ? 'less' : 'protocol ↓'}
								</button>
								<button class="archive-btn" onclick={() => archivePlan(plan.id)} title="Mark complete">✓</button>
							</div>
						</div>

						{#if plan.progress_note}
							<div class="plan-progress">{plan.progress_note}</div>
						{/if}

						{#if expandedPlan === plan.id}
							<div class="plan-body">{plan.plan}</div>
						{/if}
					</div>
				{/each}
			{/if}
		</section>

		<!-- ── Initiatives ── -->
		<section class="section">
			<div class="section-label">Initiatives</div>

			{#if areas.length === 0}
				<div class="empty-hint">No areas set up yet.</div>
			{:else}
				{#each areas as area (area.id)}
					{@const inits = areaInits(area.id)}
					{#if inits.length > 0}
						<div class="area-block">
							<div class="area-name">{area.name}</div>
							{#each inits as init (init.id)}
								<div class="init-row" class:paused={init.status === 'paused'}>
									<div class="init-body">
										<span class="init-title">{init.title}</span>
										{#if init.why}
											<span class="init-sub">{init.why}</span>
										{/if}
										{#if init.target_date}
											<span class="init-date">by {init.target_date}</span>
										{/if}
									</div>
									<div class="init-actions">
										<Pill tone={statusTone(init.status)} size="sm">{init.status}</Pill>
										{#if init.status === 'active'}
											<button class="act" onclick={() => setStatus(init, 'paused')} disabled={actioning === init.id}>Pause</button>
											<button class="act" onclick={() => setStatus(init, 'completed')} disabled={actioning === init.id}>Done</button>
										{:else if init.status === 'paused'}
											<button class="act accent" onclick={() => setStatus(init, 'active')} disabled={actioning === init.id}>Resume</button>
											<button class="act" onclick={() => setStatus(init, 'abandoned')} disabled={actioning === init.id}>Drop</button>
										{/if}
									</div>
								</div>
							{/each}
						</div>
					{/if}
				{/each}
			{/if}
			<div class="add-hint">Add initiatives in chat or via Settings → Areas.</div>
		</section>

		<!-- ── Open Decisions ── -->
		{#if decisions.length > 0}
			<section class="section">
				<div class="section-label">Open Decisions</div>
				{#each decisions as d (d.id)}
					<div class="decision-row">
						<span class="d-q">{d.question}</span>
						<div class="d-meta">
							{#if d.deadline}
								<Pill tone={deadlineTone(d.deadline)} size="sm">by {d.deadline}</Pill>
							{/if}
						</div>
					</div>
				{/each}
				<div class="add-hint">Decide in chat: <em>"My decision on X is…"</em></div>
			</section>
		{/if}
	{/if}
</div>

<style>
	.page-header {
		display: flex;
		align-items: baseline;
		gap: 12px;
		margin-bottom: 32px;
	}
	.page-title {
		font-size: 22px;
		font-weight: 600;
		color: var(--color-fg);
		margin: 0;
	}
	.count-pill {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--color-accent);
		background: var(--accent-12);
		border: 1px solid rgba(93, 208, 200, 0.4);
		border-radius: 999px;
		padding: 2px 9px;
	}
	.loading {
		font-size: 12px;
		color: var(--color-fg-dim);
		padding: 20px 0;
	}

	/* ── sections ── */
	.section {
		margin-bottom: 36px;
	}
	.section-label {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--color-fg-mute);
		margin-bottom: 12px;
	}
	.empty-hint {
		font-size: 12.5px;
		color: var(--color-fg-dim);
		line-height: 1.6;
		max-width: 520px;
	}
	.empty-hint em {
		font-style: normal;
		color: var(--color-fg);
		font-family: var(--font-mono);
		font-size: 12px;
	}
	.add-hint {
		font-size: 11.5px;
		color: var(--color-fg-faint);
		margin-top: 10px;
		line-height: 1.5;
	}
	.add-hint em {
		font-style: normal;
		color: var(--color-fg-dim);
		font-family: var(--font-mono);
		font-size: 11px;
	}

	/* ── plans ── */
	.plan-card {
		padding: 14px 0;
		border-bottom: 1px solid var(--color-border);
	}
	.plan-card:last-child {
		border-bottom: 0;
	}
	.plan-header {
		display: flex;
		align-items: flex-start;
		gap: 12px;
		justify-content: space-between;
	}
	.plan-goal {
		font-size: 14px;
		font-weight: 500;
		color: var(--color-fg);
		line-height: 1.4;
		flex: 1;
	}
	.plan-meta {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
	}
	.meta-chip {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--color-fg-mute);
		background: var(--color-bg-2);
		border: 1px solid var(--color-border);
		border-radius: 999px;
		padding: 1px 8px;
	}
	.expand-btn {
		font-size: 11px;
		color: var(--color-accent);
		background: none;
		border: 0;
		padding: 0;
		cursor: pointer;
		transition: opacity 120ms;
	}
	.expand-btn:hover { opacity: 0.7; }
	.archive-btn {
		font-size: 13px;
		color: var(--color-fg-faint);
		background: none;
		border: 0;
		padding: 0 2px;
		cursor: pointer;
		transition: color 120ms;
	}
	.archive-btn:hover { color: var(--color-accent); }
	.plan-progress {
		margin-top: 6px;
		font-size: 12px;
		color: var(--color-fg-dim);
		line-height: 1.5;
	}
	.plan-body {
		margin-top: 10px;
		font-size: 12.5px;
		color: var(--color-fg-dim);
		line-height: 1.65;
		white-space: pre-wrap;
		padding: 10px 12px;
		background: var(--color-bg-1);
		border: 1px solid var(--color-border);
		border-radius: var(--r-md);
	}

	/* ── initiatives ── */
	.area-block {
		margin-bottom: 16px;
	}
	.area-name {
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-fg-faint);
		margin-bottom: 6px;
	}
	.init-row {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		padding: 7px 0 7px 10px;
		border-left: 2px solid var(--color-border);
		margin-bottom: 3px;
		transition: border-color 120ms;
	}
	.init-row:hover { border-left-color: var(--color-accent); }
	.init-row.paused { opacity: 0.5; }
	.init-body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.init-title {
		font-size: 13px;
		font-weight: 500;
		color: var(--color-fg);
		line-height: 1.3;
	}
	.init-sub {
		font-size: 11.5px;
		color: var(--color-fg-dim);
	}
	.init-date {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--color-fg-faint);
	}
	.init-actions {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}
	.act {
		font-size: 11px;
		color: var(--color-fg-dim);
		background: none;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		padding: 1px 8px;
		cursor: pointer;
		height: 22px;
		transition: background 120ms, color 120ms;
	}
	.act:hover:not(:disabled) {
		background: var(--color-bg-2);
		color: var(--color-fg);
	}
	.act:disabled { opacity: 0.4; cursor: default; }
	.act.accent {
		color: var(--color-accent);
		border-color: rgba(93, 208, 200, 0.4);
		background: var(--accent-12);
	}

	/* ── decisions ── */
	.decision-row {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		padding: 8px 0;
		border-bottom: 1px solid var(--color-border);
	}
	.decision-row:last-of-type { border-bottom: 0; }
	.d-q {
		flex: 1;
		font-size: 13px;
		color: var(--color-fg);
		line-height: 1.4;
	}
	.d-meta {
		flex-shrink: 0;
	}
</style>
