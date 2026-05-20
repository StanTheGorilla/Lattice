<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Pill from '$lib/components/ui/Pill.svelte';
	import ReadinessRing from '$lib/components/ReadinessRing.svelte';
	import { fns, entries as entriesApi } from '$lib/api/client';
	import type {
		AdvisorIntent,
		AdvisorOutput,
		CaffeineStatusOutput,
		Entry,
		ReadinessOutput,
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
	let caffeine = $state<CaffeineStatusOutput | null>(null);
	let recent = $state<Entry[]>([]);
	let intent = $state<AdvisorIntent>('learn');
	let advisorLoading = $state(false);
	let loading = $state(true);
	let sleepErr = $state<string | null>(null);
	let caffeineErr = $state<string | null>(null);

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

	async function loadAll() {
		loading = true;
		sleepErr = null;
		caffeineErr = null;
		await Promise.allSettled([
			fns.readiness().then((r) => { readiness = r; }).catch(console.error),
			fns.advisor(intent).then((a) => { advisor = a; }).catch(console.error),
			fns.trainingRec().then((t) => { training = t; }).catch(console.error),
			fns.sleepWindow().then((sw) => { sleep = sw; }).catch((e) => { sleepErr = String(e); console.error('sleep_window', e); }),
			fns.caffeineStatus().then((c) => { caffeine = c; }).catch((e) => { caffeineErr = String(e); console.error('caffeine', e); }),
			entriesApi.list({ limit: 8 }).then((e) => { recent = e.items; }).catch(console.error),
		]);
		loading = false;
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

		{#if advisorLoading}
			<div class="empty">…</div>
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
		{:else}
			<div class="empty">—</div>
		{/if}
	</Card>

	<Card eyebrow="Sleep window · F4">
		{#if sleep}
			<div class="sleep-times">
				<div class="time-block">
					<div class="time-label">Bed</div>
					<div class="time-val">{fmtTime(sleep.bedtime)}</div>
				</div>
				<div class="arrow">→</div>
				<div class="time-block">
					<div class="time-label">Wake</div>
					<div class="time-val">{fmtTime(sleep.wake_time)}</div>
				</div>
			</div>
			<div class="duration-row">
				<span class="duration-label">Target</span>
				<span class="duration-val">{fmtDuration(sleep.target_duration_min)}</span>
			</div>
			{#if sleep.flags.length > 0}
				<ul class="flags">
					{#each sleep.flags as f (f)}
						<li>{f}</li>
					{/each}
				</ul>
			{/if}
		{:else if sleepErr}
			<div class="card-err">{sleepErr}</div>
			<button class="retry-btn" onclick={loadAll}>retry</button>
		{:else if loading}
			<div class="empty">…</div>
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
			<div class="empty">…</div>
		{:else}
			<div class="card-err">no data — <button class="retry-link" onclick={loadAll}>retry</button></div>
		{/if}
	</Card>

	<Card eyebrow="Recent entries" meta={recent.length > 0 ? `last ${recent.length}` : ''}>
		{#if recent.length === 0}
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
</style>
