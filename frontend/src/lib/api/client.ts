// Typed fetch wrapper for the Lattice backend.
//
// Uses cookies for auth (session cookie set by POST /auth/login). All requests
// go through `request()` so error handling is centralised.

import type {
	AdvisorIntent,
	AdvisorOutput,
	AuthStatus,
	CaffeineStatusOutput,
	CalendarEvent,
	Entry,
	EntryListResponse,
	EntryMarkers,
	EntryType,
	HabitAdherenceOutput,
	HabitCheckin,
	HabitDefinition,
	Metric,
	MetricListResponse,
	MetricsLatestResponse,
	ReadinessOutput,
	SleepWindowOutput,
	TrainingRecOutput,
	WeeklyReport,
	WorkWindowsOutput
} from './types';

const BASE = '/api';

export class ApiError extends Error {
	constructor(
		public status: number,
		public body: unknown,
		message: string
	) {
		super(message);
		this.name = 'ApiError';
	}
}

async function request<T>(
	path: string,
	init: RequestInit = {}
): Promise<T> {
	const url = path.startsWith('http') ? path : `${BASE}${path}`;
	const response = await fetch(url, {
		credentials: 'include',
		headers: {
			'Content-Type': 'application/json',
			...(init.headers ?? {})
		},
		...init
	});
	const text = await response.text();
	const body = text ? JSON.parse(text) : null;
	if (!response.ok) {
		const message =
			(body && typeof body === 'object' && 'detail' in body
				? JSON.stringify((body as { detail: unknown }).detail)
				: response.statusText) || `HTTP ${response.status}`;
		throw new ApiError(response.status, body, message);
	}
	return body as T;
}

function qs(params: Record<string, string | number | undefined | null>): string {
	const parts: string[] = [];
	for (const [k, v] of Object.entries(params)) {
		if (v === undefined || v === null || v === '') continue;
		parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
	}
	return parts.length ? '?' + parts.join('&') : '';
}

// ---------- auth ----------

export const auth = {
	login: (password: string) =>
		request<{ ok: boolean; permissive: boolean }>('/auth/login', {
			method: 'POST',
			body: JSON.stringify({ password })
		}),
	logout: () => request<void>('/auth/logout', { method: 'POST' }),
	status: () => request<AuthStatus>('/auth/status')
};

// ---------- metrics ----------

export const metrics = {
	list: (params: { name?: string; from?: string; to?: string; limit?: number; offset?: number } = {}) =>
		request<MetricListResponse>(`/metrics${qs(params)}`),
	latest: (names: string[]) =>
		request<MetricsLatestResponse>(`/metrics/latest${qs({ names: names.join(',') })}`),
	baseline: (name: string, days?: number) =>
		request<{ name: string; mean: number | null; sd: number | null; n: number; window_days: number }>(
			`/metrics/baseline${qs({ name, days })}`
		)
};

// ---------- calendar ----------

export const calendar = {
	events: (from: string, to: string) =>
		request<CalendarEvent[]>(`/calendar/events${qs({ from, to })}`),
	sync: () => request<{ refreshed: number; window_from: string; window_to: string }>('/calendar/sync', { method: 'POST' })
};

// ---------- entries ----------

export const entries = {
	list: (params: { type?: EntryType; from?: string; to?: string; limit?: number; offset?: number } = {}) =>
		request<EntryListResponse>(`/entries${qs(params)}`),
	create: (entry: { type: EntryType; data: Record<string, unknown>; timestamp?: string; source?: string }) =>
		request<Entry>('/entries', { method: 'POST', body: JSON.stringify(entry) }),
	patch: (id: number, body: { data?: Record<string, unknown>; timestamp?: string }) =>
		request<Entry>(`/entries/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
	remove: (id: number) => request<void>(`/entries/${id}`, { method: 'DELETE' }),
	markers: (id: number) => request<EntryMarkers>(`/entries/${id}/markers`),
	estimateNutrition: (id: number) => request<Entry>(`/entries/${id}/estimate-nutrition`, { method: 'POST' })
};

// ---------- habits ----------

export const habits = {
	list: (active?: boolean) =>
		request<HabitDefinition[]>(`/habits${qs({ active: active === undefined ? undefined : String(active) })}`),
	create: (body: { name: string; target_per_week?: number }) =>
		request<HabitDefinition>('/habits', { method: 'POST', body: JSON.stringify(body) }),
	patch: (id: number, body: { name?: string; target_per_week?: number; active?: boolean }) =>
		request<HabitDefinition>(`/habits/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
	checkins: (habitId: number, from?: string, to?: string) =>
		request<{ items: HabitCheckin[] }>(`/habits/${habitId}/checkins${qs({ from, to })}`),
	checkin: (habitId: number, body: { date: string; completed?: boolean; note?: string }) =>
		request<HabitCheckin>(`/habits/${habitId}/checkins`, {
			method: 'POST',
			body: JSON.stringify(body)
		}),
	uncheck: (habitId: number, date: string) =>
		request<void>(`/habits/${habitId}/checkins/${date}`, { method: 'DELETE' })
};

// ---------- functions (F1–F5, F8, F9a) ----------

export const fns = {
	readiness: (date?: string) =>
		request<ReadinessOutput>(`/functions/readiness${qs({ date })}`),
	workWindows: (date?: string, min_minutes?: number) =>
		request<WorkWindowsOutput>(`/functions/work_windows${qs({ date, min_minutes })}`),
	trainingRec: (date?: string) =>
		request<TrainingRecOutput>(`/functions/training_recommendation${qs({ date })}`),
	sleepWindow: (date?: string) =>
		request<SleepWindowOutput>(`/functions/sleep_window${qs({ date })}`),
	caffeineStatus: (at?: string) =>
		request<CaffeineStatusOutput>(`/functions/caffeine_status${qs({ at })}`),
	advisor: (intent: AdvisorIntent, date?: string) =>
		request<AdvisorOutput>(`/functions/advisor${qs({ intent, date })}`),
	habitsAdherence: (from?: string, to?: string) =>
		request<HabitAdherenceOutput>(`/functions/habits/adherence${qs({ from, to })}`)
};

// ---------- sync ----------

export type GarminStreamEvent =
	| {
			type: 'progress';
			day: string;
			done: number;
			total: number;
			metrics_written: number;
			workouts_written: number;
			samples_written: number;
			stages_written: number;
			errors: string[];
	  }
	| {
			type: 'done';
			metrics_total: number;
			workouts_total: number;
			samples_total: number;
			stages_total: number;
			total: number;
	  }
	| { type: 'error'; code: string; message: string };

export const sync = {
	garmin: (days?: number) =>
		request<{
			metrics_written: number;
			workouts_written: number;
			samples_written: number;
			stages_written: number;
			dates: string[];
			errors: string[];
		}>(`/sync/garmin${qs({ days })}`, { method: 'POST' }),
	status: () =>
		request<{ garmin_last_metric_at: string | null; calendar_last_fetched_at: string | null }>(
			`/sync/status`
		),
	garminStream: async (
		days: number,
		onEvent: (e: GarminStreamEvent) => void,
		signal?: AbortSignal
	): Promise<void> => {
		const res = await fetch(`${BASE}/sync/garmin/stream${qs({ days })}`, {
			method: 'POST',
			credentials: 'include',
			signal
		});
		if (!res.ok || !res.body) {
			let body: unknown = null;
			try {
				body = await res.json();
			} catch {
				/* ignore */
			}
			throw new ApiError(res.status, body, `stream failed: HTTP ${res.status}`);
		}
		const reader = res.body.getReader();
		const decoder = new TextDecoder();
		let buf = '';
		// eslint-disable-next-line no-constant-condition
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;
			buf += decoder.decode(value, { stream: true });
			let idx: number;
			while ((idx = buf.indexOf('\n\n')) !== -1) {
				const block = buf.slice(0, idx);
				buf = buf.slice(idx + 2);
				for (const line of block.split('\n')) {
					if (!line.startsWith('data:')) continue;
					const json = line.slice(5).trim();
					if (!json) continue;
					try {
						onEvent(JSON.parse(json) as GarminStreamEvent);
					} catch (err) {
						console.warn('sync stream: bad event', err);
					}
				}
			}
		}
	}
};

// ---------- planning system ----------

import type { AIRuleOut, AreaOut, DecisionOut, InitiativeOut, PlanOut, ProfileOut } from './types';

export const planning = {
	getProfile: () => request<ProfileOut>('/profile'),
	patchProfile: (body: Record<string, unknown>) =>
		request<ProfileOut>('/profile', { method: 'PATCH', body: JSON.stringify(body) }),

	listAreas: (includeArchived = false) =>
		request<AreaOut[]>(`/areas${qs({ include_archived: includeArchived ? 'true' : undefined })}`),
	createArea: (body: { key: string; name: string; description?: string; color?: string; sort_order?: number }) =>
		request<AreaOut>('/areas', { method: 'POST', body: JSON.stringify(body) }),
	patchArea: (id: number, body: Record<string, unknown>) =>
		request<AreaOut>(`/areas/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
	deleteArea: (id: number) => request<void>(`/areas/${id}`, { method: 'DELETE' }),

	listInitiatives: (params: { area_id?: number; status?: string } = {}) =>
		request<InitiativeOut[]>(`/initiatives${qs(params)}`),
	createInitiative: (body: { area_id: number; title: string; why?: string; target_outcome?: string; target_date?: string; review_at?: string }) =>
		request<InitiativeOut>('/initiatives', { method: 'POST', body: JSON.stringify(body) }),
	patchInitiative: (id: number, body: Record<string, unknown>) =>
		request<InitiativeOut>(`/initiatives/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
	deleteInitiative: (id: number) => request<void>(`/initiatives/${id}`, { method: 'DELETE' }),

	listDecisions: (params: { status?: string; area_id?: number; initiative_id?: number } = {}) =>
		request<DecisionOut[]>(`/decisions${qs(params)}`),
	createDecision: (body: { question: string; area_id?: number; options?: string[]; criteria?: string; deadline?: string }) =>
		request<DecisionOut>('/decisions', { method: 'POST', body: JSON.stringify(body) }),
	patchDecision: (id: number, body: Record<string, unknown>) =>
		request<DecisionOut>(`/decisions/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
	deleteDecision: (id: number) => request<void>(`/decisions/${id}`, { method: 'DELETE' }),

	listRules: (active?: boolean) =>
		request<AIRuleOut[]>(`/ai-rules${qs({ active: active === undefined ? undefined : String(active) })}`),
	createRule: (body: { rule: string; scope?: string; active?: boolean }) =>
		request<AIRuleOut>('/ai-rules', { method: 'POST', body: JSON.stringify(body) }),
	patchRule: (id: number, body: Record<string, unknown>) =>
		request<AIRuleOut>(`/ai-rules/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
	deleteRule: (id: number) => request<void>(`/ai-rules/${id}`, { method: 'DELETE' }),

	listPlans: (status?: string) =>
		request<PlanOut[]>(`/plans${qs({ status })}`),
	patchPlan: (id: number, body: Record<string, unknown>) =>
		request<PlanOut>(`/plans/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
	deletePlan: (id: number) => request<void>(`/plans/${id}`, { method: 'DELETE' })
};

// ---------- nutrition ----------

import type { DailyNutrition, FoodNutrition, NutritionGoals, NutritionHistory } from './types';

export const nutritionGoalsApi = {
	get: () => request<NutritionGoals>('/profile/nutrition-goals'),
	set: (body: Partial<Omit<NutritionGoals, 'source'>>) =>
		request<NutritionGoals>('/profile', { method: 'PATCH', body: JSON.stringify(body) })
};

export const nutritionApi = {
	estimate: (description: string, grams?: number) =>
		request<FoodNutrition>(`/nutrition/estimate`, {
			method: 'POST',
			body: JSON.stringify({ description, grams })
		}),
	daily: (date?: string) =>
		request<DailyNutrition>(`/nutrition/daily${qs({ date })}`),
	history: (days?: number) =>
		request<NutritionHistory>(`/nutrition/history${qs({ days })}`)
};

// ---------- chat ----------

import type { ChatResponse } from './types';

export const chatApi = {
	send: (session_id: string, message: string) =>
		request<ChatResponse>('/chat', {
			method: 'POST',
			body: JSON.stringify({ session_id, message })
		})
};

// ---------- F10 analytics ----------

import type { AllostaticLoad, ChangepointResult, LaggedCorrelation } from './types';

export const analyticsApi = {
	allostaticLoad: () =>
		request<AllostaticLoad>('/functions/analytics/allostatic_load'),
	changepoints: (metric: string, days?: number) =>
		request<ChangepointResult>(`/functions/analytics/changepoints${qs({ metric, days })}`),
	laggedCorrelation: (metric_a: string, metric_b: string, days?: number, max_lag?: number) =>
		request<LaggedCorrelation>(
			`/functions/analytics/lagged_correlation${qs({ metric_a, metric_b, days, max_lag })}`
		)
};

// ---------- research papers ----------

import type { ResearchPaper, ResearchPaperMeta } from './types';

export const researchApi = {
	list: (topic?: string) =>
		request<ResearchPaperMeta[]>(`/research/papers${topic ? qs({ topic }) : ''}`),
	get: (filename: string) =>
		request<ResearchPaper>(`/research/papers/${encodeURIComponent(filename)}`)
};

// ---------- alerts ----------

import type { AlertEventOut, AlertRuleOut } from './types';

export const alertsApi = {
	listRules: () => request<AlertRuleOut[]>('/alerts/rules'),
	createRule: (body: { metric_name: string; operator: string; threshold: number; label: string; cooldown_hours?: number }) =>
		request<AlertRuleOut>('/alerts/rules', { method: 'POST', body: JSON.stringify(body) }),
	patchRule: (id: number, body: Record<string, unknown>) =>
		request<AlertRuleOut>(`/alerts/rules/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
	deleteRule: (id: number) => request<void>(`/alerts/rules/${id}`, { method: 'DELETE' }),
	listEvents: (limit?: number) =>
		request<AlertEventOut[]>(`/alerts/events${qs({ limit })}`)
};

// ---------- reports (F7 weekly) ----------

export const reports = {
	latest: () => request<WeeklyReport>(`/reports/weekly/latest`),
	byWeek: (week: string) => request<WeeklyReport>(`/reports/weekly${qs({ week })}`),
	index: () => request<string[]>(`/reports/weekly/index`),
	generate: (week?: string) =>
		request<WeeklyReport>(`/reports/weekly/generate${qs({ week })}`, { method: 'POST' })
};
