<script lang="ts">
	import { onMount } from 'svelte';
	import { planning } from '$lib/api/client';
	import type { AIRuleOut, AreaOut, DecisionOut, InitiativeOut, PlanOut } from '$lib/api/types';
	import Pill from '$lib/components/ui/Pill.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import { toast } from '$lib/toast.svelte';

	let plans = $state<PlanOut[]>([]);
	let areas = $state<AreaOut[]>([]);
	let initiatives = $state<InitiativeOut[]>([]);
	let decisions = $state<DecisionOut[]>([]);
	let rules = $state<AIRuleOut[]>([]);
	let loading = $state(true);

	// expanded plan body
	let expandedPlan = $state<number | null>(null);

	// status action in flight
	let actioning = $state<number | null>(null);

	// ── create-form state ──
	let addInitForArea = $state<number | null>(null); // area id the init form is open for
	let initTitle = $state('');
	let initWhy = $state('');
	let initTargetDate = $state('');
	let savingInit = $state(false);

	let showAddArea = $state(false);
	let areaName_ = $state('');
	let areaKey = $state('');
	let savingArea = $state(false);

	let showAddRule = $state(false);
	let ruleText = $state('');
	let savingRule = $state(false);

	async function loadAll() {
		[plans, areas, initiatives, decisions, rules] = await Promise.all([
			planning.listPlans(),
			planning.listAreas(),
			planning.listInitiatives(),
			planning.listDecisions({ status: 'open' }),
			planning.listRules()
		]);
	}

	onMount(async () => {
		await loadAll();
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

	function openInitForm(areaId: number) {
		addInitForArea = areaId;
		initTitle = '';
		initWhy = '';
		initTargetDate = '';
	}

	async function submitInitiative(areaId: number) {
		if (!initTitle.trim()) {
			toast.error('title is required');
			return;
		}
		savingInit = true;
		try {
			const created = await planning.createInitiative({
				area_id: areaId,
				title: initTitle.trim(),
				why: initWhy.trim() || undefined,
				target_date: initTargetDate || undefined
			});
			initiatives = [...initiatives, created];
			addInitForArea = null;
			toast.info('initiative added');
		} catch (e) {
			toast.error('add failed: ' + (e instanceof Error ? e.message : String(e)));
		} finally {
			savingInit = false;
		}
	}

	function slugify(s: string): string {
		return s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
	}

	async function submitArea() {
		const name = areaName_.trim();
		if (!name) {
			toast.error('name is required');
			return;
		}
		const key = (areaKey.trim() || slugify(name)).slice(0, 32);
		savingArea = true;
		try {
			const created = await planning.createArea({ key, name });
			areas = [...areas, created];
			showAddArea = false;
			areaName_ = '';
			areaKey = '';
			toast.info('area added');
		} catch (e) {
			toast.error('add failed: ' + (e instanceof Error ? e.message : String(e)));
		} finally {
			savingArea = false;
		}
	}

	async function submitRule() {
		if (!ruleText.trim()) {
			toast.error('rule text is required');
			return;
		}
		savingRule = true;
		try {
			const created = await planning.createRule({ rule: ruleText.trim() });
			rules = [...rules, created];
			showAddRule = false;
			ruleText = '';
			toast.info('rule added');
		} catch (e) {
			toast.error('add failed: ' + (e instanceof Error ? e.message : String(e)));
		} finally {
			savingRule = false;
		}
	}

	async function toggleRule(r: AIRuleOut) {
		try {
			const updated = await planning.patchRule(r.id, { active: !r.active });
			rules = rules.map((x) => (x.id === r.id ? updated : x));
		} catch (e) {
			toast.error('update failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

	async function removeRule(r: AIRuleOut) {
		if (!confirm('delete this AI rule?')) return;
		try {
			await planning.deleteRule(r.id);
			rules = rules.filter((x) => x.id !== r.id);
		} catch (e) {
			toast.error('delete failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

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
			<div class="section-head">
				<div class="section-label">Initiatives</div>
				<button class="link-btn" onclick={() => (showAddArea = !showAddArea)}>
					{showAddArea ? 'cancel' : '+ area'}
				</button>
			</div>

			{#if showAddArea}
				<div class="add-form">
					<input class="raw-input" bind:value={areaName_} placeholder="Area name (e.g. Health)" disabled={savingArea} />
					<input class="raw-input key" bind:value={areaKey} placeholder="key (optional)" disabled={savingArea} />
					<Button variant="primary" size="sm" onclick={submitArea} disabled={savingArea}>
						{savingArea ? '…' : 'Add'}
					</Button>
				</div>
			{/if}

			{#if areas.length === 0}
				<div class="empty-hint">No areas yet. Add one above to group your initiatives.</div>
			{:else}
				{#each areas as area (area.id)}
					{@const inits = areaInits(area.id)}
					<div class="area-block">
						<div class="area-head">
							<div class="area-name">{area.name}</div>
							<button class="link-btn" onclick={() => (addInitForArea === area.id ? (addInitForArea = null) : openInitForm(area.id))}>
								{addInitForArea === area.id ? 'cancel' : '+ initiative'}
							</button>
						</div>

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

						{#if addInitForArea === area.id}
							<div class="add-form col">
								<input class="raw-input" bind:value={initTitle} placeholder="Initiative title" disabled={savingInit} />
								<input class="raw-input" bind:value={initWhy} placeholder="Why it matters (optional)" disabled={savingInit} />
								<div class="add-form">
									<input class="raw-input" type="date" bind:value={initTargetDate} disabled={savingInit} />
									<Button variant="primary" size="sm" onclick={() => submitInitiative(area.id)} disabled={savingInit}>
										{savingInit ? '…' : 'Add initiative'}
									</Button>
								</div>
							</div>
						{:else if inits.length === 0}
							<div class="area-empty">No active initiatives.</div>
						{/if}
					</div>
				{/each}
			{/if}
		</section>

		<!-- ── AI Rules ── -->
		<section class="section">
			<div class="section-head">
				<div class="section-label">AI Rules</div>
				<button class="link-btn" onclick={() => (showAddRule = !showAddRule)}>
					{showAddRule ? 'cancel' : '+ rule'}
				</button>
			</div>
			<div class="add-hint">Standing instructions the assistant follows in every conversation.</div>

			{#if showAddRule}
				<div class="add-form col">
					<input class="raw-input" bind:value={ruleText} placeholder="e.g. Always use metric units" disabled={savingRule} />
					<Button variant="primary" size="sm" onclick={submitRule} disabled={savingRule}>
						{savingRule ? '…' : 'Add rule'}
					</Button>
				</div>
			{/if}

			{#if rules.length > 0}
				<div class="rules">
					{#each rules as r (r.id)}
						<div class="rule-row" class:off={!r.active}>
							<span class="rule-text">{r.rule}</span>
							<div class="rule-actions">
								<button class="act" onclick={() => toggleRule(r)}>{r.active ? 'mute' : 'enable'}</button>
								<button class="act" onclick={() => removeRule(r)}>delete</button>
							</div>
						</div>
					{/each}
				</div>
			{/if}
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
	.section-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 12px;
	}
	.section-label {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--color-fg-mute);
		margin-bottom: 12px;
	}
	.section-head .section-label {
		margin-bottom: 0;
	}
	.link-btn {
		font-size: 11px;
		color: var(--color-accent);
		background: none;
		border: 0;
		padding: 0;
		cursor: pointer;
		transition: opacity 120ms;
	}
	.link-btn:hover {
		opacity: 0.7;
	}
	.add-form {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 8px 0 14px;
	}
	.add-form.col {
		flex-direction: column;
		align-items: stretch;
	}
	.raw-input {
		flex: 1;
		padding: 7px 10px;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		background: var(--color-bg-2);
		color: var(--color-fg);
		font-size: 12.5px;
		font-family: inherit;
		outline: none;
		transition: border-color 120ms, background 120ms;
	}
	.raw-input:focus {
		border-color: var(--color-accent);
		background: var(--color-bg-1);
	}
	.raw-input.key {
		flex: 0 0 130px;
		font-family: var(--font-mono);
		font-size: 11.5px;
	}
	.area-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		margin-bottom: 6px;
	}
	.area-head .area-name {
		margin-bottom: 0;
	}
	.area-empty {
		font-size: 11.5px;
		color: var(--color-fg-faint);
		padding: 2px 0 6px 10px;
	}
	.rules {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.rule-row {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 7px 0 7px 10px;
		border-left: 2px solid var(--color-border);
		transition: border-color 120ms;
	}
	.rule-row:hover {
		border-left-color: var(--color-accent);
	}
	.rule-row.off {
		opacity: 0.45;
	}
	.rule-text {
		flex: 1;
		font-size: 12.5px;
		color: var(--color-fg);
		line-height: 1.4;
	}
	.rule-actions {
		display: flex;
		gap: 4px;
		flex-shrink: 0;
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
