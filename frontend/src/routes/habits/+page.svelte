<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import { habits as habitsApi, fns, reports } from '$lib/api/client';
	import { toast } from '$lib/toast.svelte';
	import type { HabitAdherence, HabitCheckin, HabitDefinition, WeeklyReport } from '$lib/api/types';

	const DAYS = 14;

	let defs = $state<HabitDefinition[]>([]);
	let adherence = $state<HabitAdherence[]>([]);
	let checkinsByHabit = $state<Record<number, Set<string>>>({});
	let error = $state<string | null>(null);

	let weeklyReport = $state<WeeklyReport | null>(null);

	let newName = $state('');
	let newTarget = $state(7);
	let creating = $state(false);
	let createError = $state<string | null>(null);

	function isoDate(d: Date): string {
		return d.toISOString().slice(0, 10);
	}

	function dateGrid(): string[] {
		const out: string[] = [];
		const today = new Date();
		for (let i = DAYS - 1; i >= 0; i--) {
			const d = new Date(today);
			d.setDate(today.getDate() - i);
			out.push(isoDate(d));
		}
		return out;
	}

	const GRID = $derived(dateGrid());

	async function load() {
		try {
			const [definitions, adh, report] = await Promise.all([
				habitsApi.list(true),
				fns.habitsAdherence(GRID[0], GRID[GRID.length - 1]),
				reports.latest().catch(() => null)
			]);
			weeklyReport = report;
			defs = definitions;
			adherence = adh.items;

			const checkinResults = await Promise.all(
				definitions.map((d) => habitsApi.checkins(d.id, GRID[0], GRID[GRID.length - 1]))
			);
			const map: Record<number, Set<string>> = {};
			definitions.forEach((d, i) => {
				map[d.id] = new Set(
					checkinResults[i].items.filter((c: HabitCheckin) => c.completed).map((c) => c.date)
				);
			});
			checkinsByHabit = map;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(load);

	async function toggle(habitId: number, date: string) {
		const set = checkinsByHabit[habitId];
		const done = set?.has(date);
		try {
			if (done) {
				await habitsApi.uncheck(habitId, date);
			} else {
				await habitsApi.checkin(habitId, { date, completed: true });
			}
			await load();
		} catch (e) {
			toast.error('toggle failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

	async function createHabit(e: Event) {
		e.preventDefault();
		if (!newName.trim()) return;
		creating = true;
		createError = null;
		try {
			await habitsApi.create({ name: newName.trim(), target_per_week: newTarget });
			newName = '';
			newTarget = 7;
			await load();
		} catch (err) {
			createError = err instanceof Error ? err.message : String(err);
		} finally {
			creating = false;
		}
	}

	function getAdherence(id: number): HabitAdherence | undefined {
		return adherence.find((a) => a.habit_id === id);
	}

	function dayLetter(iso: string): string {
		const d = new Date(iso);
		return ['S', 'M', 'T', 'W', 'T', 'F', 'S'][d.getDay()];
	}
</script>

<svelte:head>
	<title>Lattice · Habits</title>
</svelte:head>

<header class="page-header">
	<div class="title">
		<h1>Habits</h1>
		<span class="sub">{defs.length} active · last {DAYS} days</span>
	</div>
</header>

{#if error}
	<div class="err">load failed: {error}</div>
{/if}

<div class="layout">
	<div class="main-col">
		{#if defs.length === 0}
			<Card>
				<div class="empty">No active habits — add one →</div>
			</Card>
		{:else}
			{#each defs as h (h.id)}
				{@const a = getAdherence(h.id)}
				<Card>
					<div class="habit-head">
						<div class="habit-title">
							<h3>{h.name}</h3>
							<span class="sub">target {h.target_per_week}/wk</span>
						</div>
						{#if a}
							<div class="streaks">
								<div class="streak-stat">
									<span class="label">Streak</span>
									<span class="val">{a.current_streak_days}d</span>
								</div>
								<div class="streak-stat">
									<span class="label">Longest</span>
									<span class="val">{a.longest_streak_days}d</span>
								</div>
								<div class="streak-stat">
									<span class="label">Week</span>
									<span class="val">{a.week_completion_pct}%</span>
								</div>
							</div>
						{/if}
					</div>

					<div class="day-grid">
						{#each GRID as d (d)}
							{@const done = checkinsByHabit[h.id]?.has(d) ?? false}
							{@const dt = new Date(d)}
							<div class="day">
								<span class="dow">{dayLetter(d)}</span>
								<button
									class="cell"
									class:done
									onclick={() => toggle(h.id, d)}
									title={d}
									aria-label="{h.name} on {d}"
								>
									<span class="dayno">{dt.getDate()}</span>
								</button>
							</div>
						{/each}
					</div>
				</Card>
			{/each}
		{/if}
	</div>

	<aside class="form-col">
		{#if weeklyReport && (weeklyReport.stats.correlations.length > 0 || weeklyReport.stats.mean_shifts.length > 0)}
			<Card eyebrow="Weekly signals">
				{#if weeklyReport.stats.correlations.length > 0}
					<div class="corr-section">
						<h4 class="corr-heading">Correlations</h4>
						{#each weeklyReport.stats.correlations as c (c.label)}
							<div class="corr-row">
								<span class="corr-label">{c.label.replace(/ × /g, ' × ')}</span>
								<div class="corr-bar-wrap">
									<div
										class="corr-bar"
										class:positive={c.direction === 'positive'}
										class:negative={c.direction === 'negative'}
										style="width: {Math.abs(c.r) * 100}%"
									></div>
								</div>
								<span class="corr-r" class:pos={c.direction === 'positive'} class:neg={c.direction === 'negative'}>
									{c.direction === 'positive' ? '+' : ''}{c.r.toFixed(2)}
								</span>
								<span class="corr-n">n={c.n}</span>
							</div>
						{/each}
					</div>
				{/if}
				{#if weeklyReport.stats.mean_shifts.length > 0}
					<div class="corr-section" class:has-top={weeklyReport.stats.correlations.length > 0}>
						<h4 class="corr-heading">Mean shifts this week</h4>
						{#each weeklyReport.stats.mean_shifts as s (s.metric)}
							<div class="shift-row">
								<span class="shift-metric">{s.metric.replace(/_/g, ' ')}</span>
								<span class="shift-dir" class:up={s.direction === 'up'} class:dn={s.direction === 'down'}>
									{s.direction === 'up' ? '↑' : '↓'} {Math.abs(s.delta_sd).toFixed(1)}σ
								</span>
								<span class="shift-vals">{s.this_week_mean.toFixed(1)} vs {s.trailing_mean.toFixed(1)}</span>
							</div>
						{/each}
					</div>
				{/if}
				<p class="corr-week">week {weeklyReport.stats.iso_week}</p>
			</Card>
		{/if}

		<Card eyebrow="New habit">
			<form onsubmit={createHabit} class="form">
				<label class="field">
					<span class="label">Name</span>
					<input
						class="raw-input"
						type="text"
						bind:value={newName}
						placeholder="No coffee after 14:00"
						disabled={creating}
					/>
				</label>
				<label class="field">
					<span class="label">Target per week (1–7)</span>
					<input
						class="raw-input"
						type="number"
						min="1"
						max="7"
						bind:value={newTarget}
						disabled={creating}
					/>
				</label>
				{#if createError}
					<div class="err">{createError}</div>
				{/if}
				<Button type="submit" variant="primary" disabled={creating || !newName.trim()}>
					{creating ? 'creating…' : 'Add habit'}
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
	.habit-head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 20px;
	}
	.habit-title h3 {
		font-size: 16px;
		margin: 0 0 4px;
		font-weight: 600;
		letter-spacing: -0.005em;
	}
	.streaks {
		display: flex;
		gap: 18px;
	}
	.streak-stat {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 2px;
	}
	.streak-stat .label {
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.12em;
		color: var(--color-fg-dim);
		font-weight: 500;
	}
	.streak-stat .val {
		font-family: var(--font-mono);
		font-size: 14px;
		font-variant-numeric: tabular-nums;
		color: var(--color-fg);
		font-weight: 500;
	}
	.day-grid {
		display: grid;
		grid-template-columns: repeat(14, 1fr);
		gap: 6px;
	}
	.day {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
	}
	.dow {
		font-size: 9.5px;
		color: var(--color-fg-dim);
		font-family: var(--font-mono);
		letter-spacing: 0.1em;
		font-weight: 500;
	}
	.cell {
		width: 100%;
		aspect-ratio: 1;
		border: 1px solid var(--color-border);
		background: var(--color-bg-2);
		border-radius: var(--r-sm);
		cursor: pointer;
		display: grid;
		place-items: center;
		transition: all 120ms;
	}
	.cell:hover {
		border-color: var(--color-border-strong);
		background: var(--color-bg-3);
	}
	.cell.done {
		background: var(--color-accent);
		border-color: var(--color-accent);
	}
	.cell.done .dayno {
		color: #062927;
		font-weight: 600;
	}
	.dayno {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--color-fg-mute);
		font-variant-numeric: tabular-nums;
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
		height: 32px;
		padding: 0 10px;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		background: var(--color-bg-2);
		color: var(--color-fg);
		font-size: 12.5px;
		outline: none;
		transition: border-color 120ms, background 120ms;
	}
	.raw-input:focus {
		border-color: var(--color-accent);
		background: var(--color-bg-1);
	}
	.corr-section { display: flex; flex-direction: column; gap: 8px; }
	.corr-section.has-top { margin-top: 14px; border-top: 1px solid var(--color-border-2); padding-top: 14px; }
	.corr-heading {
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.12em;
		color: var(--color-fg-dim);
		font-weight: 500;
		margin: 0 0 4px;
	}
	.corr-row {
		display: grid;
		grid-template-columns: 1fr 60px 36px 30px;
		align-items: center;
		gap: 6px;
		font-size: 11px;
	}
	.corr-label {
		color: var(--color-fg-mute);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.corr-bar-wrap {
		height: 4px;
		background: var(--color-bg-3);
		border-radius: 2px;
		overflow: hidden;
	}
	.corr-bar {
		height: 100%;
		border-radius: 2px;
		transition: width 400ms;
	}
	.corr-bar.positive { background: #46c88c; }
	.corr-bar.negative { background: var(--color-bad); }
	.corr-r {
		font-family: var(--font-mono);
		font-size: 11px;
		font-variant-numeric: tabular-nums;
		text-align: right;
	}
	.corr-r.pos { color: #46c88c; }
	.corr-r.neg { color: var(--color-bad); }
	.corr-n { font-family: var(--font-mono); font-size: 10px; color: var(--color-fg-dim); }
	.shift-row {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 11px;
	}
	.shift-metric { flex: 1; color: var(--color-fg-mute); }
	.shift-dir { font-weight: 600; font-family: var(--font-mono); font-size: 12px; min-width: 44px; }
	.shift-dir.up { color: #46c88c; }
	.shift-dir.dn { color: var(--color-bad); }
	.shift-vals { font-family: var(--font-mono); font-size: 10px; color: var(--color-fg-dim); }
	.corr-week { font-size: 10px; color: var(--color-fg-faint); margin: 10px 0 0; font-family: var(--font-mono); }
</style>
