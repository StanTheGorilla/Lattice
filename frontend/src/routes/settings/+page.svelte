<script lang="ts">
	import { onMount } from 'svelte';
	import { planning, alertsApi } from '$lib/api/client';
	import type { AIRuleOut, AlertRuleOut } from '$lib/api/types';
	import Card from '$lib/components/ui/Card.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';

	// ---------- profile form ----------
	let profileLoaded = $state(false);
	let saving = $state(false);
	let savedAt = $state(0); // timestamp; >0 means "just saved"

	let displayName = $state('');
	let birthday = $state('');
	let sexAtBirth = $state('');
	let heightCm = $state('');
	let weightKg = $state('');
	let chronotype = $state('');
	let targetWakeTime = $state('');
	let targetSleepMin = $state('');
	let caffeineCutoff = $state('');
	let lastMealCutoff = $state('');
	let screenOffHour = $state('');
	let workPattern = $state('');
	let healthFlags = $state('');

	const justSaved = $derived(Date.now() - savedAt < 2500);

	// ---------- AI rules ----------
	let rules = $state<AIRuleOut[]>([]);
	let newRule = $state('');
	let addingRule = $state(false);
	let ruleError = $state('');

	onMount(async () => {
		const [prof, ruleList] = await Promise.all([
			planning.getProfile(),
			planning.listRules()
		]);
		loadAlerts();
		displayName = prof.display_name ?? '';
		birthday = prof.birthday ?? '';
		sexAtBirth = prof.sex_at_birth ?? '';
		heightCm = prof.height_cm != null ? String(prof.height_cm) : '';
		weightKg = prof.weight_kg != null ? String(prof.weight_kg) : '';
		chronotype = prof.chronotype ?? '';
		targetWakeTime = prof.target_wake_time ?? '';
		targetSleepMin = prof.target_sleep_min != null ? String(prof.target_sleep_min) : '';
		caffeineCutoff = prof.caffeine_cutoff_hour != null ? String(prof.caffeine_cutoff_hour) : '';
		lastMealCutoff = prof.last_meal_cutoff_hour != null ? String(prof.last_meal_cutoff_hour) : '';
		screenOffHour = prof.screen_off_hour != null ? String(prof.screen_off_hour) : '';
		workPattern = prof.work_pattern ?? '';
		healthFlags = prof.health_flags ?? '';
		profileLoaded = true;
		rules = ruleList;
	});

	function toNum(s: string): number | null {
		const n = parseFloat(s);
		return isNaN(n) ? null : n;
	}
	function toInt(s: string): number | null {
		const n = parseInt(s, 10);
		return isNaN(n) ? null : n;
	}

	async function saveProfile() {
		saving = true;
		try {
			await planning.patchProfile({
				display_name: displayName || null,
				birthday: birthday || null,
				sex_at_birth: sexAtBirth || null,
				height_cm: toNum(heightCm),
				weight_kg: toNum(weightKg),
				chronotype: chronotype || null,
				target_wake_time: targetWakeTime || null,
				target_sleep_min: toInt(targetSleepMin),
				caffeine_cutoff_hour: toInt(caffeineCutoff),
				last_meal_cutoff_hour: toInt(lastMealCutoff),
				screen_off_hour: toInt(screenOffHour),
				work_pattern: workPattern || null,
				health_flags: healthFlags || null
			});
			savedAt = Date.now();
		} finally {
			saving = false;
		}
	}

	async function toggleRule(rule: AIRuleOut) {
		const updated = await planning.patchRule(rule.id, { active: !rule.active });
		rules = rules.map((r) => (r.id === rule.id ? updated : r));
	}

	async function deleteRule(id: number) {
		await planning.deleteRule(id);
		rules = rules.filter((r) => r.id !== id);
	}

	// ---------- alert rules ----------
	let alertRules = $state<AlertRuleOut[]>([]);
	let newAlertMetric = $state('readiness_score');
	let newAlertOp = $state<'lt' | 'lte' | 'gt' | 'gte'>('lt');
	let newAlertThreshold = $state('');
	let newAlertLabel = $state('');
	let newAlertCooldown = $state('4');
	let addingAlert = $state(false);
	let alertError = $state('');

	async function loadAlerts() {
		alertRules = await alertsApi.listRules().catch(() => []);
	}

	async function submitAlert() {
		alertError = '';
		const label = newAlertLabel.trim();
		const threshold = parseFloat(newAlertThreshold);
		if (!label || isNaN(threshold)) { alertError = 'Label and threshold are required.'; return; }
		try {
			const r = await alertsApi.createRule({
				metric_name: newAlertMetric,
				operator: newAlertOp,
				threshold,
				label,
				cooldown_hours: parseInt(newAlertCooldown, 10) || 4
			});
			alertRules = [r, ...alertRules];
			newAlertLabel = '';
			newAlertThreshold = '';
			addingAlert = false;
		} catch {
			alertError = 'Could not save rule.';
		}
	}

	async function toggleAlert(rule: AlertRuleOut) {
		const updated = await alertsApi.patchRule(rule.id, { active: !rule.active });
		alertRules = alertRules.map((r) => (r.id === rule.id ? updated : r));
	}

	async function deleteAlert(id: number) {
		await alertsApi.deleteRule(id);
		alertRules = alertRules.filter((r) => r.id !== id);
	}

	async function submitRule() {
		const text = newRule.trim();
		if (!text) return;
		ruleError = '';
		try {
			const r = await planning.createRule({ rule: text });
			rules = [r, ...rules];
			newRule = '';
			addingRule = false;
		} catch {
			ruleError = 'Rule already exists or could not be saved.';
		}
	}
</script>

<div class="page">
	<h1 class="page-title">Settings</h1>

	<!-- ── Profile ── -->
	<section class="section">
		<div class="section-head">
			<span class="section-label">Profile</span>
			<span class="section-sub">Used by the AI and sleep algorithms.</span>
		</div>

		{#if profileLoaded}
			<Card>
				<div class="form">
					<div class="row row-3">
						<div class="field">
							<label class="label" for="displayName">Name</label>
							<Input id="displayName" placeholder="How should the AI address you?" bind:value={displayName} />
						</div>
						<div class="field">
							<label class="label" for="birthday">Birthday</label>
							<Input id="birthday" type="date" bind:value={birthday} />
						</div>
						<div class="field">
							<label class="label" for="sex">Sex at birth</label>
							<select id="sex" class="select" bind:value={sexAtBirth}>
								<option value="">— not set —</option>
								<option value="male">Male</option>
								<option value="female">Female</option>
								<option value="intersex">Intersex</option>
								<option value="prefer_not_to_say">Prefer not to say</option>
							</select>
						</div>
					</div>

					<div class="row row-3">
						<div class="field">
							<label class="label" for="height">Height (cm)</label>
							<Input id="height" type="number" min={50} max={260} placeholder="180" bind:value={heightCm} />
						</div>
						<div class="field">
							<label class="label" for="weight">Weight (kg)</label>
							<Input id="weight" type="number" min={20} max={400} placeholder="75" bind:value={weightKg} />
						</div>
						<div class="field">
							<label class="label" for="chronotype">Chronotype</label>
							<select id="chronotype" class="select" bind:value={chronotype}>
								<option value="">— not set —</option>
								<option value="morning">Morning</option>
								<option value="neutral">Neutral</option>
								<option value="evening">Evening</option>
							</select>
						</div>
					</div>

					<div class="row-divider">Sleep &amp; Schedule</div>

					<div class="row row-3">
						<div class="field">
							<label class="label" for="wakeTime">Target wake time</label>
							<Input id="wakeTime" type="time" bind:value={targetWakeTime} />
						</div>
						<div class="field">
							<label class="label" for="sleepMin">Target sleep (min)</label>
							<Input id="sleepMin" type="number" min={180} max={720} placeholder="480" bind:value={targetSleepMin} />
						</div>
						<div class="field">
							<label class="label" for="caffeine">Caffeine cutoff (hour)</label>
							<Input id="caffeine" type="number" min={0} max={23} placeholder="14" bind:value={caffeineCutoff} />
						</div>
					</div>

					<div class="row row-2">
						<div class="field">
							<label class="label" for="lastMeal">Last meal cutoff (hour)</label>
							<Input id="lastMeal" type="number" min={0} max={23} placeholder="20" bind:value={lastMealCutoff} />
						</div>
						<div class="field">
							<label class="label" for="screenOff">Screens off (hour)</label>
							<Input id="screenOff" type="number" min={0} max={23} placeholder="22" bind:value={screenOffHour} />
						</div>
					</div>

					<div class="row-divider">Context for AI</div>

					<div class="field">
						<label class="label" for="workPattern">Work pattern</label>
						<textarea
							id="workPattern"
							class="textarea"
							placeholder="e.g. 9–5 office, 3 days remote, heavy meetings Mon + Wed"
							rows={2}
							bind:value={workPattern}
						></textarea>
					</div>

					<div class="field">
						<label class="label" for="healthFlags">Health flags</label>
						<textarea
							id="healthFlags"
							class="textarea"
							placeholder="e.g. mild asthma, lower back, lactose intolerant"
							rows={2}
							bind:value={healthFlags}
						></textarea>
					</div>

					<div class="form-footer">
						<Button variant="primary" onclick={saveProfile} disabled={saving}>
							{saving ? 'Saving…' : 'Save Profile'}
						</Button>
						{#if justSaved}
							<span class="saved-msg">Saved</span>
						{/if}
					</div>
				</div>
			</Card>
		{:else}
			<div class="loading-row">Loading…</div>
		{/if}
	</section>

	<!-- ── Alert Rules ── -->
	<section class="section">
		<div class="section-head">
			<span class="section-label">Alert Rules</span>
			<span class="section-sub">Discord DMs when a metric crosses a threshold.</span>
		</div>

		<Card>
			{#if addingAlert}
				<div class="alert-form">
					<div class="row row-3">
						<div class="field">
							<label class="label" for="alertMetric">Metric</label>
							<select id="alertMetric" class="select" bind:value={newAlertMetric}>
								<option value="readiness_score">readiness_score</option>
								<option value="hrv_overnight_avg">hrv_overnight_avg</option>
								<option value="sleep_score">sleep_score</option>
								<option value="resting_hr">resting_hr</option>
								<option value="body_battery_start">body_battery_start</option>
								<option value="stress_avg">stress_avg</option>
							</select>
						</div>
						<div class="field">
							<label class="label" for="alertOp">Condition</label>
							<select id="alertOp" class="select" bind:value={newAlertOp}>
								<option value="lt">&#60; (below)</option>
								<option value="lte">≤ (at or below)</option>
								<option value="gt">&#62; (above)</option>
								<option value="gte">≥ (at or above)</option>
							</select>
						</div>
						<div class="field">
							<label class="label" for="alertThreshold">Threshold</label>
							<Input id="alertThreshold" type="number" placeholder="e.g. 40" bind:value={newAlertThreshold} />
						</div>
					</div>
					<div class="row row-2">
						<div class="field">
							<label class="label" for="alertLabel">Label (shown in DM)</label>
							<Input id="alertLabel" placeholder="Low readiness — take it easy" bind:value={newAlertLabel} />
						</div>
						<div class="field">
							<label class="label" for="alertCooldown">Cooldown (hours)</label>
							<Input id="alertCooldown" type="number" min={1} max={168} placeholder="4" bind:value={newAlertCooldown} />
						</div>
					</div>
					{#if alertError}<span class="rule-error">{alertError}</span>{/if}
					<div class="rule-add-actions">
						<Button variant="primary" size="sm" onclick={submitAlert}>Add Alert</Button>
						<Button size="sm" onclick={() => { addingAlert = false; alertError = ''; }}>Cancel</Button>
					</div>
				</div>
			{:else}
				<button class="add-rule-btn" onclick={() => { addingAlert = true; }}>+ Add alert rule</button>
			{/if}

			{#if alertRules.length === 0 && !addingAlert}
				<div class="rules-empty">No alert rules. Add one to get Discord DMs when metrics cross thresholds.</div>
			{/if}

			{#each alertRules as ar (ar.id)}
				<div class="rule-row" class:inactive={!ar.active}>
					<div class="alert-body">
						<span class="alert-label">{ar.label}</span>
						<span class="alert-cond">{ar.metric_name} {ar.operator} {ar.threshold} · cooldown {ar.cooldown_hours}h</span>
					</div>
					<div class="rule-controls">
						<button
							class="toggle-btn"
							class:active={ar.active}
							onclick={() => toggleAlert(ar)}
							title={ar.active ? 'Disable' : 'Enable'}
						>{ar.active ? 'on' : 'off'}</button>
						<button class="delete-btn" onclick={() => deleteAlert(ar.id)} title="Delete">×</button>
					</div>
				</div>
			{/each}
		</Card>
	</section>

	<!-- ── AI Rules ── -->
	<section class="section">
		<div class="section-head">
			<span class="section-label">AI Rules</span>
			<span class="section-sub">Hard constraints the AI must always follow.</span>
		</div>

		<Card>
			{#if addingRule}
				<div class="rule-add-form">
					<textarea
						class="textarea"
						placeholder="e.g. Never suggest reducing caffeine to zero — I will not comply."
						rows={2}
						bind:value={newRule}
						onkeydown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submitRule(); }}
					></textarea>
					{#if ruleError}
						<span class="rule-error">{ruleError}</span>
					{/if}
					<div class="rule-add-actions">
						<Button variant="primary" size="sm" onclick={submitRule}>Add Rule</Button>
						<Button size="sm" onclick={() => { addingRule = false; newRule = ''; ruleError = ''; }}>Cancel</Button>
					</div>
				</div>
			{:else}
				<button class="add-rule-btn" onclick={() => { addingRule = true; }}>+ Add rule</button>
			{/if}

			{#if rules.length === 0 && !addingRule}
				<div class="rules-empty">No rules yet. Add one to constrain the AI.</div>
			{/if}

			{#each rules as rule (rule.id)}
				<div class="rule-row" class:inactive={!rule.active}>
					<span class="rule-text">{rule.rule}</span>
					<div class="rule-controls">
						<button
							class="toggle-btn"
							class:active={rule.active}
							onclick={() => toggleRule(rule)}
							title={rule.active ? 'Disable' : 'Enable'}
						>
							{rule.active ? 'on' : 'off'}
						</button>
						<button class="delete-btn" onclick={() => deleteRule(rule.id)} title="Delete">×</button>
					</div>
				</div>
			{/each}
		</Card>
	</section>
</div>

<style>
	.page {
		max-width: 760px;
	}
	.page-title {
		font-size: 22px;
		font-weight: 600;
		color: var(--color-fg);
		margin: 0 0 28px;
	}
	.section {
		margin-bottom: 36px;
	}
	.section-head {
		display: flex;
		align-items: baseline;
		gap: 12px;
		margin-bottom: 12px;
	}
	.section-label {
		font-size: 12px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--color-fg-mute);
	}
	.section-sub {
		font-size: 12px;
		color: var(--color-fg-dim);
	}
	.form {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
	.row {
		display: grid;
		gap: 12px;
	}
	.row-2 { grid-template-columns: 1fr 1fr; }
	.row-3 { grid-template-columns: 1fr 1fr 1fr; }
	.row-divider {
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--color-fg-faint);
		padding-top: 4px;
		border-top: 1px solid var(--color-border);
		margin-top: 4px;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 5px;
	}
	.label {
		font-size: 11.5px;
		color: var(--color-fg-mute);
		font-weight: 500;
	}
	.select {
		height: 34px;
		padding: 0 10px;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		background: var(--color-bg-2);
		color: var(--color-fg);
		font-size: 13px;
		outline: none;
		cursor: pointer;
		transition: border-color 120ms;
		appearance: none;
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%23666' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: right 10px center;
	}
	.select:focus { border-color: var(--color-accent); }
	.textarea {
		padding: 8px 12px;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		background: var(--color-bg-2);
		color: var(--color-fg);
		font-size: 13px;
		line-height: 1.5;
		resize: vertical;
		outline: none;
		font-family: inherit;
		transition: border-color 120ms;
		width: 100%;
		box-sizing: border-box;
	}
	.textarea:focus { border-color: var(--color-accent); background: var(--color-bg-1); }
	.form-footer {
		display: flex;
		align-items: center;
		gap: 12px;
		padding-top: 4px;
	}
	.saved-msg {
		font-size: 12px;
		color: var(--color-ok);
	}
	.loading-row {
		font-size: 12px;
		color: var(--color-fg-dim);
		padding: 20px 0;
	}

	/* rules */
	.add-rule-btn {
		font-size: 12px;
		color: var(--color-accent);
		background: none;
		border: 0;
		padding: 0 0 14px;
		cursor: pointer;
		transition: opacity 120ms;
		display: block;
	}
	.add-rule-btn:hover { opacity: 0.75; }
	.rule-add-form {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding-bottom: 14px;
		border-bottom: 1px solid var(--color-border);
		margin-bottom: 4px;
	}
	.rule-add-actions {
		display: flex;
		gap: 8px;
	}
	.rule-error {
		font-size: 11.5px;
		color: var(--color-bad);
	}
	.rules-empty {
		font-size: 12px;
		color: var(--color-fg-dim);
		padding: 4px 0 8px;
	}
	.rule-row {
		display: flex;
		align-items: flex-start;
		gap: 12px;
		padding: 10px 0;
		border-bottom: 1px solid var(--color-border);
	}
	.rule-row:last-child { border-bottom: 0; }
	.rule-row.inactive .rule-text { opacity: 0.4; }
	.rule-text {
		flex: 1;
		font-size: 13px;
		color: var(--color-fg);
		line-height: 1.5;
	}
	.rule-controls {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
	}
	.toggle-btn {
		font-family: var(--font-mono);
		font-size: 10px;
		padding: 2px 7px;
		border-radius: 999px;
		border: 1px solid var(--color-border);
		background: var(--color-bg-2);
		color: var(--color-fg-dim);
		cursor: pointer;
		transition: background 120ms, color 120ms, border-color 120ms;
	}
	.toggle-btn.active {
		background: var(--accent-12);
		border-color: rgba(93, 208, 200, 0.4);
		color: var(--color-accent);
	}
	.delete-btn {
		font-size: 15px;
		line-height: 1;
		color: var(--color-fg-faint);
		background: none;
		border: 0;
		padding: 0 3px;
		cursor: pointer;
		transition: color 120ms;
	}
	.delete-btn:hover { color: var(--color-bad); }
	.alert-form {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding-bottom: 14px;
		border-bottom: 1px solid var(--color-border);
		margin-bottom: 4px;
	}
	.alert-body {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.alert-label {
		font-size: 13px;
		color: var(--color-fg);
		font-weight: 500;
	}
	.alert-cond {
		font-size: 11px;
		font-family: var(--font-mono);
		color: var(--color-fg-dim);
	}
</style>
