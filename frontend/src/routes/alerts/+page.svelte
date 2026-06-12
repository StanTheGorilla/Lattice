<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import { alertsApi } from '$lib/api/client';
	import { toast } from '$lib/toast.svelte';
	import type { AlertRuleOut, AlertEventOut } from '$lib/api/types';

	// Curated metric suggestions (exact names from the metrics table).
	const METRICS: { value: string; label: string }[] = [
		{ value: 'hrv_overnight_avg', label: 'HRV (overnight avg)' },
		{ value: 'resting_hr', label: 'Resting HR' },
		{ value: 'body_battery_min', label: 'Body battery (daily min)' },
		{ value: 'body_battery_end', label: 'Body battery (end of day)' },
		{ value: 'stress_avg', label: 'Stress (daily avg)' },
		{ value: 'sleep_score', label: 'Sleep score' },
		{ value: 'sleep_duration_min', label: 'Sleep duration (min)' },
		{ value: 'readiness_score', label: 'Readiness score' },
		{ value: 'training_load_acute', label: 'Acute training load' },
		{ value: 'vo2_max', label: 'VO₂ max' },
		{ value: 'steps', label: 'Steps' }
	];

	const OPS: { value: 'lt' | 'lte' | 'gt' | 'gte'; sym: string; label: string }[] = [
		{ value: 'lt', sym: '<', label: 'below' },
		{ value: 'lte', sym: '≤', label: 'at or below' },
		{ value: 'gt', sym: '>', label: 'above' },
		{ value: 'gte', sym: '≥', label: 'at or above' }
	];

	let rules = $state<AlertRuleOut[]>([]);
	let events = $state<AlertEventOut[]>([]);
	let error = $state<string | null>(null);

	// form state
	let metricName = $state('hrv_overnight_avg');
	let operator = $state<'lt' | 'lte' | 'gt' | 'gte'>('lt');
	let threshold = $state('');
	let label = $state('');
	let cooldownHours = $state('4');
	let saving = $state(false);
	let formError = $state<string | null>(null);

	function metricLabel(name: string): string {
		return METRICS.find((m) => m.value === name)?.label ?? name;
	}
	function opSym(op: string): string {
		return OPS.find((o) => o.value === op)?.sym ?? op;
	}

	async function load() {
		try {
			[rules, events] = await Promise.all([
				alertsApi.listRules(),
				alertsApi.listEvents(20)
			]);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(load);

	function ruleLabelFor(id: number): string {
		return rules.find((r) => r.id === id)?.label ?? `rule ${id}`;
	}

	async function submit(e: Event) {
		e.preventDefault();
		formError = null;
		const t = parseFloat(threshold);
		if (Number.isNaN(t)) {
			formError = 'enter a numeric threshold';
			return;
		}
		if (!metricName.trim()) {
			formError = 'pick a metric';
			return;
		}
		const cd = parseInt(cooldownHours, 10);
		if (Number.isNaN(cd) || cd < 1) {
			formError = 'cooldown must be a positive number of hours';
			return;
		}
		const finalLabel = label.trim() || `${metricLabel(metricName)} ${opSym(operator)} ${t}`;
		saving = true;
		try {
			await alertsApi.createRule({
				metric_name: metricName.trim(),
				operator,
				threshold: t,
				label: finalLabel,
				cooldown_hours: cd
			});
			toast.info('alert created');
			threshold = '';
			label = '';
			await load();
		} catch (err) {
			formError = err instanceof Error ? err.message : String(err);
		} finally {
			saving = false;
		}
	}

	let checking = $state(false);
	async function checkNow() {
		checking = true;
		try {
			const res = await alertsApi.checkNow();
			toast.info(res.fired > 0 ? `${res.fired} alert(s) fired — check Discord` : 'checked — nothing crossed');
			await load();
		} catch (e) {
			toast.error('check failed: ' + (e instanceof Error ? e.message : String(e)));
		} finally {
			checking = false;
		}
	}

	async function toggleActive(r: AlertRuleOut) {
		try {
			await alertsApi.patchRule(r.id, { active: !r.active });
			await load();
		} catch (e) {
			toast.error('update failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

	async function remove(r: AlertRuleOut) {
		if (!confirm(`delete alert "${r.label}"?`)) return;
		try {
			await alertsApi.deleteRule(r.id);
			await load();
			toast.info('deleted');
		} catch (e) {
			toast.error('delete failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}
</script>

<svelte:head>
	<title>Lattice · Alerts</title>
</svelte:head>

<header class="page-header">
	<div class="title">
		<h1>Alerts</h1>
		<span class="sub">threshold watches — checked hourly, DM'd to you on Discord when crossed</span>
	</div>
	<Button variant="ghost" size="sm" onclick={checkNow} disabled={checking}>
		{checking ? 'checking…' : 'check now'}
	</Button>
</header>

{#if error}
	<div class="err">load failed: {error}</div>
{/if}

<div class="layout">
	<div class="main-col">
		{#if rules.length === 0}
			<Card>
				<div class="empty">
					No alerts yet. Create one on the right, e.g. "HRV below 40" — I'll DM you when the
					latest reading crosses it.
				</div>
			</Card>
		{:else}
			{#each rules as r (r.id)}
				<Card>
					<div class="rt-row">
						<div class="rt-body" class:dim={!r.active}>
							<div class="rt-head">
								<span class="rt-metric">{metricLabel(r.metric_name)}</span>
								<span class="rt-cond">{opSym(r.operator)} {r.threshold}</span>
								{#if !r.active}<span class="badge off">paused</span>{/if}
							</div>
							<p class="rt-detail">{r.label}</p>
							<span class="sub">cooldown {r.cooldown_hours}h</span>
						</div>
						<div class="rt-actions">
							<Button variant="ghost" size="sm" onclick={() => toggleActive(r)}>
								{r.active ? 'pause' : 'enable'}
							</Button>
							<Button variant="ghost" size="sm" onclick={() => remove(r)}>delete</Button>
						</div>
					</div>
				</Card>
			{/each}
		{/if}

		{#if events.length > 0}
			<Card eyebrow="Recent fires">
				<ul class="events">
					{#each events as ev (ev.id)}
						<li>
							<span class="ev-time">{ev.fired_at.slice(0, 16).replace('T', ' ')}</span>
							<span class="ev-label">{ruleLabelFor(ev.rule_id)}</span>
							<span class="ev-val">{ev.value.toFixed(1)}</span>
						</li>
					{/each}
				</ul>
			</Card>
		{/if}
	</div>

	<aside class="form-col">
		<Card eyebrow="New alert">
			<form onsubmit={submit} class="form">
				<label class="field">
					<span class="label">Metric</span>
					<input class="raw-input" list="metric-options" bind:value={metricName} disabled={saving} />
					<datalist id="metric-options">
						{#each METRICS as m (m.value)}
							<option value={m.value}>{m.label}</option>
						{/each}
					</datalist>
				</label>

				<div class="field">
					<span class="label">Condition</span>
					<div class="seg">
						{#each OPS as o (o.value)}
							<button
								type="button"
								class:active={operator === o.value}
								onclick={() => (operator = o.value)}
								disabled={saving}
								title={o.label}>{o.sym}</button
							>
						{/each}
					</div>
				</div>

				<label class="field">
					<span class="label">Threshold</span>
					<input
						class="raw-input"
						type="number"
						step="any"
						bind:value={threshold}
						placeholder="40"
						disabled={saving}
					/>
				</label>

				<label class="field">
					<span class="label">Label <span class="opt">(optional)</span></span>
					<input
						class="raw-input"
						bind:value={label}
						placeholder="auto-generated if blank"
						disabled={saving}
					/>
				</label>

				<label class="field">
					<span class="label">Cooldown (hours)</span>
					<input class="raw-input" type="number" min="1" bind:value={cooldownHours} disabled={saving} />
				</label>

				{#if formError}
					<div class="err">{formError}</div>
				{/if}

				<div class="form-actions">
					<Button type="submit" variant="primary" disabled={saving}>
						{saving ? 'saving…' : 'Create alert'}
					</Button>
				</div>
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
	.opt {
		color: var(--color-fg-faint);
		font-weight: 400;
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
		grid-template-columns: minmax(0, 1fr) 340px;
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
	.rt-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
	}
	.rt-body {
		display: flex;
		flex-direction: column;
		gap: 6px;
		min-width: 0;
	}
	.rt-body.dim {
		opacity: 0.5;
	}
	.rt-head {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.rt-metric {
		font-size: 14px;
		font-weight: 600;
		color: var(--color-fg);
	}
	.rt-cond {
		font-family: var(--font-mono, monospace);
		font-size: 13px;
		font-weight: 600;
		color: var(--color-accent);
	}
	.rt-detail {
		margin: 0;
		font-size: 13px;
		color: var(--color-fg-dim);
		line-height: 1.4;
	}
	.badge {
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 2px 6px;
		border-radius: var(--r-sm);
		border: 1px solid var(--color-border);
		color: var(--color-fg-mute);
	}
	.rt-actions {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
		justify-content: flex-end;
	}
	.events {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.events li {
		display: flex;
		align-items: baseline;
		gap: 10px;
		font-size: 12px;
	}
	.ev-time {
		font-family: var(--font-mono, monospace);
		color: var(--color-fg-dim);
		font-size: 11px;
	}
	.ev-label {
		flex: 1;
		color: var(--color-fg-mute);
		min-width: 0;
	}
	.ev-val {
		font-family: var(--font-mono, monospace);
		color: var(--color-fg);
		font-weight: 600;
	}
	.form {
		display: flex;
		flex-direction: column;
		gap: 14px;
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
		transition: border-color 120ms, background 120ms;
	}
	.raw-input:focus {
		border-color: var(--color-accent);
		background: var(--color-bg-1);
	}
	.seg {
		display: flex;
		gap: 6px;
	}
	.seg button {
		flex: 1;
		padding: 7px 8px;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		background: var(--color-bg-2);
		color: var(--color-fg-mute);
		font-size: 14px;
		font-family: var(--font-mono, monospace);
		cursor: pointer;
		transition: all 120ms;
	}
	.seg button.active {
		border-color: var(--color-accent);
		color: var(--color-fg);
		background: var(--color-bg-1);
	}
	.form-actions {
		display: flex;
		gap: 8px;
	}
</style>
