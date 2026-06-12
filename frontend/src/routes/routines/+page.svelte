<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import { routinesApi } from '$lib/api/client';
	import { toast } from '$lib/toast.svelte';
	import type {
		Routine,
		RoutineInput,
		RoutineType,
		Chattiness,
		RoutineRun
	} from '$lib/api/types';

	const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

	let items = $state<Routine[]>([]);
	let runs = $state<RoutineRun[]>([]);
	let error = $state<string | null>(null);

	// form state
	let editingId = $state<number | null>(null);
	let name = $state('');
	let type = $state<RoutineType>('ai_review');
	let time = $state('07:30');
	let days = $state<boolean[]>([true, true, true, true, true, true, true]);
	let chattiness = $state<Chattiness>('always');
	let instruction = $state('');
	let reminderText = $state('');
	let enabled = $state(true);
	let saving = $state(false);
	let formError = $state<string | null>(null);

	async function load() {
		try {
			const res = await routinesApi.list();
			items = res.items;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
		try {
			const r = await routinesApi.runs(15);
			runs = r.items;
		} catch {
			// run history is non-critical; ignore failures
		}
	}

	onMount(load);

	function routineName(id: number): string {
		return items.find((r) => r.id === id)?.name ?? `#${id}`;
	}

	function fmtFired(iso: string): string {
		return iso.slice(0, 16).replace('T', ' ');
	}

	function runStatus(run: RoutineRun): { label: string; cls: string } {
		if (run.suppressed) return { label: 'nothing notable', cls: 'quiet' };
		if (run.sent) return { label: 'sent', cls: 'ok' };
		return { label: 'not sent', cls: 'off' };
	}

	function maskFromDays(d: boolean[]): number {
		return d.reduce((acc, on, i) => (on ? acc | (1 << i) : acc), 0);
	}

	function daysFromMask(mask: number): boolean[] {
		return Array.from({ length: 7 }, (_, i) => Boolean(mask & (1 << i)));
	}

	function fmtTime(r: Routine): string {
		return `${String(r.hour).padStart(2, '0')}:${String(r.minute).padStart(2, '0')}`;
	}

	function fmtDays(mask: number): string {
		if (mask === 127) return 'every day';
		if (mask === 0b0011111) return 'Mon–Fri';
		if (mask === 0b1100000) return 'weekends';
		return daysFromMask(mask)
			.map((on, i) => (on ? WEEKDAYS[i] : null))
			.filter(Boolean)
			.join(' ');
	}

	function resetForm() {
		editingId = null;
		name = '';
		type = 'ai_review';
		time = '07:30';
		days = [true, true, true, true, true, true, true];
		chattiness = 'always';
		instruction = '';
		reminderText = '';
		enabled = true;
		formError = null;
	}

	function startEdit(r: Routine) {
		editingId = r.id;
		name = r.name;
		type = r.type;
		time = fmtTime(r);
		days = daysFromMask(r.weekday_mask);
		chattiness = r.chattiness;
		instruction = r.instruction ?? '';
		reminderText = r.reminder_text ?? '';
		enabled = r.enabled;
		formError = null;
		window.scrollTo({ top: 0, behavior: 'smooth' });
	}

	function buildPayload(): RoutineInput | null {
		const [hh, mm] = time.split(':').map((x) => parseInt(x, 10));
		if (Number.isNaN(hh) || Number.isNaN(mm)) {
			formError = 'pick a valid time';
			return null;
		}
		const mask = maskFromDays(days);
		if (mask === 0) {
			formError = 'select at least one day';
			return null;
		}
		if (!name.trim()) {
			formError = 'name is required';
			return null;
		}
		if (type === 'ai_review' && !instruction.trim()) {
			formError = 'an AI review needs an instruction';
			return null;
		}
		if (type === 'reminder' && !reminderText.trim()) {
			formError = 'a reminder needs its message text';
			return null;
		}
		return {
			name: name.trim(),
			type,
			hour: hh,
			minute: mm,
			weekday_mask: mask,
			chattiness,
			instruction: type === 'ai_review' ? instruction.trim() : null,
			reminder_text: type === 'reminder' ? reminderText.trim() : null,
			enabled
		};
	}

	async function submit(e: Event) {
		e.preventDefault();
		const payload = buildPayload();
		if (!payload) return;
		saving = true;
		formError = null;
		try {
			if (editingId !== null) {
				await routinesApi.patch(editingId, payload);
				toast.info('routine updated');
			} else {
				await routinesApi.create(payload);
				toast.info('routine created');
			}
			resetForm();
			await load();
		} catch (err) {
			formError = err instanceof Error ? err.message : String(err);
		} finally {
			saving = false;
		}
	}

	async function toggleEnabled(r: Routine) {
		try {
			await routinesApi.patch(r.id, { enabled: !r.enabled });
			await load();
		} catch (e) {
			toast.error('update failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

	async function runNow(r: Routine) {
		toast.info(`running "${r.name}"…`);
		try {
			await routinesApi.run(r.id);
			toast.info('ran — check Discord');
			await load();
		} catch (e) {
			toast.error('run failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

	async function remove(r: Routine) {
		if (!confirm(`delete routine "${r.name}"?`)) return;
		try {
			await routinesApi.remove(r.id);
			if (editingId === r.id) resetForm();
			await load();
			toast.info('deleted');
		} catch (e) {
			toast.error('delete failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}
</script>

<svelte:head>
	<title>Lattice · Routines</title>
</svelte:head>

<header class="page-header">
	<div class="title">
		<h1>Routines</h1>
		<span class="sub">scheduled AI check-ins &amp; reminders — sent to you on Discord</span>
	</div>
</header>

{#if error}
	<div class="err">load failed: {error}</div>
{/if}

<div class="layout">
	<div class="main-col">
		{#if items.length === 0}
			<Card>
				<div class="empty">
					No routines yet. Create one on the right — an AI review (I analyse your data and
					message you) or a plain reminder.
				</div>
			</Card>
		{:else}
			{#each items as r (r.id)}
				<Card>
					<div class="rt-row">
						<div class="rt-body" class:dim={!r.enabled}>
							<div class="rt-head">
								<span class="rt-time">{fmtTime(r)}</span>
								<span class="rt-name">{r.name}</span>
								<span class="badge {r.type === 'ai_review' ? 'ai' : 'rem'}">
									{r.type === 'ai_review' ? 'AI review' : 'reminder'}
								</span>
								{#if r.type === 'ai_review' && r.chattiness === 'only_notable'}
									<span class="badge quiet">only notable</span>
								{/if}
								{#if !r.enabled}<span class="badge off">paused</span>{/if}
							</div>
							<p class="rt-detail">
								{r.type === 'ai_review' ? r.instruction : r.reminder_text}
							</p>
							<span class="sub">
								{fmtDays(r.weekday_mask)}{r.last_run_at
									? ` · last run ${r.last_run_at.slice(0, 16).replace('T', ' ')}`
									: ''}
							</span>
						</div>
						<div class="rt-actions">
							<Button variant="ghost" size="sm" onclick={() => runNow(r)}>run now</Button>
							<Button variant="ghost" size="sm" onclick={() => toggleEnabled(r)}>
								{r.enabled ? 'pause' : 'enable'}
							</Button>
							<Button variant="ghost" size="sm" onclick={() => startEdit(r)}>edit</Button>
							<Button variant="ghost" size="sm" onclick={() => remove(r)}>delete</Button>
						</div>
					</div>
				</Card>
			{/each}
		{/if}

		{#if runs.length > 0}
			<Card eyebrow="Recent runs">
				<ul class="runs">
					{#each runs as run (run.id)}
						{@const st = runStatus(run)}
						<li class="run">
							<div class="run-head">
								<span class="run-time">{fmtFired(run.fired_at)}</span>
								<span class="run-name">{routineName(run.routine_id)}</span>
								<span class="badge {st.cls}">{st.label}</span>
							</div>
							{#if run.reply_excerpt && !run.suppressed}
								<p class="run-excerpt">{run.reply_excerpt}</p>
							{/if}
						</li>
					{/each}
				</ul>
			</Card>
		{/if}
	</div>

	<aside class="form-col">
		<Card eyebrow={editingId !== null ? 'Edit routine' : 'New routine'}>
			<form onsubmit={submit} class="form">
				<label class="field">
					<span class="label">Name</span>
					<input class="raw-input" bind:value={name} placeholder="Morning brief" disabled={saving} />
				</label>

				<div class="field">
					<span class="label">Type</span>
					<div class="seg">
						<button
							type="button"
							class:active={type === 'ai_review'}
							onclick={() => (type = 'ai_review')}
							disabled={saving}>AI review</button
						>
						<button
							type="button"
							class:active={type === 'reminder'}
							onclick={() => (type = 'reminder')}
							disabled={saving}>Reminder</button
						>
					</div>
				</div>

				<label class="field">
					<span class="label">Time</span>
					<input class="raw-input" type="time" bind:value={time} disabled={saving} />
				</label>

				<div class="field">
					<span class="label">Days</span>
					<div class="days">
						{#each WEEKDAYS as d, i (d)}
							<button
								type="button"
								class="day"
								class:active={days[i]}
								onclick={() => (days[i] = !days[i])}
								disabled={saving}>{d[0]}</button
							>
						{/each}
					</div>
				</div>

				{#if type === 'ai_review'}
					<label class="field">
						<span class="label">Instruction</span>
						<textarea
							class="raw-input"
							rows="4"
							bind:value={instruction}
							placeholder="Review my recovery and recent training; flag anything off."
							disabled={saving}
						></textarea>
					</label>
					<div class="field">
						<span class="label">When to message</span>
						<div class="seg">
							<button
								type="button"
								class:active={chattiness === 'always'}
								onclick={() => (chattiness = 'always')}
								disabled={saving}>Always</button
							>
							<button
								type="button"
								class:active={chattiness === 'only_notable'}
								onclick={() => (chattiness = 'only_notable')}
								disabled={saving}>Only if notable</button
							>
						</div>
					</div>
				{:else}
					<label class="field">
						<span class="label">Reminder text</span>
						<textarea
							class="raw-input"
							rows="3"
							bind:value={reminderText}
							placeholder="Stretch + 10 min walk."
							disabled={saving}
						></textarea>
					</label>
				{/if}

				<label class="check">
					<input type="checkbox" bind:checked={enabled} disabled={saving} />
					<span>Enabled</span>
				</label>

				{#if formError}
					<div class="err">{formError}</div>
				{/if}

				<div class="form-actions">
					<Button type="submit" variant="primary" disabled={saving}>
						{saving ? 'saving…' : editingId !== null ? 'Save changes' : 'Create routine'}
					</Button>
					{#if editingId !== null}
						<Button variant="ghost" onclick={resetForm} disabled={saving}>Cancel</Button>
					{/if}
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
	.rt-time {
		font-family: var(--font-mono, monospace);
		font-size: 14px;
		font-weight: 600;
		color: var(--color-accent);
	}
	.rt-name {
		font-size: 14px;
		font-weight: 600;
		color: var(--color-fg);
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
	.badge.ai {
		color: var(--color-accent);
		border-color: var(--color-accent);
	}
	.badge.quiet,
	.badge.off {
		color: var(--color-fg-mute);
	}
	.rt-actions {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
		justify-content: flex-end;
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
		resize: vertical;
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
		font-size: 12px;
		font-family: inherit;
		cursor: pointer;
		transition: all 120ms;
	}
	.seg button.active {
		border-color: var(--color-accent);
		color: var(--color-fg);
		background: var(--color-bg-1);
	}
	.days {
		display: flex;
		gap: 5px;
	}
	.day {
		width: 32px;
		height: 32px;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		background: var(--color-bg-2);
		color: var(--color-fg-mute);
		font-size: 12px;
		cursor: pointer;
		transition: all 120ms;
	}
	.day.active {
		border-color: var(--color-accent);
		color: var(--color-fg);
		background: var(--color-bg-1);
	}
	.check {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12.5px;
		color: var(--color-fg-dim);
	}
	.form-actions {
		display: flex;
		gap: 8px;
	}
	.runs {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.run {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding-bottom: 10px;
		border-bottom: 1px solid var(--color-border);
	}
	.run:last-child {
		border-bottom: none;
		padding-bottom: 0;
	}
	.run-head {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.run-time {
		font-family: var(--font-mono, monospace);
		font-size: 12px;
		color: var(--color-fg-mute);
	}
	.run-name {
		font-size: 13px;
		font-weight: 600;
		color: var(--color-fg);
	}
	.run-excerpt {
		margin: 0;
		font-size: 12px;
		color: var(--color-fg-dim);
		line-height: 1.4;
	}
	.badge.ok {
		color: var(--color-accent);
		border-color: var(--color-accent);
	}
</style>
