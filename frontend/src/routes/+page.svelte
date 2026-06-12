<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Pill from '$lib/components/ui/Pill.svelte';
	import ReadinessRing from '$lib/components/ReadinessRing.svelte';
	import BarChart from '$lib/components/BarChart.svelte';
	import LineChart from '$lib/components/LineChart.svelte';
	import { fns, entries as entriesApi, dashboardApi } from '$lib/api/client';
	import type {
		AdvisorIntent,
		AdvisorOutput,
		CaffeineStatusOutput,
		DashboardCard,
		Entry,
		ReadinessOutput,
		ResolvedLineBar,
		ResolvedTable,
		SleepWindowOutput,
		TrainingRecOutput
	} from '$lib/api/types';

	const INTENTS: AdvisorIntent[] = [
		'learn',
		'creative',
		'train',
		'rest',
		'meeting',
		'physical_task'
	];

	const COMPONENT_LABEL: Record<string, string> = {
		hrv: 'HRV',
		sleep: 'Sleep',
		rhr: 'RHR',
		bb: 'Body battery',
		stress: 'Stress'
	};

	let readiness = $state<ReadinessOutput | null>(null);
	let advisor = $state<AdvisorOutput | null>(null);
	let training = $state<TrainingRecOutput | null>(null);
	let sleep = $state<SleepWindowOutput | null>(null);
	let sleepFormula = $state<SleepWindowOutput | null>(null);
	let sleepTab = $state<'ai' | 'algorithm'>('ai');
	let caffeine = $state<CaffeineStatusOutput | null>(null);
	let recent = $state<Entry[]>([]);
	let intent = $state<AdvisorIntent>('learn');
	let advisorLoading = $state(false);
	let loading = $state(true);
	let sleepErr = $state<string | null>(null);
	let regenerating = $state(false);
	let reverting = $state(false);
	let formulaLoading = $state(false);
	let caffeineErr = $state<string | null>(null);

	// The stored recommendation (`sleep`) is what the rest of Lattice reads. It's
	// AI-owned iff its source is 'ai'; otherwise the algorithm is active.
	const aiActive = $derived(sleep?.source === 'ai');
	const aiRec = $derived(aiActive ? sleep : null);
	let cards = $state<DashboardCard[]>([]);
	let cardsErr = $state<string | null>(null);

	async function loadAdvisor(i: AdvisorIntent) {
		advisorLoading = true;
		try {
			advisor = await fns.advisor(i);
		} catch (e) {
			console.error('advisor error', e);
		} finally {
			advisorLoading = false;
		}
	}

	function pickIntent(i: AdvisorIntent) {
		intent = i;
		loadAdvisor(i);
	}

	async function regenerateSleep() {
		if (regenerating || reverting) return;
		regenerating = true;
		sleepErr = null;
		try {
			sleep = await fns.regenerateSleepWindow();
			sleepTab = 'ai';
		} catch (e) {
			sleepErr = String(e);
			console.error('regenerate sleep_window', e);
		} finally {
			regenerating = false;
		}
	}

	async function reloadFormula() {
		if (formulaLoading) return;
		formulaLoading = true;
		sleepErr = null;
		try {
			sleepFormula = await fns.sleepWindowFormula();
		} catch (e) {
			sleepErr = String(e);
			console.error('formula sleep_window', e);
		} finally {
			formulaLoading = false;
		}
	}

	// "Use this" on the Algorithm tab: drop the AI decision so the algorithm
	// becomes the active recommendation the rest of Lattice reads.
	async function useAlgorithm() {
		if (regenerating || reverting) return;
		reverting = true;
		sleepErr = null;
		try {
			sleep = await fns.revertSleepWindow();
			sleepFormula = sleep;
			sleepTab = 'algorithm';
		} catch (e) {
			sleepErr = String(e);
			console.error('revert sleep_window', e);
		} finally {
			reverting = false;
		}
	}

	async function loadAll() {
		loading = true;
		sleepErr = null;
		caffeineErr = null;
		cardsErr = null;
		await Promise.allSettled([
			fns.readiness().then((r) => { readiness = r; }).catch(console.error),
			fns.advisor(intent).then((a) => { advisor = a; }).catch(console.error),
			fns.trainingRec().then((t) => { training = t; }).catch(console.error),
			fns.sleepWindow().then((sw) => { sleep = sw; sleepTab = sw.source === 'ai' ? 'ai' : 'algorithm'; }).catch((e) => { sleepErr = String(e); console.error('sleep_window', e); }),
			fns.sleepWindowFormula().then((sw) => { sleepFormula = sw; }).catch((e) => { console.error('sleep_window formula', e); }),
			fns.caffeineStatus().then((c) => { caffeine = c; }).catch((e) => { caffeineErr = String(e); console.error('caffeine', e); }),
			entriesApi.list({ limit: 8 }).then((e) => { recent = e.items; }).catch(console.error),
			dashboardApi.listCards().then((r) => { cards = r.items; }).catch((e) => { cardsErr = String(e); console.error('dashboard cards', e); }),
		]);
		loading = false;
	}

	async function deleteCard(id: number) {
		if (!confirm('Delete this chart?')) return;
		try {
			await dashboardApi.deleteCard(id);
			cards = cards.filter((c) => c.id !== id);
		} catch (e) {
			console.error('delete card', e);
		}
	}

	async function moveCard(id: number, direction: 'up' | 'down') {
		try {
			await dashboardApi.moveCard(id, direction);
			const refreshed = await dashboardApi.listCards();
			cards = refreshed.items;
		} catch (e) {
			console.error('move card', e);
		}
	}

	function asLineBar(r: ResolvedLineBar | ResolvedTable): ResolvedLineBar {
		return r as ResolvedLineBar;
	}
	function asTable(r: ResolvedLineBar | ResolvedTable): ResolvedTable {
		return r as ResolvedTable;
	}

	onMount(loadAll);

	function fmtTime(iso: string): string {
		try {
			const d = new Date(iso);
			return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
		} catch {
			return iso;
		}
	}

	function fmtDuration(min: number | undefined): string {
		if (min === undefined || min === null) return '—';
		const h = Math.floor(min / 60);
		const m = Math.round(min % 60);
		return h > 0 ? `${h}h ${m}m` : `${m}m`;
	}

	function trainingTone(rec: string): 'ok' | 'warn' | 'bad' | 'accent' | 'neutral' {
		if (rec === 'rest') return 'bad';
		if (rec === 'easy') return 'warn';
		if (rec === 'moderate') return 'accent';
		if (rec === 'hard') return 'accent';
		return 'neutral';
	}

	const today = new Date();
	const todayLabel = today.toLocaleDateString([], {
		weekday: 'long',
		day: 'numeric',
		month: 'long'
	});
</script>

<svelte:head>
	<title>Lattice · Today</title>
</svelte:head>

<header class="page-header">
	<div class="title">
		<h1>Today</h1>
		<span class="date">{todayLabel}</span>
	</div>
</header>

{#snippet skel(height: number, width: string)}
	<div class="skeleton" style="height:{height}px;width:{width}"></div>
{/snippet}

{#snippet skelCard()}
	<div class="skel-stack">
		{@render skel(26, '55%')}
		{@render skel(13, '90%')}
		{@render skel(13, '75%')}
		{@render skel(13, '60%')}
	</div>
{/snippet}

<!-- Hero row: readiness + advisor -->
<div class="hero-grid">
	<Card eyebrow="Readiness · F1">
		{#if readiness}
			<div class="readiness-layout">
				<ReadinessRing data={readiness} size={150} />
				<div class="components">
					<div class="components-head">Components</div>
					<ul>
						{#each Object.entries(readiness.explanation.components) as [k, v] (k)}
							<li>
								<span class="k">{COMPONENT_LABEL[k] ?? k}</span>
								<span class="v">{(v * 100).toFixed(0)}</span>
							</li>
						{/each}
					</ul>
					{#if readiness.explanation.missing.length > 0}
						<div class="missing">missing · {readiness.explanation.missing.join(', ')}</div>
					{/if}
				</div>
			</div>
		{:else if loading}
			<div class="readiness-layout">
				<div class="skeleton skel-ring"></div>
				{@render skelCard()}
			</div>
		{:else}
			<div class="empty">—</div>
		{/if}
	</Card>

	<Card eyebrow="Advisor · F9a">
		<div class="intent-row">
			{#each INTENTS as i (i)}
				<button class="intent-btn" class:active={intent === i} onclick={() => pickIntent(i)}>
					{i.replace('_', ' ')}
				</button>
			{/each}
		</div>

		{#if advisorLoading || (loading && !advisor)}
			{@render skelCard()}
		{:else if advisor}
			<div class="advisor">
				<div class="rec">{advisor.recommendation}</div>

				{#if advisor.window}
					<div class="window-row">
						<span class="window-time">{fmtTime(advisor.window.start)} – {fmtTime(advisor.window.end)}</span>
						<span class="window-meta">
							focus <strong>{advisor.window.predicted_focus}</strong>
							· <span class="dim">{(advisor.confidence * 100).toFixed(0)}%</span>
						</span>
					</div>
				{:else}
					<div class="window-meta">
						confidence <strong>{(advisor.confidence * 100).toFixed(0)}%</strong>
					</div>
				{/if}

				<ul class="reasons">
					{#each advisor.reasons as r (r)}
						<li>{r}</li>
					{/each}
				</ul>
			</div>
		{/if}
	</Card>
</div>

<!-- Stats row -->
<div class="stats-grid">
	<Card eyebrow="Training · F3">
		{#if training}
			<div class="hero-stat">
				<div class="hero-num tone-{trainingTone(training.recommendation)}">
					{training.recommendation}
				</div>
				<div class="hero-sub">{(training.confidence * 100).toFixed(0)}% confidence</div>
			</div>
			<ul class="reasons compact">
				{#each training.rationale as r (r)}
					<li>{r}</li>
				{/each}
			</ul>
			<dl class="kv">
				<dt>AC ratio</dt>
				<dd>{training.inputs.ac_ratio ?? '—'}</dd>
				<dt>Days since hard</dt>
				<dd>{training.inputs.days_since_hard ?? '—'}</dd>
				<dt>Meetings</dt>
				<dd>{training.inputs.meeting_hours ?? '—'}h</dd>
			</dl>
		{:else if loading}
			{@render skelCard()}
		{:else}
			<div class="empty">—</div>
		{/if}
	</Card>

	{#snippet recBody(rec: SleepWindowOutput)}
		<div class="sleep-times">
			<div class="time-block">
				<div class="time-label">Bed</div>
				<div class="time-val">{fmtTime(rec.bedtime)}</div>
			</div>
			<div class="arrow">→</div>
			<div class="time-block">
				<div class="time-label">Wake</div>
				<div class="time-val">{fmtTime(rec.wake_time)}</div>
			</div>
		</div>
		<div class="duration-row">
			<span class="duration-label">Target</span>
			<span class="duration-val">{fmtDuration(rec.target_duration_min)}</span>
		</div>
		{#if rec.rationale}
			<p class="rationale">{rec.rationale}</p>
		{/if}
		{#if rec.flags.length > 0}
			<ul class="flags">
				{#each rec.flags as f (f)}
					<li>{f}</li>
				{/each}
			</ul>
		{/if}
	{/snippet}

	<Card eyebrow="Sleep window">
		{#if sleep || sleepFormula}
			<div class="sleep-tabs">
				<button class="tab" class:active={sleepTab === 'ai'} onclick={() => (sleepTab = 'ai')}>
					AI{#if aiActive}<span class="dot-active" title="active"></span>{/if}
				</button>
				<button
					class="tab"
					class:active={sleepTab === 'algorithm'}
					onclick={() => (sleepTab = 'algorithm')}
				>
					Algorithm{#if !aiActive}<span class="dot-active" title="active"></span>{/if}
				</button>
			</div>

			{#if sleepTab === 'ai'}
				{#if aiRec}
					{@render recBody(aiRec)}
					<div class="sleep-actions">
						<button class="regen-btn" onclick={regenerateSleep} disabled={regenerating || reverting}>
							{regenerating ? 'thinking…' : '↻ Regenerate'}
						</button>
					</div>
				{:else}
					<div class="tab-empty">No AI recommendation yet — it'll weigh the algorithm, your recovery and calendar.</div>
					<div class="sleep-actions">
						<button class="regen-btn" onclick={regenerateSleep} disabled={regenerating || reverting}>
							{regenerating ? 'thinking…' : '✦ Generate with AI'}
						</button>
					</div>
				{/if}
			{:else if sleepFormula}
				{@render recBody(sleepFormula)}
				<div class="sleep-actions">
					<button class="regen-btn" onclick={reloadFormula} disabled={formulaLoading}>
						{formulaLoading ? '…' : '↻ Reload'}
					</button>
					{#if aiActive}
						<button class="revert-btn" onclick={useAlgorithm} disabled={regenerating || reverting}>
							{reverting ? '…' : 'Use this'}
						</button>
					{/if}
				</div>
			{:else}
				<div class="empty">…</div>
			{/if}
		{:else if sleepErr}
			<div class="card-err">{sleepErr}</div>
			<button class="retry-btn" onclick={loadAll}>retry</button>
		{:else if loading}
			{@render skelCard()}
		{:else}
			<div class="card-err">no data — <button class="retry-link" onclick={loadAll}>retry</button></div>
		{/if}
	</Card>

	<Card eyebrow="Caffeine · F5">
		{#if caffeine}
			<div class="caf-row">
				<Pill tone={caffeine.safe_for_new_cup ? 'ok' : 'bad'} size="md">
					{caffeine.safe_for_new_cup ? 'OK for a cup' : 'No more today'}
				</Pill>
			</div>
			<div class="hero-stat">
				<div class="hero-num">{caffeine.residual_at_bedtime_mg}<span class="hero-unit">mg</span></div>
				<div class="hero-sub">at bedtime</div>
			</div>
			<dl class="kv">
				<dt>Cups today</dt>
				<dd>{caffeine.inputs.cups_today ?? 0}</dd>
				<dt>Last call</dt>
				<dd>{caffeine.last_call_minutes !== null ? `${caffeine.last_call_minutes}m` : 'over'}</dd>
				<dt>Hours to bed</dt>
				<dd>{caffeine.inputs.hours_to_bed ?? '—'}</dd>
			</dl>
		{:else if caffeineErr}
			<div class="card-err">{caffeineErr}</div>
			<button class="retry-btn" onclick={loadAll}>retry</button>
		{:else if loading}
			{@render skelCard()}
		{:else}
			<div class="card-err">no data — <button class="retry-link" onclick={loadAll}>retry</button></div>
		{/if}
	</Card>

	<Card eyebrow="Recent entries" meta={recent.length > 0 ? `last ${recent.length}` : ''}>
		{#if loading && recent.length === 0}
			{@render skelCard()}
		{:else if recent.length === 0}
			<div class="empty">No entries yet</div>
		{:else}
			<ul class="entries">
				{#each recent as e (e.id)}
					<li>
						<span class="glyph">{e.type[0].toUpperCase()}</span>
						<span class="type">{e.type.replace('_', ' ')}</span>
						<span class="time">{fmtTime(e.timestamp)}</span>
					</li>
				{/each}
			</ul>
		{/if}
	</Card>
</div>

<!-- User-created chart cards (added from chat via render_chart) -->
{#if cards.length > 0 || cardsErr}
	<section class="cards-section">
		<header class="cards-head">
			<h2>Your charts</h2>
			<span class="cards-hint">ask in chat to add or change them</span>
		</header>
		{#if cardsErr}
			<div class="card-err">{cardsErr}</div>
		{/if}
		<div class="cards-grid">
			{#each cards as card, i (card.id)}
				<Card eyebrow={card.chart_type.toUpperCase()} title={card.title}>
					<div class="card-controls">
						<button
							class="ctrl"
							disabled={i === 0}
							onclick={() => moveCard(card.id, 'up')}
							aria-label="Move up"
						>↑</button>
						<button
							class="ctrl"
							disabled={i === cards.length - 1}
							onclick={() => moveCard(card.id, 'down')}
							aria-label="Move down"
						>↓</button>
						<button
							class="ctrl ctrl-del"
							onclick={() => deleteCard(card.id)}
							aria-label="Delete"
						>×</button>
					</div>
					{#if card.chart_type === 'line'}
						<LineChart
							series={asLineBar(card.resolved).series}
							labels={asLineBar(card.resolved).labels}
							height={220}
						/>
					{:else if card.chart_type === 'bar'}
						<BarChart
							series={asLineBar(card.resolved).series}
							labels={asLineBar(card.resolved).labels}
							height={220}
						/>
					{:else if card.chart_type === 'table'}
						<div class="table-wrap">
							<table>
								<thead>
									<tr>
										{#each asTable(card.resolved).columns as col (col)}
											<th>{col}</th>
										{/each}
									</tr>
								</thead>
								<tbody>
									{#each asTable(card.resolved).rows as row, ri (ri)}
										<tr>
											{#each row as cell, ci (ci)}
												<td>{cell ?? '—'}</td>
											{/each}
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}
				</Card>
			{/each}
		</div>
	</section>
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
	.date {
		font-size: 13px;
		color: var(--color-fg-mute);
	}
	/* Hero row */
	.hero-grid {
		display: grid;
		grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
		gap: 16px;
		margin-bottom: 16px;
	}
	@media (max-width: 1000px) {
		.hero-grid {
			grid-template-columns: 1fr;
		}
	}

	.readiness-layout {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 28px;
		align-items: center;
	}
	@media (max-width: 600px) {
		.readiness-layout {
			grid-template-columns: 1fr;
			justify-items: center;
			gap: 16px;
		}
	}

	.components {
		display: flex;
		flex-direction: column;
		gap: 6px;
		min-width: 0;
	}
	.components-head {
		font-size: 10.5px;
		text-transform: uppercase;
		letter-spacing: 0.14em;
		color: var(--color-fg-dim);
		font-weight: 500;
		margin-bottom: 4px;
	}
	.components ul {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.components li {
		display: flex;
		justify-content: space-between;
		font-size: 13px;
		padding: 4px 0;
		border-bottom: 1px solid var(--color-border-2);
	}
	.components li:last-child {
		border-bottom: 0;
	}
	.components .k {
		color: var(--color-fg-mute);
	}
	.components .v {
		color: var(--color-fg);
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-weight: 500;
	}
	.missing {
		font-size: 11px;
		color: var(--color-warn);
		margin-top: 6px;
	}

	/* Advisor */
	.intent-row {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
	.intent-btn {
		font-size: 11.5px;
		padding: 5px 10px;
		border: 1px solid var(--color-border);
		background: var(--color-bg-2);
		color: var(--color-fg-mute);
		border-radius: 999px;
		cursor: pointer;
		text-transform: lowercase;
		transition: all 120ms;
		font-weight: 500;
	}
	.intent-btn:hover {
		color: var(--color-fg);
		border-color: var(--color-border-strong);
	}
	.intent-btn.active {
		border-color: var(--color-accent);
		color: var(--color-accent);
		background: var(--accent-12);
	}
	.advisor {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.rec {
		font-size: 22px;
		color: var(--color-fg);
		font-weight: 600;
		letter-spacing: -0.01em;
		font-family: var(--font-mono);
	}
	.window-row {
		display: flex;
		align-items: baseline;
		gap: 12px;
		flex-wrap: wrap;
	}
	.window-time {
		font-family: var(--font-mono);
		font-size: 17px;
		color: var(--color-accent);
		font-variant-numeric: tabular-nums;
		font-weight: 500;
	}
	.window-meta {
		font-size: 12.5px;
		color: var(--color-fg-mute);
	}
	.window-meta strong {
		color: var(--color-fg);
		font-weight: 600;
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
	}
	.window-meta .dim {
		color: var(--color-fg-dim);
	}

	.reasons {
		list-style: none;
		padding: 0;
		margin: 4px 0 0;
		display: flex;
		flex-direction: column;
		gap: 5px;
		font-size: 12.5px;
		color: var(--color-fg-mute);
		line-height: 1.5;
	}
	.reasons li {
		padding-left: 14px;
		position: relative;
	}
	.reasons li::before {
		content: '';
		position: absolute;
		left: 2px;
		top: 8px;
		width: 4px;
		height: 4px;
		border-radius: 50%;
		background: var(--color-fg-faint);
	}
	.reasons.compact {
		font-size: 12px;
		gap: 3px;
	}

	/* Stats row */
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 16px;
	}
	@media (max-width: 1100px) {
		.stats-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
	@media (max-width: 600px) {
		.stats-grid {
			grid-template-columns: 1fr;
		}
	}

	.hero-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.hero-num {
		font-family: var(--font-mono);
		font-size: 28px;
		font-weight: 500;
		font-variant-numeric: tabular-nums;
		color: var(--color-fg);
		line-height: 1.1;
		letter-spacing: -0.02em;
	}
	.hero-unit {
		font-size: 13px;
		color: var(--color-fg-dim);
		font-weight: 400;
		margin-left: 2px;
	}
	.hero-sub {
		font-size: 11.5px;
		color: var(--color-fg-mute);
	}
	.tone-accent {
		color: var(--color-accent);
	}
	.tone-warn {
		color: var(--color-warn);
	}
	.tone-bad {
		color: var(--color-bad);
	}
	.tone-ok {
		color: var(--color-ok);
	}
	.tone-neutral {
		color: var(--color-fg);
	}

	/* key/value list */
	.kv {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 4px 12px;
		font-size: 12px;
		margin: 4px 0 0;
	}
	.kv dt {
		color: var(--color-fg-mute);
	}
	.kv dd {
		margin: 0;
		color: var(--color-fg);
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	/* Sleep */
	.sleep-tabs {
		display: flex;
		gap: 4px;
		border-bottom: 1px solid var(--color-border);
		margin-bottom: 12px;
	}
	.tab {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-size: 12px;
		font-weight: 500;
		padding: 6px 10px;
		border: none;
		border-bottom: 2px solid transparent;
		margin-bottom: -1px;
		background: none;
		color: var(--color-fg-mute);
		cursor: pointer;
		transition: all 120ms;
	}
	.tab:hover {
		color: var(--color-fg);
	}
	.tab.active {
		color: var(--color-fg);
		border-bottom-color: var(--color-accent);
	}
	.dot-active {
		width: 5px;
		height: 5px;
		border-radius: 999px;
		background: var(--color-accent);
	}
	.tab-empty {
		font-size: 12px;
		line-height: 1.5;
		color: var(--color-fg-mute);
		padding: 4px 0 2px;
	}
	.prov-row {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.sleep-actions {
		margin-left: auto;
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
		justify-content: flex-end;
	}
	.regen-btn,
	.revert-btn {
		font-size: 11px;
		padding: 4px 10px;
		border: 1px solid var(--color-border);
		border-radius: 999px;
		background: var(--color-bg-2);
		color: var(--color-fg-mute);
		cursor: pointer;
		transition: all 120ms;
		white-space: nowrap;
	}
	.regen-btn:hover:not(:disabled),
	.revert-btn:hover:not(:disabled) {
		color: var(--color-fg);
		border-color: var(--color-accent);
		background: var(--accent-12);
	}
	.regen-btn:disabled,
	.revert-btn:disabled {
		opacity: 0.5;
		cursor: progress;
	}
	.rationale {
		margin: 0;
		font-size: 12px;
		line-height: 1.5;
		color: var(--color-fg-mute);
	}
	.sleep-times {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.time-block {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.time-label {
		font-size: 10.5px;
		text-transform: uppercase;
		letter-spacing: 0.12em;
		color: var(--color-fg-dim);
		font-weight: 500;
	}
	.time-val {
		font-family: var(--font-mono);
		font-size: 20px;
		font-variant-numeric: tabular-nums;
		color: var(--color-fg);
		font-weight: 500;
		letter-spacing: -0.01em;
	}
	.arrow {
		color: var(--color-fg-faint);
		font-size: 14px;
		margin-top: 12px;
	}
	.duration-row {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		padding-top: 8px;
		border-top: 1px solid var(--color-border-2);
	}
	.duration-label {
		font-size: 12px;
		color: var(--color-fg-mute);
	}
	.duration-val {
		font-family: var(--font-mono);
		font-size: 14px;
		font-variant-numeric: tabular-nums;
		color: var(--color-fg);
		font-weight: 500;
	}
	.flags {
		list-style: none;
		padding: 8px 10px;
		margin: 0;
		background: var(--warn-12);
		border: 1px solid rgba(212, 177, 90, 0.25);
		border-radius: var(--r-sm);
		display: flex;
		flex-direction: column;
		gap: 3px;
		font-size: 11.5px;
		color: var(--color-warn);
	}

	/* Caffeine */
	.caf-row {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	/* Recent entries */
	.entries {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
	}
	.entries li {
		display: grid;
		grid-template-columns: 22px 1fr auto;
		gap: 10px;
		align-items: center;
		font-size: 12px;
		padding: 7px 0;
		border-bottom: 1px solid var(--color-border-2);
	}
	.entries li:last-child {
		border-bottom: 0;
	}
	.glyph {
		width: 22px;
		height: 22px;
		border: 1px solid var(--color-border);
		background: var(--color-bg-2);
		border-radius: var(--r-sm);
		display: grid;
		place-items: center;
		color: var(--color-fg-mute);
		font-size: 10.5px;
		font-family: var(--font-mono);
		font-weight: 600;
	}
	.type {
		color: var(--color-fg);
		text-transform: capitalize;
	}
	.time {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--color-fg-dim);
		font-variant-numeric: tabular-nums;
	}

	.empty {
		color: var(--color-fg-dim);
		font-size: 12px;
		padding: 8px 0;
	}
	.skel-stack {
		display: flex;
		flex-direction: column;
		gap: 10px;
		width: 100%;
	}
	.skel-ring {
		width: 150px;
		height: 150px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.card-err {
		font-size: 11.5px;
		color: var(--color-bad);
		padding: 6px 0;
		word-break: break-all;
	}
	.retry-btn {
		margin-top: 6px;
		font-size: 11px;
		padding: 4px 10px;
		border: 1px solid var(--color-border);
		background: var(--color-bg-2);
		color: var(--color-fg-mute);
		border-radius: 999px;
		cursor: pointer;
	}
	.retry-link {
		background: none;
		border: none;
		color: var(--color-accent);
		cursor: pointer;
		font-size: inherit;
		padding: 0;
		text-decoration: underline;
	}

	/* User chart cards section */
	.cards-section {
		margin-top: 32px;
	}
	.cards-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		margin-bottom: 14px;
		gap: 12px;
	}
	.cards-head h2 {
		margin: 0;
		font-size: 16px;
		font-weight: 600;
		color: var(--color-fg);
		letter-spacing: -0.01em;
	}
	.cards-hint {
		font-size: 11px;
		color: var(--color-fg-dim);
		font-family: var(--font-mono);
	}
	.cards-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 16px;
	}
	@media (max-width: 900px) {
		.cards-grid {
			grid-template-columns: 1fr;
		}
	}
	.card-controls {
		display: flex;
		gap: 4px;
		justify-content: flex-end;
		margin-top: -4px;
	}
	.ctrl {
		width: 24px;
		height: 24px;
		display: grid;
		place-items: center;
		background: var(--color-bg-2);
		border: 1px solid var(--color-border);
		color: var(--color-fg-mute);
		border-radius: var(--r-sm);
		cursor: pointer;
		font-size: 13px;
		font-family: var(--font-mono);
		padding: 0;
		line-height: 1;
		transition: all 120ms;
	}
	.ctrl:hover:not(:disabled) {
		color: var(--color-fg);
		border-color: var(--color-border-strong);
	}
	.ctrl:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}
	.ctrl-del:hover:not(:disabled) {
		color: var(--color-bad);
		border-color: rgba(201, 106, 106, 0.4);
	}
	.table-wrap {
		overflow-x: auto;
	}
	.table-wrap table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
		font-family: var(--font-mono);
	}
	.table-wrap th {
		text-align: left;
		padding: 6px 10px;
		color: var(--color-fg-dim);
		border-bottom: 1px solid var(--color-border);
		font-weight: 600;
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.table-wrap td {
		padding: 6px 10px;
		color: var(--color-fg);
		border-bottom: 1px solid var(--color-border-2);
		font-variant-numeric: tabular-nums;
	}
	.table-wrap tr:last-child td {
		border-bottom: none;
	}
</style>
