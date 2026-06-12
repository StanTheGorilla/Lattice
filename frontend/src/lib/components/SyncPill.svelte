<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { scale } from 'svelte/transition';
	import { sync, calendar, ApiError, type GarminStreamEvent } from '$lib/api/client';
	import { toast } from '$lib/toast.svelte';

	let garminAt = $state<string | null>(null);
	let calendarAt = $state<string | null>(null);
	let errored = $state(false);
	let timer: ReturnType<typeof setInterval> | null = null;

	let open = $state(false);
	let pillEl: HTMLButtonElement | null = $state(null);
	let popoverEl: HTMLDivElement | null = $state(null);

	let days = $state(1);
	let customDays = $state(7);
	let syncing = $state(false);
	let progressDone = $state(0);
	let progressTotal = $state(0);
	let progressLastDay = $state<string | null>(null);
	let progressMetrics = $state(0);
	let progressWorkouts = $state(0);
	let progressSamples = $state(0);
	let progressErrors = $state<string[]>([]);
	let abortCtl: AbortController | null = null;

	let calendarSyncing = $state(false);

	const PRESETS: { label: string; days: number }[] = [
		{ label: '1 day', days: 1 },
		{ label: '1 wk', days: 7 },
		{ label: '1 mo', days: 31 },
		{ label: '1 yr', days: 365 }
	];

	async function load() {
		try {
			const s = await sync.status();
			garminAt = s.garmin_last_metric_at;
			calendarAt = s.calendar_last_fetched_at;
			errored = false;
		} catch {
			errored = true;
		}
	}

	function rel(iso: string | null): string {
		if (!iso) return '—';
		const t = Date.parse(iso);
		if (Number.isNaN(t)) return '—';
		const seconds = Math.max(0, Math.round((Date.now() - t) / 1000));
		if (seconds < 60) return `${seconds}s`;
		const minutes = Math.round(seconds / 60);
		if (minutes < 60) return `${minutes}m`;
		const hours = Math.round(minutes / 60);
		if (hours < 24) return `${hours}h`;
		const d = Math.round(hours / 24);
		return `${d}d`;
	}

	function togglePopover() {
		open = !open;
		if (open) {
			progressErrors = [];
		}
	}

	function close() {
		if (syncing) return;
		open = false;
	}

	function onDocClick(e: MouseEvent) {
		if (!open) return;
		const t = e.target as Node;
		if (popoverEl && popoverEl.contains(t)) return;
		if (pillEl && pillEl.contains(t)) return;
		close();
	}

	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape' && open && !syncing) close();
	}

	async function runGarminSync(n: number) {
		if (syncing) return;
		syncing = true;
		days = n;
		progressDone = 0;
		progressTotal = n;
		progressLastDay = null;
		progressMetrics = 0;
		progressWorkouts = 0;
		progressSamples = 0;
		progressErrors = [];
		abortCtl = new AbortController();
		try {
			await sync.garminStream(
				n,
				(e: GarminStreamEvent) => {
					if (e.type === 'progress') {
						progressDone = e.done;
						progressTotal = e.total;
						progressLastDay = e.day;
						progressMetrics += e.metrics_written;
						progressWorkouts += e.workouts_written;
						progressSamples += e.samples_written;
						if (e.errors.length) progressErrors = [...progressErrors, ...e.errors];
					} else if (e.type === 'done') {
						toast.info(
							`Synced ${e.total} day${e.total === 1 ? '' : 's'} — ` +
								`${e.metrics_total} metrics, ${e.workouts_total} workouts, ` +
								`${e.samples_total.toLocaleString()} samples`
						);
					} else if (e.type === 'error') {
						toast.error(`Garmin sync failed: ${e.message}`);
					}
				},
				abortCtl.signal
			);
			await load();
		} catch (err) {
			if (err instanceof DOMException && err.name === 'AbortError') {
				toast.info('Sync cancelled');
			} else if (err instanceof ApiError) {
				toast.error(`Sync failed: ${err.message}`);
			} else {
				toast.error('Sync failed');
			}
		} finally {
			syncing = false;
			abortCtl = null;
		}
	}

	function cancelSync() {
		abortCtl?.abort();
	}

	async function runCalendarSync() {
		if (calendarSyncing) return;
		calendarSyncing = true;
		try {
			const r = await calendar.sync();
			toast.info(`Calendar synced — ${r.refreshed} events`);
			await load();
		} catch (err) {
			if (err instanceof ApiError) {
				toast.error(`Calendar sync failed: ${err.message}`);
			} else {
				toast.error('Calendar sync failed');
			}
		} finally {
			calendarSyncing = false;
		}
	}

	onMount(() => {
		load();
		timer = setInterval(load, 60_000);
		document.addEventListener('click', onDocClick);
		document.addEventListener('keydown', onKey);
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
		document.removeEventListener('click', onDocClick);
		document.removeEventListener('keydown', onKey);
		abortCtl?.abort();
	});
</script>

<div class="wrap">
	<button
		type="button"
		class="pill"
		class:err={errored}
		class:open
		bind:this={pillEl}
		onclick={togglePopover}
		title="Sync activity — click to open"
	>
		<span class="lbl">G</span>
		<span class="val">{rel(garminAt)}</span>
		<span class="sep">·</span>
		<span class="lbl">C</span>
		<span class="val">{rel(calendarAt)}</span>
	</button>

	{#if open}
		<div
			class="popover"
			bind:this={popoverEl}
			role="dialog"
			aria-label="Sync controls"
			transition:scale={{ start: 0.96, duration: 160 }}
		>
			<header>
				<span class="title">SYNC</span>
				<button class="x" type="button" onclick={close} disabled={syncing}>×</button>
			</header>

			<section>
				<div class="row-label">Garmin — last metric {rel(garminAt)} ago</div>
				<div class="presets">
					{#each PRESETS as p (p.days)}
						<button
							class="preset"
							type="button"
							disabled={syncing}
							onclick={() => runGarminSync(p.days)}
						>
							{p.label}
						</button>
					{/each}
				</div>

				<div class="custom">
					<input
						type="number"
						min="1"
						max="400"
						bind:value={customDays}
						disabled={syncing}
						aria-label="Custom days"
					/>
					<span class="days-label">days</span>
					<button
						type="button"
						class="go"
						disabled={syncing || customDays < 1 || customDays > 400}
						onclick={() => runGarminSync(customDays)}
					>
						Sync
					</button>
				</div>

				{#if syncing || progressTotal > 0}
					<div class="progress">
						<div class="bar">
							<div
								class="fill"
								style="width: {progressTotal > 0
									? (progressDone / progressTotal) * 100
									: 0}%"
							></div>
						</div>
						<div class="stats">
							<span>{progressDone}/{progressTotal}</span>
							{#if progressLastDay}<span class="dim">· {progressLastDay}</span>{/if}
							<span class="dim">· {progressMetrics}m / {progressWorkouts}w / {progressSamples}s</span>
							{#if syncing}
								<button class="cancel" type="button" onclick={cancelSync}>cancel</button>
							{/if}
						</div>
						{#if progressErrors.length}
							<div class="errs">
								{progressErrors.length} error{progressErrors.length === 1 ? '' : 's'}
								<details>
									<summary class="dim">show</summary>
									<ul>
										{#each progressErrors.slice(0, 20) as e, i (i)}
											<li>{e}</li>
										{/each}
									</ul>
								</details>
							</div>
						{/if}
					</div>
				{/if}
			</section>

			<section>
				<div class="row-label">Calendar — last fetched {rel(calendarAt)} ago</div>
				<button
					type="button"
					class="go full"
					disabled={calendarSyncing}
					onclick={runCalendarSync}
				>
					{calendarSyncing ? 'Syncing…' : 'Sync calendar'}
				</button>
			</section>
		</div>
	{/if}
</div>

<style>
	.wrap {
		position: relative;
	}
	.pill {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 7px 12px;
		margin: 8px 16px;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		font-size: 11px;
		color: var(--color-fg-mute);
		letter-spacing: 0.04em;
		background: var(--color-bg-1);
		cursor: pointer;
		font-family: inherit;
		width: calc(100% - 32px);
		justify-content: flex-start;
		transition: background 120ms, border-color 120ms, color 120ms;
	}
	.pill:hover {
		border-color: var(--color-border-strong);
		background: var(--color-bg-2);
		color: var(--color-fg);
	}
	.pill.open {
		border-color: var(--color-accent);
		background: var(--color-bg-2);
		color: var(--color-fg);
	}
	.lbl {
		color: var(--color-fg-dim);
		font-weight: 500;
	}
	.val {
		color: var(--color-fg);
		font-variant-numeric: tabular-nums;
	}
	.sep {
		color: var(--color-fg-faint);
	}
	.err {
		border-color: rgba(201, 106, 106, 0.35);
		color: var(--color-bad);
	}

	.popover {
		position: absolute;
		bottom: calc(100% + 6px);
		left: 16px;
		width: 300px;
		max-width: calc(100vw - 32px);
		background: var(--color-bg-1);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--r-md);
		padding: 16px;
		z-index: 30;
		box-shadow: var(--shadow-lg);
		font-size: 12.5px;
		transform-origin: bottom left;
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 10px;
	}
	.title {
		font-family: var(--font-mono);
		font-size: 10.5px;
		letter-spacing: 0.16em;
		color: var(--color-fg-dim);
		font-weight: 600;
	}
	.x {
		background: none;
		border: 0;
		color: var(--color-fg-dim);
		cursor: pointer;
		font-size: 18px;
		line-height: 1;
		padding: 0 4px;
		transition: color 120ms;
	}
	.x:hover {
		color: var(--color-fg);
	}
	.x:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}
	section {
		margin-top: 10px;
	}
	section + section {
		border-top: 1px solid var(--color-border);
		padding-top: 12px;
		margin-top: 14px;
	}
	.row-label {
		font-size: 11px;
		color: var(--color-fg-mute);
		margin-bottom: 8px;
	}
	.presets {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 6px;
		margin-bottom: 10px;
	}
	.preset,
	.go,
	.cancel {
		font-size: 12px;
		letter-spacing: 0.02em;
		padding: 8px 10px;
		border: 1px solid var(--color-border);
		background: var(--color-bg-2);
		color: var(--color-fg);
		border-radius: var(--r-sm);
		cursor: pointer;
		transition: border-color 120ms, color 120ms, background 120ms;
		white-space: nowrap;
		text-align: center;
	}
	.preset:hover:not(:disabled),
	.go:hover:not(:disabled) {
		border-color: var(--color-accent);
		color: var(--color-accent);
		background: var(--accent-12);
	}
	.preset:disabled,
	.go:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.custom {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.custom input {
		flex: 1;
		min-width: 0;
		font-family: var(--font-mono);
		font-size: 13px;
		padding: 7px 10px;
		border: 1px solid var(--color-border);
		background: var(--color-bg-2);
		color: var(--color-fg);
		border-radius: var(--r-sm);
		font-variant-numeric: tabular-nums;
		outline: none;
		transition: border-color 120ms;
	}
	.custom input:focus {
		border-color: var(--color-accent);
	}
	.custom .days-label {
		font-size: 11.5px;
		color: var(--color-fg-mute);
	}
	.custom .go {
		padding: 8px 16px;
		font-weight: 500;
	}
	.go.full {
		width: 100%;
		text-align: center;
		padding: 10px;
		font-weight: 500;
	}
	.dim {
		color: var(--color-fg-dim);
	}
	.progress {
		margin-top: 10px;
	}
	.bar {
		height: 5px;
		background: var(--color-bg-3);
		border-radius: 999px;
		overflow: hidden;
	}
	.fill {
		height: 100%;
		background: var(--color-accent);
		transition: width 200ms ease-out;
		border-radius: 999px;
	}
	.stats {
		margin-top: 6px;
		display: flex;
		gap: 6px;
		align-items: center;
		font-size: 11px;
		color: var(--color-fg);
		font-variant-numeric: tabular-nums;
		flex-wrap: wrap;
	}
	.cancel {
		margin-left: auto;
		font-size: 10px;
		padding: 3px 6px;
	}
	.cancel:hover {
		border-color: var(--color-bad);
		color: var(--color-bad);
		background: var(--bad-12);
	}
	.errs {
		margin-top: 8px;
		font-size: 10.5px;
		color: var(--color-bad);
	}
	.errs ul {
		margin: 4px 0 0;
		padding-left: 16px;
		color: var(--color-fg-dim);
	}
	.errs summary {
		cursor: pointer;
	}
</style>
