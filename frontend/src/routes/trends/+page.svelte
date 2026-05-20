<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import LineChart from '$lib/components/LineChart.svelte';
	import { metrics, nutritionApi, analyticsApi } from '$lib/api/client';
	import type { AllostaticLoad, ChangepointResult, NutritionDayPoint } from '$lib/api/types';

	const METRICS: { name: string; label: string; color: string; yMin?: number; yMax?: number }[] = [
		{ name: 'sleep_score', label: 'Sleep score', color: '#5dd0c8', yMin: 0, yMax: 100 },
		{ name: 'hrv_overnight_avg', label: 'HRV overnight avg', color: '#b39ddc' },
		{ name: 'resting_hr', label: 'Resting HR', color: '#d4b15a' },
		{ name: 'body_battery_start', label: 'Body battery (morning)', color: '#6dbf7a', yMin: 0, yMax: 100 }
	];

	let series = $state<Record<string, { labels: string[]; values: (number | null)[] }>>({});
	let error = $state<string | null>(null);
	let nutritionSeries = $state<NutritionDayPoint[]>([]);
	let ali = $state<AllostaticLoad | null>(null);
	let changepoints = $state<Record<string, ChangepointResult>>({});

	function summarize(values: (number | null)[]): { last: number | null; avg: number | null; min: number | null; max: number | null } {
		const nums = values.filter((v): v is number => v !== null);
		if (nums.length === 0) return { last: null, avg: null, min: null, max: null };
		const last = values[values.length - 1] ?? null;
		const avg = nums.reduce((a, b) => a + b, 0) / nums.length;
		return {
			last,
			avg,
			min: Math.min(...nums),
			max: Math.max(...nums)
		};
	}

	function fmt(v: number | null, digits = 0): string {
		if (v === null || v === undefined) return '—';
		return v.toFixed(digits);
	}

	onMount(async () => {
		// Phase 1: charts — render immediately without waiting for heavy analytics
		try {
			const [metricResults, nutHistory] = await Promise.all([
				Promise.all(METRICS.map((m) => metrics.list({ name: m.name, limit: 60 }))),
				nutritionApi.history(30).catch(() => null)
			]);
			const next: typeof series = {};
			metricResults.forEach((r, i) => {
				const m = METRICS[i];
				const items = [...r.items].reverse();
				next[m.name] = {
					labels: items.map((it) =>
						new Date(it.timestamp).toLocaleDateString([], { month: 'short', day: 'numeric' })
					),
					values: items.map((it) => it.value)
				};
			});
			series = next;
			if (nutHistory) nutritionSeries = nutHistory.series;
		} catch (e) {
			console.error('trends load', e);
			error = e instanceof Error ? e.message : String(e);
		}

		// Phase 2: analytics — load independently, populate section when ready
		const CP_METRICS = ['hrv_overnight_avg', 'sleep_score', 'resting_hr'];
		const [aliResult, ...cpResults] = await Promise.all([
			analyticsApi.allostaticLoad().catch(() => null),
			...CP_METRICS.map((m) => analyticsApi.changepoints(m, 90).catch(() => null))
		]);
		if (aliResult) ali = aliResult;
		const cpMap: Record<string, ChangepointResult> = {};
		cpResults.forEach((r, i) => { if (r) cpMap[CP_METRICS[i]] = r; });
		changepoints = cpMap;
	});

	const nutLabels = $derived(
		nutritionSeries.map((d) =>
			new Date(d.date).toLocaleDateString([], { month: 'short', day: 'numeric' })
		)
	);
</script>

<svelte:head>
	<title>Lattice · Trends</title>
</svelte:head>

<header class="page-header">
	<div class="title">
		<h1>Trends</h1>
		<span class="sub">Last 60 entries per metric</span>
	</div>
</header>

{#if error}
	<div class="err">load failed: {error}</div>
{/if}

<div class="grid">
	{#each METRICS as m (m.name)}
		{@const s = series[m.name]}
		{@const stats = s ? summarize(s.values) : null}
		<Card>
			<header class="card-head">
				<div class="left">
					<span class="eyebrow">{m.label}</span>
					{#if stats && stats.last !== null}
						<div class="hero">
							<span class="last">{fmt(stats.last, m.name === 'hrv_overnight_avg' ? 0 : 0)}</span>
							<span class="hero-meta">latest</span>
						</div>
					{/if}
				</div>
				{#if stats && stats.avg !== null}
					<dl class="stats">
						<div><dt>avg</dt><dd>{fmt(stats.avg, 1)}</dd></div>
						<div><dt>min</dt><dd>{fmt(stats.min, 0)}</dd></div>
						<div><dt>max</dt><dd>{fmt(stats.max, 0)}</dd></div>
					</dl>
				{/if}
			</header>

			{#if s && s.values.length > 0}
				<div class="chart-wrap">
					<LineChart
						series={[{ name: m.label, data: s.values, color: m.color }]}
						labels={s.labels}
						yMin={m.yMin}
						yMax={m.yMax}
					/>
				</div>
			{:else if s}
				<div class="empty">no data yet</div>
			{:else}
				<div class="empty">loading…</div>
			{/if}
		</Card>
	{/each}
</div>

{#if nutritionSeries.length > 0}
	<section class="nut-section">
		<h2 class="section-title">Nutrition · last 30 days</h2>
		<div class="grid">
			<Card>
				<header class="card-head">
					<span class="eyebrow">Calories (kcal)</span>
					<dl class="stats">
						<div><dt>avg</dt><dd>{Math.round(nutritionSeries.reduce((a, d) => a + d.calories, 0) / nutritionSeries.length)}</dd></div>
						<div><dt>max</dt><dd>{Math.round(Math.max(...nutritionSeries.map(d => d.calories)))}</dd></div>
					</dl>
				</header>
				<div class="chart-wrap">
					<LineChart
						series={[{ name: 'Calories', data: nutritionSeries.map(d => d.calories), color: '#5dd0c8' }]}
						labels={nutLabels}
						yMin={0}
					/>
				</div>
			</Card>
			<Card>
				<header class="card-head">
					<span class="eyebrow">Protein · Carbs · Fat (g)</span>
				</header>
				<div class="chart-wrap">
					<LineChart
						series={[
							{ name: 'Protein', data: nutritionSeries.map(d => d.protein_g), color: '#6dbf7a' },
							{ name: 'Carbs',   data: nutritionSeries.map(d => d.carbs_g),   color: '#d4b15a' },
							{ name: 'Fat',     data: nutritionSeries.map(d => d.fat_g),     color: '#d47a5a' }
						]}
						labels={nutLabels}
						yMin={0}
					/>
				</div>
			</Card>
			<Card>
				<header class="card-head">
					<span class="eyebrow">Fiber · Sugar (g)</span>
				</header>
				<div class="chart-wrap">
					<LineChart
						series={[
							{ name: 'Fiber', data: nutritionSeries.map(d => d.fiber_g), color: '#5bbf7a' },
							{ name: 'Sugar', data: nutritionSeries.map(d => d.sugar_g), color: '#e0a05a' }
						]}
						labels={nutLabels}
						yMin={0}
					/>
				</div>
			</Card>
		</div>
	</section>
{/if}

{#if ali || Object.keys(changepoints).length > 0}
	<section class="nut-section">
		<h2 class="section-title">Analytics</h2>
		<div class="grid">
			{#if ali}
				<Card>
					<header class="card-head">
						<div class="left">
							<span class="eyebrow">Allostatic Load</span>
							<div class="hero">
								<span class="last" style="color: {ali.score >= 4 ? 'var(--color-bad)' : ali.score >= 2 ? 'var(--color-warn)' : '#46c88c'}">{ali.score}</span>
								<span class="hero-meta">/ {ali.max_score} · {ali.category}</span>
							</div>
						</div>
					</header>
					<p class="ali-interp">{ali.interpretation}</p>
					<div class="ali-grid">
						{#each ali.components as c (c.marker)}
							<div class="ali-row" class:flagged={c.flag}>
								<span class="ali-label">{c.label}</span>
								<span class="ali-val">{c.recent_mean != null ? c.recent_mean.toFixed(1) : '—'}</span>
								<span class="ali-flag">{c.flag ? '⚑' : '✓'}</span>
							</div>
						{/each}
					</div>
					{#if ali.low_confidence}
						<p class="ali-conf">Low confidence — fewer than 4 markers had data</p>
					{/if}
				</Card>
			{/if}
			{#each Object.entries(changepoints) as [metric, cp] (metric)}
				{#if cp.changepoints.length > 0}
					<Card>
						<header class="card-head">
							<div class="left">
								<span class="eyebrow">Change points · {metric.replace(/_/g, ' ')}</span>
								<span class="cp-count">{cp.changepoints.length} detected in {cp.days}d</span>
							</div>
						</header>
						<div class="cp-list">
							{#each cp.changepoints as point (point.date)}
								<div class="cp-row">
									<span class="cp-date">{new Date(point.date).toLocaleDateString([], { month: 'short', day: 'numeric' })}</span>
									<span class="cp-dir" class:up={point.direction === 'up'} class:dn={point.direction === 'down'}>
										{point.direction === 'up' ? '↑' : '↓'} {point.magnitude.toFixed(1)}
									</span>
									<span class="cp-z">z={point.z_score.toFixed(1)}</span>
								</div>
							{/each}
						</div>
					</Card>
				{/if}
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
	.sub {
		font-size: 13px;
		color: var(--color-fg-mute);
	}
	.err {
		margin-bottom: 16px;
		padding: 10px 14px;
		border-radius: var(--r-sm);
		background: var(--bad-12);
		color: var(--color-bad);
		font-size: 12px;
		border: 1px solid rgba(201, 106, 106, 0.3);
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 16px;
	}
	@media (max-width: 800px) {
		.grid {
			grid-template-columns: 1fr;
		}
	}
	.card-head {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 16px;
	}
	.left {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.eyebrow {
		font-size: 10.5px;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: var(--color-fg-dim);
		font-weight: 500;
	}
	.hero {
		display: flex;
		align-items: baseline;
		gap: 8px;
	}
	.last {
		font-family: var(--font-mono);
		font-size: 28px;
		font-weight: 500;
		font-variant-numeric: tabular-nums;
		color: var(--color-fg);
		line-height: 1;
		letter-spacing: -0.02em;
	}
	.hero-meta {
		font-size: 11.5px;
		color: var(--color-fg-mute);
	}
	.stats {
		display: flex;
		gap: 14px;
		margin: 0;
	}
	.stats div {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 2px;
	}
	.stats dt {
		font-size: 9.5px;
		text-transform: uppercase;
		letter-spacing: 0.12em;
		color: var(--color-fg-dim);
		font-weight: 500;
	}
	.stats dd {
		margin: 0;
		font-family: var(--font-mono);
		font-size: 13px;
		font-variant-numeric: tabular-nums;
		color: var(--color-fg);
	}
	.chart-wrap {
		margin-top: 4px;
	}
	.empty {
		text-align: center;
		font-size: 12px;
		color: var(--color-fg-dim);
		padding: 32px 0;
	}
	.nut-section {
		margin-top: 28px;
	}
	.section-title {
		font-size: 13px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--color-fg-dim);
		margin: 0 0 14px;
	}
	.ali-interp {
		font-size: 12px;
		color: var(--color-fg-mute);
		margin: 4px 0 12px;
		line-height: 1.5;
	}
	.ali-grid {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.ali-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 8px;
		border-radius: var(--r-sm);
		font-size: 12px;
	}
	.ali-row.flagged {
		background: var(--bad-12);
	}
	.ali-label { flex: 1; color: var(--color-fg-mute); }
	.ali-val { font-family: var(--font-mono); font-size: 11px; color: var(--color-fg); min-width: 40px; text-align: right; }
	.ali-flag { font-size: 11px; min-width: 16px; text-align: center; }
	.ali-row.flagged .ali-flag { color: var(--color-bad); }
	.ali-row:not(.flagged) .ali-flag { color: #46c88c; }
	.ali-conf { font-size: 11px; color: var(--color-fg-dim); margin-top: 10px; font-style: italic; }
	.cp-count { font-size: 12px; color: var(--color-fg-mute); margin-top: 4px; }
	.cp-list { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
	.cp-row {
		display: flex;
		align-items: center;
		gap: 10px;
		font-size: 12px;
	}
	.cp-date { font-family: var(--font-mono); font-size: 11px; color: var(--color-fg-mute); min-width: 56px; }
	.cp-dir { font-weight: 600; }
	.cp-dir.up { color: #46c88c; }
	.cp-dir.dn { color: var(--color-bad); }
	.cp-z { font-family: var(--font-mono); font-size: 11px; color: var(--color-fg-dim); }
</style>
