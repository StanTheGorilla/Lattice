<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Pill from '$lib/components/ui/Pill.svelte';
	import { entries as entriesApi, nutritionApi, nutritionGoalsApi } from '$lib/api/client';
	let nutritionPending = $state(new Set<number>());
	import { toast } from '$lib/toast.svelte';
	import type { DailyNutrition, Entry, EntryMarkers, EntryType, FoodNutrition, NutritionGoals, NutritionDayPoint } from '$lib/api/types';

	const TYPES: EntryType[] = [
		'food',
		'drink',
		'mood',
		'energy',
		'focus',
		'symptom',
		'note',
		'workout_manual'
	];

	let filter = $state<EntryType | 'all'>('all');
	let items = $state<Entry[]>([]);
	let total = $state(0);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let dailyNutrition = $state<DailyNutrition | null>(null);
	let nutritionGoals = $state<NutritionGoals | null>(null);
	let nutritionHistory = $state<NutritionDayPoint[]>([]);

	let newType = $state<EntryType>('food');
	let formData = $state<Record<string, string>>({});
	let submitting = $state(false);
	let formError = $state<string | null>(null);

	// Entry markers expansion
	let expandedId = $state<number | null>(null);
	let markersCache = $state(new Map<number, EntryMarkers>());
	let markersLoading = $state(new Set<number>());

	async function toggleEntry(id: number) {
		if (expandedId === id) {
			expandedId = null;
			return;
		}
		expandedId = id;
		if (!markersCache.has(id) && !markersLoading.has(id)) {
			markersLoading = new Set([...markersLoading, id]);
			try {
				const m = await entriesApi.markers(id);
				markersCache = new Map([...markersCache, [id, m]]);
			} catch {
				// markers are additive — silent fail is fine
			} finally {
				markersLoading = new Set([...markersLoading].filter((x) => x !== id));
			}
		}
	}

	async function loadNutrition() {
		const [daily, goals, history] = await Promise.all([
			nutritionApi.daily().catch(() => null),
			nutritionGoalsApi.get().catch(() => null),
			nutritionApi.history(90).catch(() => null)
		]);
		dailyNutrition = daily;
		nutritionGoals = goals;
		nutritionHistory = history?.series ?? [];
	}

	async function load() {
		loading = true;
		try {
			const r = await entriesApi.list({ type: filter === 'all' ? undefined : filter, limit: 50 });
			items = r.items;
			total = r.total;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		load();
		loadNutrition();
	});

	function pickFilter(t: EntryType | 'all') {
		filter = t;
		load();
	}

	function fmtTime(iso: string): string {
		try {
			const d = new Date(iso);
			return d.toLocaleString([], {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return iso;
		}
	}

	function foodHasNutrition(e: Entry): boolean {
		return e.type === 'food' && !!e.data.nutrition;
	}

	function foodNutrition(e: Entry): FoodNutrition | null {
		if (!foodHasNutrition(e)) return null;
		return e.data.nutrition as FoodNutrition;
	}

	function summarize(e: Entry): string {
		const d = e.data;
		switch (e.type) {
			case 'food':
				return String(d.description ?? '—') + (d.grams ? ` · ${d.grams}g` : '') + (d.meal_type ? ` · ${d.meal_type}` : '');
			case 'drink': {
				const name = d.sub_type ? String(d.sub_type) : String(d.kind ?? '—');
				const cafStr = d.caffeine_mg ? ` · ${d.caffeine_mg}mg` : '';
				const countStr = d.count ? ` · ${d.count}x` : '';
				const volStr = d.volume_ml ? ` · ${d.volume_ml}ml` : '';
				return `${name}${cafStr}${countStr}${volStr}`;
			}
			case 'mood':
			case 'energy':
				return `${d.score ?? '—'}/5${d.note ? ` · ${d.note}` : ''}`;
			case 'focus':
				return `${d.score ?? '—'}/5${d.session_duration_min ? ` · ${d.session_duration_min}m` : ''}${d.task ? ` · ${d.task}` : ''}`;
			case 'symptom':
				return `${d.tag ?? '—'} · ${d.severity ?? '—'}/5${d.note ? ` · ${d.note}` : ''}`;
			case 'note':
				return String(d.text ?? '—');
			case 'workout_manual':
				return `${d.kind ?? '—'} · ${d.duration_min ?? '—'}m · ${d.intensity ?? '—'}`;
			default:
				return JSON.stringify(d);
		}
	}

	function buildPayload(): Record<string, unknown> {
		const d: Record<string, unknown> = {};
		for (const [k, v] of Object.entries(formData)) {
			if (v === '' || v === undefined) continue;
			if (['score', 'severity', 'count', 'volume_ml', 'duration_min', 'session_duration_min'].includes(k)) {
				const n = Number(v);
				if (!isNaN(n)) d[k] = n;
				continue;
			}
			d[k] = v;
		}
		return d;
	}

	async function submit() {
		formError = null;
		submitting = true;
		try {
			const created = await entriesApi.create({ type: newType, data: buildPayload() });
			formData = {};
			await load();
			// For food entries, nutrition is estimated in the background.
			// Mark the entry as pending, then re-fetch once estimation likely finished.
			if (newType === 'food') {
				nutritionPending = new Set([...nutritionPending, created.id]);
				setTimeout(async () => {
					await load();
					nutritionPending = new Set([...nutritionPending].filter((x) => x !== created.id));
				}, 8000);
			}
		} catch (e) {
			formError = e instanceof Error ? e.message : String(e);
		} finally {
			submitting = false;
		}
	}

	async function reEstimate(e: MouseEvent, id: number) {
		e.stopPropagation();
		nutritionPending = new Set([...nutritionPending, id]);
		try {
			await entriesApi.estimateNutrition(id);
			// Poll until nutrition appears (up to 30s)
			for (let i = 0; i < 6; i++) {
				await new Promise((r) => setTimeout(r, 5000));
				await load();
				const entry = items.find((x) => x.id === id);
				if (entry?.data.nutrition) break;
			}
		} catch {
			toast.error('estimation failed');
		} finally {
			nutritionPending = new Set([...nutritionPending].filter((x) => x !== id));
		}
	}

	async function remove(id: number) {
		if (!confirm('delete this entry?')) return;
		try {
			await entriesApi.remove(id);
			await load();
		} catch (e) {
			toast.error('delete failed: ' + (e instanceof Error ? e.message : String(e)));
		}
	}

	function setField(k: string, v: string) {
		formData = { ...formData, [k]: v };
	}

	const FIELDS: Record<EntryType, { key: string; label: string; type?: string; placeholder?: string }[]> = {
		food: [
			{ key: 'description', label: 'Description', placeholder: 'chicken salad with avocado' },
			{ key: 'grams', label: 'Grams (optional)', type: 'number', placeholder: '400' },
			{ key: 'meal_type', label: 'Meal type (optional)', placeholder: 'breakfast | lunch | dinner | snack' }
		],
		drink: [
			{ key: 'kind', label: 'Kind', placeholder: 'latte, espresso, water, beer, tea…' },
			{ key: 'count', label: 'Count (optional)', type: 'number', placeholder: '1' },
			{ key: 'volume_ml', label: 'Volume ml (optional)', type: 'number', placeholder: '250' }
		],
		mood: [
			{ key: 'score', label: 'Score (1-5)', type: 'number' },
			{ key: 'note', label: 'Note (optional)' }
		],
		energy: [
			{ key: 'score', label: 'Score (1-5)', type: 'number' },
			{ key: 'note', label: 'Note (optional)' }
		],
		focus: [
			{ key: 'score', label: 'Score (1-5)', type: 'number' },
			{ key: 'session_duration_min', label: 'Duration (min)', type: 'number' },
			{ key: 'task', label: 'Task' }
		],
		symptom: [
			{ key: 'tag', label: 'Tag', placeholder: 'headache | fatigue | gut | other' },
			{ key: 'severity', label: 'Severity (1-5)', type: 'number' },
			{ key: 'note', label: 'Note (optional)' }
		],
		note: [{ key: 'text', label: 'Text' }],
		workout_manual: [
			{ key: 'kind', label: 'Kind', placeholder: 'run, cycling, lift…' },
			{ key: 'duration_min', label: 'Duration (min)', type: 'number' },
			{ key: 'intensity', label: 'Intensity', placeholder: 'low | medium | high' },
			{ key: 'note', label: 'Note (optional)' }
		]
	};

	function changeNewType(t: EntryType) {
		newType = t;
		formData = {};
		formError = null;
	}

	// ── nutrition calendar ──
	const today = new Date();
	let calYear = $state(today.getFullYear());
	let calMonth = $state(today.getMonth()); // 0-indexed

	const historyMap = $derived(
		new Map(nutritionHistory.map((d) => [d.date, d]))
	);

	const calWeeks = $derived((() => {
		const first = new Date(calYear, calMonth, 1);
		const last = new Date(calYear, calMonth + 1, 0);
		const startOffset = (first.getDay() + 6) % 7; // Monday = 0
		const weeks: (number | null)[][] = [];
		let week: (number | null)[] = Array(startOffset).fill(null);
		for (let d = 1; d <= last.getDate(); d++) {
			week.push(d);
			if (week.length === 7) { weeks.push(week); week = []; }
		}
		if (week.length) { while (week.length < 7) week.push(null); weeks.push(week); }
		return weeks;
	})());

	const CAL_MONTHS = ['January','February','March','April','May','June',
		'July','August','September','October','November','December'];

	function prevMonth() {
		if (calMonth === 0) { calMonth = 11; calYear -= 1; }
		else calMonth -= 1;
	}
	function nextMonth() {
		if (calMonth === 11) { calMonth = 0; calYear += 1; }
		else calMonth += 1;
	}

	function dayKey(d: number) {
		return `${calYear}-${String(calMonth + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
	}

	function isToday(d: number) {
		return calYear === today.getFullYear() && calMonth === today.getMonth() && d === today.getDate();
	}

	function macroScore(data: { calories: number; protein_g: number; carbs_g: number; fat_g: number; fiber_g: number }, g: NutritionGoals) {
		let hits = 0;
		if (data.calories >= g.calorie_goal * 0.8 && data.calories <= g.calorie_goal * 1.15) hits++;
		if (data.protein_g >= g.protein_g_goal * 0.8) hits++;
		if (data.carbs_g <= g.carbs_g_goal * 1.15) hits++;
		if (data.fat_g <= g.fat_g_goal * 1.15) hits++;
		if (data.fiber_g >= g.fiber_g_goal * 0.8) hits++;
		return hits; // out of 5
	}

	// ── day detail modal ──
	let modalDate = $state<string | null>(null);
	let modalData = $state<DailyNutrition | null>(null);
	let modalLoading = $state(false);

	async function openDay(key: string) {
		modalDate = key;
		modalData = null;
		modalLoading = true;
		try {
			modalData = await nutritionApi.daily(key);
		} catch {
			modalData = null;
		} finally {
			modalLoading = false;
		}
	}

	function closeModal() { modalDate = null; modalData = null; }

	function fmtModalDate(iso: string) {
		try {
			return new Date(iso + 'T12:00:00').toLocaleDateString([], {
				weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
			});
		} catch { return iso; }
	}
</script>

<svelte:head>
	<title>Lattice · Log</title>
</svelte:head>

<header class="page-header">
	<div class="title">
		<h1>Log</h1>
		<span class="sub">{total} total entries</span>
	</div>
</header>

<div class="layout">
	<div class="main-col">
		<div class="filters">
			<button class="chip" class:active={filter === 'all'} onclick={() => pickFilter('all')}>
				All
			</button>
			{#each TYPES as t (t)}
				<button class="chip" class:active={filter === t} onclick={() => pickFilter(t)}>
					{t.replace('_', ' ')}
				</button>
			{/each}
		</div>

		{#if error}
			<div class="err">load failed: {error}</div>
		{/if}


		<Card padded={false}>
			{#if loading}
				<div class="empty">loading…</div>
			{:else if items.length === 0}
				<div class="empty">No entries</div>
			{:else}
				<table>
					<thead>
						<tr>
							<th>When</th>
							<th>Type</th>
							<th>Summary</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{#each items as e (e.id)}
							<tr
								class:has-nutrition={foodHasNutrition(e)}
								class:row-expanded={expandedId === e.id}
								onclick={() => toggleEntry(e.id)}
								style="cursor:pointer"
							>
								<td class="time">{fmtTime(e.timestamp)}</td>
								<td>
									<Pill>{e.type.replace('_', ' ')}</Pill>
								</td>
								<td class="summary">
									<div>{summarize(e)}</div>
									{#if foodHasNutrition(e)}
										{@const n = foodNutrition(e)}
										{#if n}
										<div class="macro-row">
											<span class="macro kcal">{Math.round(n.calories ?? 0)} kcal</span>
											<span class="macro">P {n.protein_g ?? 0}g</span>
											<span class="macro">C {n.carbs_g ?? 0}g</span>
											<span class="macro">F {n.fat_g ?? 0}g</span>
											{#if n.fiber_g != null}
												<span class="macro fi">fi {n.fiber_g}g</span>
											{/if}
											{#if n.sugar_g != null}
												<span class="macro su">su {n.sugar_g}g</span>
											{/if}
											{#if n.confidence && n.confidence !== 'high'}
												<span class="macro conf">{n.confidence}</span>
											{/if}
										</div>
										{/if}
									{:else if e.type === 'food'}
										{#if nutritionPending.has(e.id)}
											<div class="macro-row"><span class="macro estimating">estimating…</span></div>
										{:else}
											<div class="macro-row">
												<button class="estimate-btn" onclick={(ev) => reEstimate(ev, e.id)}>estimate nutrition</button>
											</div>
										{/if}
									{/if}
								</td>
								<td class="actions">
									<button
										class="del"
										onclick={(ev) => { ev.stopPropagation(); remove(e.id); }}
										aria-label="delete entry"
									>×</button>
								</td>
							</tr>
							{#if expandedId === e.id}
								<tr class="markers-row">
									<td colspan="4">
										{#if markersLoading.has(e.id)}
											<span class="m-loading">loading…</span>
										{:else if markersCache.has(e.id)}
											{@const m = markersCache.get(e.id)!}
											<div class="marker-chips">
												{#each m.markers as chip (chip.label)}
													<span class="mchip {chip.sentiment}">
														<span class="mchip-label">{chip.label}</span>
														<span class="mchip-sep">·</span>
														<span class="mchip-value">{chip.value}</span>
													</span>
												{/each}
											</div>
										{:else}
											<span class="m-loading">no markers available</span>
										{/if}
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			{/if}
		</Card>
	</div>

	<aside class="form-col">
		<Card eyebrow="New entry">
			<div class="type-row">
				{#each TYPES as t (t)}
					<button class="chip small" class:active={newType === t} onclick={() => changeNewType(t)}>
						{t.replace('_', ' ')}
					</button>
				{/each}
			</div>

			<div class="fields">
				{#each FIELDS[newType] as f (f.key)}
					<label class="field">
						<span class="label">{f.label}</span>
						<input
							class="raw-input"
							type={f.type ?? 'text'}
							placeholder={f.placeholder ?? ''}
							value={formData[f.key] ?? ''}
							oninput={(e) => setField(f.key, (e.target as HTMLInputElement).value)}
						/>
					</label>
				{/each}
			</div>

			{#if formError}
				<div class="err">{formError}</div>
			{/if}

			<Button variant="primary" onclick={submit} disabled={submitting}>
				{submitting ? 'saving…' : 'Save entry'}
			</Button>
		</Card>

		{#if nutritionGoals}
			{@const g = nutritionGoals}
			{@const t = dailyNutrition?.totals ?? { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0, sugar_g: 0 }}
			{@const macros = [
				{ key: 'calories', label: 'Calories', val: t.calories, goal: g.calorie_goal, unit: 'kcal', accent: '#e07b54' },
				{ key: 'protein',  label: 'Protein',  val: t.protein_g, goal: g.protein_g_goal, unit: 'g', accent: '#5b9cf6' },
				{ key: 'carbs',    label: 'Carbs',    val: t.carbs_g,   goal: g.carbs_g_goal,   unit: 'g', accent: '#f0b429' },
				{ key: 'fat',      label: 'Fat',      val: t.fat_g,     goal: g.fat_g_goal,     unit: 'g', accent: '#68d391' },
				{ key: 'fiber',    label: 'Fiber',    val: t.fiber_g,   goal: g.fiber_g_goal,   unit: 'g', accent: '#b794f4' },
				{ key: 'sugar',    label: 'Sugar',    val: t.sugar_g,   goal: g.sugar_g_goal,   unit: 'g', accent: '#fc8181' }
			]}
			<div class="macro-goals">
				<div class="mg-header">
					<span class="mg-title">Today's macros</span>
					{#if g.source !== 'set'}
						<span class="mg-source">{g.source}</span>
					{/if}
				</div>
				<div class="mg-bars">
					{#each macros as m (m.key)}
						{@const pct = Math.min(m.goal > 0 ? (m.val / m.goal) * 100 : 0, 100)}
						{@const over = m.val > m.goal && m.goal > 0}
						<div class="mg-row">
							<span class="mg-label">{m.label}</span>
							<div class="mg-track">
								<div
									class="mg-fill"
									style="width: {pct}%; background: {over ? '#f87171' : m.accent}"
								></div>
							</div>
							<span class="mg-nums" class:over>
								{Math.round(m.val)}<span class="mg-slash">/</span>{Math.round(m.goal)}{m.unit}
							</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	</aside>
</div>

{#if nutritionGoals}
	{@const g = nutritionGoals}
	<section class="cal-section">
		<div class="cal-header">
			<div class="cal-title-row">
				<h2 class="cal-title">Nutrition calendar</h2>
				{#if g.source !== 'set'}
					<span class="cal-goals-hint">goals: {g.source} · ask the AI to customise them</span>
				{/if}
			</div>
			<div class="cal-nav">
				<button class="cal-nav-btn" onclick={prevMonth}>‹</button>
				<span class="cal-month-label">{CAL_MONTHS[calMonth]} {calYear}</span>
				<button class="cal-nav-btn" onclick={nextMonth}>›</button>
			</div>
		</div>

		<div class="cal-grid">
			<div class="cal-dow-row">
				{#each ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'] as dow (dow)}
					<div class="cal-dow">{dow}</div>
				{/each}
			</div>

			{#each calWeeks as week, wi (wi)}
				<div class="cal-week-row">
					{#each week as day, di (di)}
						{#if day === null}
							<div class="cal-cell cal-cell--empty"></div>
						{:else}
							{@const key = dayKey(day)}
							{@const data = historyMap.get(key) ?? null}
							{@const score = data ? macroScore(data, g) : -1}
							<div
								class="cal-cell"
								class:cal-cell--today={isToday(day)}
								class:cal-cell--has-data={data !== null}
								onclick={() => openDay(key)}
								role="button"
								tabindex="0"
								onkeydown={(e) => e.key === 'Enter' && openDay(key)}
							>
								<span class="cal-day-num">{day}</span>
								{#if data}
									<div class="cal-macros">
										<div class="cal-bar-row">
											<span class="cal-bar-label">kcal</span>
											<div class="cal-bar-track">
												<div class="cal-bar-fill" class:over={data.calories > g.calorie_goal * 1.15}
													style="width:{Math.min(data.calories/g.calorie_goal*100,100)}%;background:#e07b54"></div>
											</div>
											<span class="cal-bar-val">{Math.round(data.calories)}</span>
										</div>
										<div class="cal-bar-row">
											<span class="cal-bar-label">pro</span>
											<div class="cal-bar-track">
												<div class="cal-bar-fill"
													style="width:{Math.min(data.protein_g/g.protein_g_goal*100,100)}%;background:#5b9cf6"></div>
											</div>
											<span class="cal-bar-val">{Math.round(data.protein_g)}g</span>
										</div>
										<div class="cal-bar-row">
											<span class="cal-bar-label">carb</span>
											<div class="cal-bar-track">
												<div class="cal-bar-fill" class:over={data.carbs_g > g.carbs_g_goal * 1.15}
													style="width:{Math.min(data.carbs_g/g.carbs_g_goal*100,100)}%;background:#f0b429"></div>
											</div>
											<span class="cal-bar-val">{Math.round(data.carbs_g)}g</span>
										</div>
										<div class="cal-bar-row">
											<span class="cal-bar-label">fat</span>
											<div class="cal-bar-track">
												<div class="cal-bar-fill" class:over={data.fat_g > g.fat_g_goal * 1.15}
													style="width:{Math.min(data.fat_g/g.fat_g_goal*100,100)}%;background:#68d391"></div>
											</div>
											<span class="cal-bar-val">{Math.round(data.fat_g)}g</span>
										</div>
										<div class="cal-bar-row">
											<span class="cal-bar-label">fib</span>
											<div class="cal-bar-track">
												<div class="cal-bar-fill"
													style="width:{Math.min(data.fiber_g/g.fiber_g_goal*100,100)}%;background:#b794f4"></div>
											</div>
											<span class="cal-bar-val">{Math.round(data.fiber_g)}g</span>
										</div>
									</div>
									<div class="cal-score-dots">
										{#each Array(5) as _, i (i)}
											<span class="cal-dot" class:filled={i < score}></span>
										{/each}
									</div>
								{:else}
									<div class="cal-no-data">—</div>
								{/if}
							</div>
						{/if}
					{/each}
				</div>
			{/each}
		</div>

		<div class="cal-legend">
			<span class="cal-dot filled" style="width:8px;height:8px"></span>goal hit
			<span class="cal-dot" style="width:8px;height:8px;margin-left:10px"></span>missed
			<span style="margin-left:10px;color:var(--color-fg-mute);opacity:0.5">click any day with data to see details</span>
		</div>
	</section>
{/if}

{#if modalDate && nutritionGoals}
	{@const g = nutritionGoals}
	<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
	<div class="modal-backdrop" onclick={closeModal} role="presentation">
		<div class="modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" tabindex="-1">
			<div class="modal-head">
				<div>
					<div class="modal-date">{fmtModalDate(modalDate)}</div>
					{#if modalData && !modalLoading}
						{@const score = macroScore(modalData.totals, g)}
						<div class="modal-score">{score}/5 goals hit · {modalData.meals_logged} meals logged</div>
					{/if}
				</div>
				<button class="modal-close" onclick={closeModal}>×</button>
			</div>

			{#if modalLoading}
				<div class="modal-loading">loading…</div>
			{:else if modalData}
				{@const t = modalData.totals}
				<div class="modal-macros">
					{#each [
						{ label: 'Calories', val: t.calories, goal: g.calorie_goal, unit: 'kcal', accent: '#e07b54', hit: t.calories >= g.calorie_goal * 0.8 && t.calories <= g.calorie_goal * 1.15 },
						{ label: 'Protein',  val: t.protein_g, goal: g.protein_g_goal, unit: 'g', accent: '#5b9cf6', hit: t.protein_g >= g.protein_g_goal * 0.8 },
						{ label: 'Carbs',    val: t.carbs_g, goal: g.carbs_g_goal, unit: 'g', accent: '#f0b429', hit: t.carbs_g <= g.carbs_g_goal * 1.15 },
						{ label: 'Fat',      val: t.fat_g, goal: g.fat_g_goal, unit: 'g', accent: '#68d391', hit: t.fat_g <= g.fat_g_goal * 1.15 },
						{ label: 'Fiber',    val: t.fiber_g, goal: g.fiber_g_goal, unit: 'g', accent: '#b794f4', hit: t.fiber_g >= g.fiber_g_goal * 0.8 },
						{ label: 'Sugar',    val: t.sugar_g, goal: g.sugar_g_goal, unit: 'g', accent: '#fc8181', hit: t.sugar_g <= g.sugar_g_goal * 1.1 }
					] as m (m.label)}
						{@const pct = Math.min(m.goal > 0 ? (m.val / m.goal) * 100 : 0, 100)}
						<div class="modal-macro-row">
							<span class="modal-macro-label">{m.label}</span>
							<div class="modal-macro-track">
								<div class="modal-macro-fill" style="width:{pct}%; background:{m.hit ? m.accent : '#f87171'}"></div>
							</div>
							<span class="modal-macro-nums">
								<strong>{Math.round(m.val)}</strong><span class="modal-slash">/</span>{Math.round(m.goal)}{m.unit}
							</span>
							<span class="modal-hit-badge" class:hit={m.hit} class:miss={!m.hit}>
								{m.hit ? '✓' : '✗'}
							</span>
						</div>
					{/each}
				</div>

				{#if modalData.meals.length > 0}
					<div class="modal-meals-title">Meals</div>
					<div class="modal-meals">
						{#each modalData.meals as meal (meal.id)}
							<div class="modal-meal">
								<div class="modal-meal-head">
									<span class="modal-meal-desc">{meal.description}</span>
									{#if meal.meal_type}
										<span class="modal-meal-type">{meal.meal_type}</span>
									{/if}
									<span class="modal-meal-time">{meal.timestamp.slice(11, 16)}</span>
								</div>
								{#if meal.nutrition}
									{@const n = meal.nutrition}
									<div class="modal-meal-macros">
										<span>{Math.round(n.calories ?? 0)} kcal</span>
										<span>P {n.protein_g ?? 0}g</span>
										<span>C {n.carbs_g ?? 0}g</span>
										<span>F {n.fat_g ?? 0}g</span>
										{#if n.fiber_g}<span>fi {n.fiber_g}g</span>{/if}
										{#if n.sugar_g}<span>su {n.sugar_g}g</span>{/if}
										{#if meal.grams}<span>{meal.grams}g portion</span>{/if}
									</div>
								{:else}
									<div class="modal-meal-no-nutrition">no nutrition estimate</div>
								{/if}
							</div>
						{/each}
					</div>
				{:else}
					<div class="modal-no-meals">No meals logged this day.</div>
				{/if}
			{:else}
				<div class="modal-no-meals">No nutrition data for this day.</div>
			{/if}
		</div>
	</div>
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
		padding: 10px 14px;
		border-radius: var(--r-sm);
		background: var(--bad-12);
		color: var(--color-bad);
		font-size: 12px;
		border: 1px solid rgba(201, 106, 106, 0.3);
		margin-bottom: 12px;
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

	.filters,
	.type-row {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		margin-bottom: 12px;
	}
	.chip {
		font-size: 11.5px;
		padding: 5px 12px;
		border: 1px solid var(--color-border);
		background: var(--color-bg-2);
		color: var(--color-fg-mute);
		border-radius: 999px;
		cursor: pointer;
		text-transform: lowercase;
		transition: all 120ms;
		font-weight: 500;
	}
	.chip.small {
		font-size: 11px;
		padding: 4px 10px;
	}
	.chip:hover {
		color: var(--color-fg);
		border-color: var(--color-border-strong);
	}
	.chip.active {
		border-color: var(--color-accent);
		color: var(--color-accent);
		background: var(--accent-12);
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}
	th,
	td {
		text-align: left;
		padding: 10px 16px;
		border-bottom: 1px solid var(--color-border-2);
	}
	tbody tr:last-child td {
		border-bottom: 0;
	}
	th {
		font-size: 10.5px;
		color: var(--color-fg-dim);
		text-transform: uppercase;
		letter-spacing: 0.12em;
		font-weight: 500;
		padding-top: 14px;
		padding-bottom: 10px;
		background: var(--color-bg-2);
	}
	th:first-child {
		border-top-left-radius: var(--r-md);
	}
	th:last-child {
		border-top-right-radius: var(--r-md);
	}
	tbody tr {
		transition: background 120ms;
	}
	tbody tr:hover {
		background: var(--color-bg-2);
	}
	.time {
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--color-fg-mute);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.summary {
		color: var(--color-fg);
	}
	.actions {
		width: 36px;
		text-align: right;
	}
	.del {
		background: transparent;
		border: 0;
		color: var(--color-fg-dim);
		cursor: pointer;
		font-size: 18px;
		padding: 2px 8px;
		border-radius: var(--r-sm);
		transition: color 120ms, background 120ms;
	}
	.del:hover {
		color: var(--color-bad);
		background: var(--bad-12);
	}

	.fields {
		display: flex;
		flex-direction: column;
		gap: 12px;
		margin-top: 4px;
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
	.raw-input::placeholder {
		color: var(--color-fg-dim);
	}

	.empty {
		text-align: center;
		font-size: 12px;
		color: var(--color-fg-dim);
		padding: 40px 0;
	}

	/* ── macro goals sidebar card ── */
	.macro-goals {
		padding: 14px 16px;
		background: var(--color-bg-1);
		border: 1px solid var(--color-border);
		border-radius: var(--r-md);
		margin-top: 12px;
	}
	.mg-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 12px;
	}
	.mg-title {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-fg-mute);
	}
	.mg-source {
		font-size: 10px;
		color: var(--color-fg-mute);
		opacity: 0.55;
		text-transform: lowercase;
	}
	.mg-bars { display: flex; flex-direction: column; gap: 8px; }
	.mg-row {
		display: grid;
		grid-template-columns: 56px 1fr 76px;
		align-items: center;
		gap: 8px;
	}
	.mg-label {
		font-size: 11.5px;
		color: var(--color-fg-dim);
	}
	.mg-track {
		height: 5px;
		background: var(--color-bg-3);
		border-radius: 3px;
		overflow: hidden;
	}
	.mg-fill {
		height: 100%;
		border-radius: 3px;
		transition: width 0.4s ease;
		min-width: 2px;
	}
	.mg-nums {
		font-size: 11px;
		color: var(--color-fg-mute);
		text-align: right;
		white-space: nowrap;
	}
	.mg-nums.over { color: #f87171; font-weight: 600; }
	.mg-slash { opacity: 0.35; margin: 0 1px; }

	/* ── entry row states ── */
	tbody tr.row-expanded {
		background: var(--color-bg-2);
	}

	/* ── markers expansion row ── */
	tr.markers-row td {
		padding: 8px 16px 12px;
		background: var(--color-bg-2);
		border-bottom: 1px solid var(--color-border-2);
	}
	.m-loading {
		font-size: 11px;
		color: var(--color-fg-dim);
		font-style: italic;
	}
	.marker-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.mchip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 11px;
		border-radius: 999px;
		padding: 3px 9px;
		border: 1px solid transparent;
		max-width: 100%;
		flex-shrink: 1;
	}
	.mchip-label {
		font-weight: 600;
		text-transform: lowercase;
		letter-spacing: 0.04em;
		white-space: nowrap;
	}
	.mchip-sep {
		opacity: 0.5;
	}
	.mchip-value {
		color: inherit;
		opacity: 0.85;
	}
	.mchip.good {
		background: rgba(70, 200, 140, 0.12);
		border-color: rgba(70, 200, 140, 0.35);
		color: #46c88c;
	}
	.mchip.bad {
		background: var(--bad-12);
		border-color: rgba(201, 106, 106, 0.35);
		color: var(--color-bad);
	}
	.mchip.neutral {
		background: var(--color-bg-1);
		border-color: var(--color-border);
		color: var(--color-fg-mute);
	}
	.mchip.info {
		background: var(--accent-12);
		border-color: rgba(93, 208, 200, 0.35);
		color: var(--color-accent);
	}

	/* ── macro chips on food entries ── */
	.macro-row {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 4px;
	}
	.macro {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--color-fg-mute);
		background: var(--color-bg-2);
		border: 1px solid var(--color-border);
		border-radius: 999px;
		padding: 1px 7px;
	}
	.macro.kcal {
		color: var(--color-accent);
		border-color: rgba(93, 208, 200, 0.35);
		background: var(--accent-12);
	}
	.macro.fi {
		color: #5bbf7a;
		border-color: rgba(91, 191, 122, 0.35);
		background: rgba(91, 191, 122, 0.08);
	}
	.macro.su {
		color: var(--color-warn);
		border-color: rgba(230, 180, 80, 0.35);
		background: var(--warn-12);
	}
	.macro.conf {
		color: var(--color-warn);
		border-color: rgba(230, 180, 80, 0.35);
		background: var(--warn-12);
		font-family: inherit;
		font-size: 10px;
	}
	.macro.estimating {
		color: var(--color-fg-dim);
		border-color: transparent;
		background: none;
		font-style: italic;
		animation: pulse 1.4s ease-in-out infinite;
	}
	@keyframes pulse {
		0%, 100% { opacity: 0.5; }
		50% { opacity: 1; }
	}
	.estimate-btn {
		font-size: 10px;
		padding: 2px 8px;
		border: 1px dashed var(--color-border-strong);
		border-radius: 999px;
		background: none;
		color: var(--color-accent);
		cursor: pointer;
		transition: background 120ms, border-color 120ms;
	}
	.estimate-btn:hover {
		background: var(--accent-12);
		border-color: var(--color-accent);
	}

	/* ── nutrition calendar ── */
	.cal-section {
		margin-top: 32px;
	}
	.cal-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 16px;
		flex-wrap: wrap;
		gap: 8px;
	}
	.cal-title-row { display: flex; align-items: baseline; gap: 12px; }
	.cal-title {
		margin: 0;
		font-size: 18px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.cal-goals-hint {
		font-size: 11px;
		color: var(--color-fg-mute);
		opacity: 0.6;
	}
	.cal-nav {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.cal-nav-btn {
		background: var(--color-bg-2);
		border: 1px solid var(--color-border);
		color: var(--color-fg);
		border-radius: var(--r-sm);
		width: 28px;
		height: 28px;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 16px;
		cursor: pointer;
		transition: background 120ms;
	}
	.cal-nav-btn:hover { background: var(--color-bg-3); }
	.cal-month-label {
		font-size: 14px;
		font-weight: 600;
		min-width: 140px;
		text-align: center;
	}
	.cal-dow-row {
		display: grid;
		grid-template-columns: repeat(7, 1fr);
		gap: 4px;
		margin-bottom: 4px;
	}
	.cal-dow {
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-fg-mute);
		text-align: center;
		padding: 4px 0;
	}
	.cal-week-row {
		display: grid;
		grid-template-columns: repeat(7, 1fr);
		gap: 4px;
		margin-bottom: 4px;
	}
	.cal-cell {
		background: var(--color-bg-1);
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		min-height: 110px;
		padding: 8px;
		display: flex;
		flex-direction: column;
		gap: 4px;
		position: relative;
	}
	.cal-cell--empty {
		background: transparent;
		border-color: transparent;
	}
	.cal-cell--today {
		border-color: var(--color-accent);
	}
	.cal-cell--has-data {
		cursor: pointer;
	}
	.cal-cell--has-data:hover {
		border-color: var(--color-border-strong);
		background: var(--color-bg-2);
	}
	.cal-day-num {
		font-size: 11px;
		font-weight: 700;
		color: var(--color-fg-dim);
		line-height: 1;
	}
	.cal-cell--today .cal-day-num {
		color: var(--color-accent);
	}
	.cal-macros {
		display: flex;
		flex-direction: column;
		gap: 3px;
		flex: 1;
	}
	.cal-bar-row {
		display: grid;
		grid-template-columns: 24px 1fr 32px;
		align-items: center;
		gap: 4px;
	}
	.cal-bar-label {
		font-size: 9px;
		color: var(--color-fg-mute);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.cal-bar-track {
		height: 4px;
		background: var(--color-bg-3);
		border-radius: 2px;
		overflow: hidden;
	}
	.cal-bar-fill {
		height: 100%;
		border-radius: 2px;
		min-width: 2px;
		transition: width 0.3s ease;
	}
	.cal-bar-fill.over { background: #f87171 !important; }
	.cal-bar-val {
		font-size: 9px;
		color: var(--color-fg-mute);
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.cal-score-dots {
		display: flex;
		gap: 3px;
		margin-top: 2px;
	}
	.cal-dot {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background: var(--color-bg-3);
	}
	.cal-dot.filled { background: #4ade80; }
	.cal-no-data {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 18px;
		color: var(--color-border);
	}
	.cal-legend {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 12px;
		font-size: 11px;
		color: var(--color-fg-mute);
	}
	.cal-legend-swatch {
		display: inline-block;
		width: 12px;
		height: 12px;
		border-radius: 3px;
		margin-left: 8px;
	}
	.cal-legend-swatch:first-child { margin-left: 0; }
	.cal-legend-swatch.good { background: #4ade80; }
	.cal-legend-swatch.ok   { background: #f0b429; }
	.cal-legend-swatch.poor { background: #f87171; }
	.cal-legend-swatch.none { background: var(--color-bg-1); border: 1px solid var(--color-border); }
	@media (max-width: 720px) {
		.cal-bar-val { display: none; }
		.cal-cell { min-height: 80px; padding: 6px; }
	}

	/* ── day detail modal ── */
	.modal-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0,0,0,0.65);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
		padding: 24px;
	}
	.modal {
		background: var(--color-bg-0, #0b0b0e);
		border: 1px solid var(--color-border);
		border-radius: var(--r-lg, 12px);
		width: 100%;
		max-width: 520px;
		max-height: 85vh;
		overflow-y: auto;
		padding: 24px;
		display: flex;
		flex-direction: column;
		gap: 20px;
	}
	.modal-head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}
	.modal-date {
		font-size: 18px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.modal-score {
		font-size: 12px;
		color: var(--color-fg-mute);
		margin-top: 4px;
	}
	.modal-close {
		background: none;
		border: none;
		font-size: 22px;
		color: var(--color-fg-mute);
		cursor: pointer;
		line-height: 1;
		padding: 0 4px;
		flex-shrink: 0;
	}
	.modal-close:hover { color: var(--color-fg); }
	.modal-loading { color: var(--color-fg-mute); font-size: 13px; }
	.modal-macros { display: flex; flex-direction: column; gap: 10px; }
	.modal-macro-row {
		display: grid;
		grid-template-columns: 70px 1fr 110px 24px;
		align-items: center;
		gap: 10px;
	}
	.modal-macro-label { font-size: 13px; color: var(--color-fg-dim); }
	.modal-macro-track {
		height: 7px;
		background: var(--color-bg-3);
		border-radius: 4px;
		overflow: hidden;
	}
	.modal-macro-fill {
		height: 100%;
		border-radius: 4px;
		min-width: 3px;
		transition: width 0.35s ease;
	}
	.modal-macro-nums {
		font-size: 12px;
		color: var(--color-fg-dim);
		text-align: right;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.modal-macro-nums strong { color: var(--color-fg); font-weight: 600; }
	.modal-slash { opacity: 0.35; margin: 0 1px; }
	.modal-hit-badge {
		font-size: 13px;
		font-weight: 700;
		text-align: center;
	}
	.modal-hit-badge.hit { color: #4ade80; }
	.modal-hit-badge.miss { color: var(--color-fg-mute); opacity: 0.4; }
	.modal-meals-title {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-fg-mute);
		padding-bottom: 8px;
		border-bottom: 1px solid var(--color-border-2);
	}
	.modal-meals { display: flex; flex-direction: column; gap: 10px; }
	.modal-meal {
		padding: 10px 12px;
		background: var(--color-bg-1);
		border-radius: var(--r-sm);
		border: 1px solid var(--color-border-2);
	}
	.modal-meal-head {
		display: flex;
		align-items: baseline;
		gap: 8px;
		flex-wrap: wrap;
		margin-bottom: 4px;
	}
	.modal-meal-desc {
		font-size: 13px;
		font-weight: 500;
		color: var(--color-fg);
		flex: 1;
	}
	.modal-meal-type {
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-fg-mute);
		background: var(--color-bg-3);
		padding: 2px 6px;
		border-radius: 999px;
	}
	.modal-meal-time {
		font-size: 11px;
		color: var(--color-fg-mute);
		font-variant-numeric: tabular-nums;
	}
	.modal-meal-macros {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		font-size: 11.5px;
		color: var(--color-fg-dim);
	}
	.modal-meal-macros span:first-child { color: var(--color-fg); font-weight: 500; }
	.modal-meal-no-nutrition {
		font-size: 11px;
		color: var(--color-fg-mute);
		opacity: 0.5;
	}
	.modal-no-meals {
		font-size: 13px;
		color: var(--color-fg-mute);
		text-align: center;
		padding: 12px 0;
	}
</style>
