<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Pill from '$lib/components/ui/Pill.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import { reports } from '$lib/api/client';
	import { ApiError } from '$lib/api/client';
	import type { WeeklyReport } from '$lib/api/types';

	let report = $state<WeeklyReport | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let generating = $state(false);
	let weeks = $state<string[]>([]);
	let selectedWeek = $state<string>('');

	async function load() {
		loading = true;
		error = null;
		try {
			const [latest, idx] = await Promise.all([
				reports.latest().catch((e) => {
					if (e instanceof ApiError && e.status === 404) return null;
					throw e;
				}),
				reports.index().catch(() => [] as string[])
			]);
			report = latest;
			weeks = idx;
			selectedWeek = latest?.iso_week ?? '';
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function onWeekChange(e: Event) {
		const target = e.currentTarget as HTMLSelectElement;
		const week = target.value;
		if (!week || (report && week === report.iso_week)) return;
		selectedWeek = week;
		loading = true;
		error = null;
		try {
			report = await reports.byWeek(week);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function generateNow() {
		generating = true;
		error = null;
		try {
			report = await reports.generate(selectedWeek || undefined);
			const next = await reports.index().catch(() => weeks);
			weeks = next;
			selectedWeek = report.iso_week;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			generating = false;
		}
	}

	onMount(load);

	function fmtNum(v: number | null | undefined, digits = 1): string {
		if (v === null || v === undefined) return '—';
		return v.toFixed(digits);
	}

	function dayLabel(d: string): string {
		try {
			return new Date(d).toLocaleDateString(undefined, { weekday: 'short', day: '2-digit' });
		} catch {
			return d;
		}
	}

	function metricLabel(name: string): string {
		const map: Record<string, string> = {
			sleep_score: 'Sleep',
			sleep_duration_min: 'Sleep dur',
			hrv_overnight_avg: 'HRV',
			resting_hr: 'RHR',
			stress_avg: 'Stress',
			readiness: 'Readiness'
		};
		return map[name] ?? name;
	}
</script>

<svelte:head>
	<title>Lattice · Weekly report</title>
</svelte:head>

<header class="page-header">
	<div class="title">
		<h1>Weekly report</h1>
		<span class="sub">{report ? report.iso_week : 'none yet'}</span>
	</div>
	<div class="header-right">
		{#if weeks.length > 0}
			<select class="week-picker" value={selectedWeek} onchange={onWeekChange}>
				{#each weeks as w (w)}
					<option value={w}>{w}</option>
				{/each}
			</select>
		{/if}
	</div>
</header>

{#if error}
	<div class="err">load failed: {error}</div>
{/if}

{#if loading}
	<div class="empty">loading…</div>
{:else if !report}
	<Card>
		<div class="empty-card">
			<Pill tone="warn">no report</Pill>
			<h2>No weekly report yet</h2>
			<p>
				The scheduler runs <span class="mono">weekly_report</span> Sundays at 22:00 (SPEC §9).
				You can also generate one now — it covers the ISO week containing today.
			</p>
			<Button variant="primary" disabled={generating} onclick={generateNow}>
				{generating ? 'generating…' : 'Generate now'}
			</Button>
		</div>
	</Card>
{:else}
	<div class="layout">
		<Card eyebrow={report.model_used}>
			<header class="summary-head">
				<div class="week">{report.iso_week}</div>
				<div class="sub">
					{report.stats.week_start} → {report.stats.week_end} · generated
					{new Date(report.generated_at).toLocaleString()}
				</div>
			</header>
			<p class="prose">{report.summary_text}</p>
			<div class="actions">
				<Button variant="ghost" disabled={generating} onclick={generateNow}>
					{generating ? 'regenerating…' : 'Regenerate'}
				</Button>
			</div>
		</Card>

		<div class="grid-3">
			{#each Object.entries(report.stats.averages) as [name, value] (name)}
				<Card>
					<div class="metric-stat">
						<div class="stat-label">{metricLabel(name)}</div>
						<div class="stat-value">{fmtNum(value, name === 'readiness' ? 0 : 1)}</div>
					</div>
				</Card>
			{/each}
		</div>

		<Card eyebrow="Daily breakdown">
			<div class="table-wrap">
				<table class="daily-table">
					<thead>
						<tr>
							<th></th>
							{#each report.stats.daily as d (d.date)}
								<th>{dayLabel(d.date)}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						<tr>
							<th class="rowhead">Readiness</th>
							{#each report.stats.daily as d (d.date + '-r')}
								<td>{d.readiness ?? '—'}</td>
							{/each}
						</tr>
						<tr>
							<th class="rowhead">Sleep</th>
							{#each report.stats.daily as d (d.date + '-s')}
								<td>{fmtNum(d.sleep_score, 0)}</td>
							{/each}
						</tr>
						<tr>
							<th class="rowhead">HRV</th>
							{#each report.stats.daily as d (d.date + '-h')}
								<td>{fmtNum(d.hrv_overnight_avg, 0)}</td>
							{/each}
						</tr>
						<tr>
							<th class="rowhead">RHR</th>
							{#each report.stats.daily as d (d.date + '-rhr')}
								<td>{fmtNum(d.resting_hr, 0)}</td>
							{/each}
						</tr>
					</tbody>
				</table>
			</div>
		</Card>

		<div class="grid-2">
			<Card eyebrow="Best day">
				{#if report.stats.best_day}
					<div class="bw-head">
						<div class="bw-date">{dayLabel(report.stats.best_day.date)}</div>
						<div class="bw-score tone-accent">{report.stats.best_day.readiness}</div>
					</div>
					<div class="sub">{report.stats.best_day.reason}</div>
				{:else}
					<div class="sub">—</div>
				{/if}
			</Card>
			<Card eyebrow="Worst day">
				{#if report.stats.worst_day}
					<div class="bw-head">
						<div class="bw-date">{dayLabel(report.stats.worst_day.date)}</div>
						<div class="bw-score tone-bad">{report.stats.worst_day.readiness}</div>
					</div>
					<div class="sub">{report.stats.worst_day.reason}</div>
				{:else}
					<div class="sub">—</div>
				{/if}
			</Card>
		</div>

		{#if report.stats.habits.length > 0}
			<Card eyebrow="Habits">
				<ul class="habits-list">
					{#each report.stats.habits as h (h.habit_id)}
						<li>
							<span class="habit-name">{h.name}</span>
							<span class="completion">{h.completed_this_week}/{h.target_per_week}</span>
							<span class="bar">
								<span
									class="bar-fill"
									style="width: {Math.min(100, h.week_completion_pct)}%"
								></span>
							</span>
							<span class="streak">{h.current_streak_days}d streak</span>
						</li>
					{/each}
				</ul>
			</Card>
		{/if}

		<div class="grid-2">
			<Card eyebrow="Correlations">
				{#if report.stats.correlations.length === 0}
					<div class="sub">No correlations crossed |r| &gt; 0.5 with n ≥ 5.</div>
				{:else}
					<ul class="corr-list">
						{#each report.stats.correlations as c (c.label)}
							<li>
								<span class="corr-label">{c.label}</span>
								<span
									class="r-val"
									class:pos={c.direction === 'positive'}
									class:neg={c.direction === 'negative'}
								>
									r = {c.r.toFixed(2)}
								</span>
								<span class="corr-n">n={c.n}</span>
							</li>
						{/each}
					</ul>
				{/if}
			</Card>
			<Card eyebrow="Mean shifts vs trailing 4w">
				{#if report.stats.mean_shifts.length === 0}
					<div class="sub">No metric drifted &gt; 1σ from baseline.</div>
				{:else}
					<ul class="shift-list">
						{#each report.stats.mean_shifts as m (m.metric)}
							<li>
								<span class="shift-name">{metricLabel(m.metric)}</span>
								<span class="shift-dir" class:up={m.direction === 'up'} class:down={m.direction === 'down'}>
									{m.direction === 'up' ? '▲' : '▼'} {Math.abs(m.delta_sd).toFixed(2)}σ
								</span>
								<span class="shift-val">
									{m.this_week_mean.toFixed(1)} <span class="vs">vs</span> {m.trailing_mean.toFixed(1)}
								</span>
							</li>
						{/each}
					</ul>
				{/if}
			</Card>
		</div>

		{#if report.stats.coverage_notes.length > 0}
			<Card>
				<div class="coverage">
					{#each report.stats.coverage_notes as note}
						<div class="coverage-note">⚠  {note}</div>
					{/each}
				</div>
			</Card>
		{/if}
	</div>
{/if}

<style>
	.page-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		margin-bottom: 28px;
		gap: 16px;
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
	.header-right {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.week-picker {
		background: var(--color-bg-2);
		color: var(--color-fg);
		border: 1px solid var(--color-border);
		font-size: 12px;
		padding: 6px 12px;
		border-radius: var(--r-sm);
		font-family: var(--font-mono);
	}
	.week-picker:focus {
		outline: none;
		border-color: var(--color-accent);
	}
	.mono {
		font-family: var(--font-mono);
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
		padding: 40px 0;
		text-align: center;
	}
	.empty-card {
		display: flex;
		flex-direction: column;
		gap: 12px;
		align-items: flex-start;
	}
	.empty-card h2 {
		font-size: 18px;
		margin: 4px 0 0;
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.empty-card p {
		font-size: 13px;
		color: var(--color-fg-mute);
		line-height: 1.6;
		margin: 0;
		max-width: 560px;
	}
	.layout {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
	.summary-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 10px;
		margin-bottom: 4px;
	}
	.week {
		font-size: 15px;
		font-weight: 600;
		color: var(--color-fg);
		font-family: var(--font-mono);
	}
	.prose {
		white-space: pre-wrap;
		font-size: 14px;
		line-height: 1.65;
		color: var(--color-fg);
		margin: 4px 0 0;
	}
	.actions {
		display: flex;
		justify-content: flex-end;
	}
	.grid-3 {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 16px;
	}
	.grid-2 {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 16px;
	}
	@media (max-width: 800px) {
		.grid-3 {
			grid-template-columns: repeat(2, 1fr);
		}
		.grid-2 {
			grid-template-columns: 1fr;
		}
	}
	.metric-stat {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.stat-label {
		font-size: 10.5px;
		text-transform: uppercase;
		color: var(--color-fg-dim);
		letter-spacing: 0.14em;
		font-weight: 500;
	}
	.stat-value {
		font-family: var(--font-mono);
		font-size: 26px;
		font-variant-numeric: tabular-nums;
		color: var(--color-fg);
		font-weight: 500;
		letter-spacing: -0.02em;
		line-height: 1.1;
	}
	.table-wrap {
		overflow-x: auto;
		margin: -4px;
		padding: 4px;
	}
	.daily-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12.5px;
		font-variant-numeric: tabular-nums;
	}
	.daily-table th,
	.daily-table td {
		text-align: center;
		padding: 8px 10px;
	}
	.daily-table thead th {
		font-weight: 500;
		color: var(--color-fg-dim);
		font-size: 10.5px;
		text-transform: uppercase;
		letter-spacing: 0.12em;
		border-bottom: 1px solid var(--color-border);
		font-family: var(--font-mono);
	}
	.rowhead {
		text-align: left !important;
		color: var(--color-fg-mute);
		font-weight: 500;
		text-transform: none !important;
		letter-spacing: normal !important;
		font-family: var(--font-sans) !important;
		font-size: 12px !important;
	}
	.daily-table tbody td {
		font-family: var(--font-mono);
		color: var(--color-fg);
	}
	.daily-table tbody tr:hover {
		background: var(--color-bg-2);
	}
	.bw-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		margin-bottom: 6px;
	}
	.bw-date {
		font-size: 13px;
		color: var(--color-fg-mute);
		font-family: var(--font-mono);
	}
	.bw-score {
		font-family: var(--font-mono);
		font-size: 28px;
		font-weight: 500;
		font-variant-numeric: tabular-nums;
		letter-spacing: -0.02em;
		line-height: 1;
	}
	.tone-accent {
		color: var(--color-accent);
	}
	.tone-bad {
		color: var(--color-bad);
	}
	.habits-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.habits-list li {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 60px minmax(0, 1fr) 90px;
		gap: 14px;
		align-items: center;
		font-size: 13px;
	}
	.habit-name {
		color: var(--color-fg);
	}
	.completion {
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--color-fg-mute);
		font-variant-numeric: tabular-nums;
		text-align: right;
	}
	.bar {
		height: 6px;
		background: var(--color-bg-3);
		border-radius: 999px;
		overflow: hidden;
	}
	.bar-fill {
		display: block;
		height: 100%;
		background: var(--color-accent);
		border-radius: 999px;
	}
	.streak {
		font-family: var(--font-mono);
		font-size: 11.5px;
		color: var(--color-fg-mute);
		text-align: right;
	}
	.corr-list,
	.shift-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
		font-size: 13px;
	}
	.corr-list li,
	.shift-list li {
		display: flex;
		gap: 12px;
		align-items: baseline;
		padding: 6px 0;
		border-bottom: 1px solid var(--color-border-2);
	}
	.corr-list li:last-child,
	.shift-list li:last-child {
		border-bottom: 0;
	}
	.corr-label,
	.shift-name {
		flex: 1;
		color: var(--color-fg);
		min-width: 0;
	}
	.r-val,
	.shift-dir,
	.shift-val {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: 12.5px;
	}
	.corr-n {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--color-fg-dim);
	}
	.pos,
	.up {
		color: var(--color-accent);
	}
	.neg,
	.down {
		color: var(--color-bad);
	}
	.shift-val {
		color: var(--color-fg-mute);
	}
	.shift-val .vs {
		color: var(--color-fg-dim);
		margin: 0 2px;
	}
	.coverage {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.coverage-note {
		font-size: 12px;
		color: var(--color-warn);
		font-family: var(--font-mono);
	}
</style>
