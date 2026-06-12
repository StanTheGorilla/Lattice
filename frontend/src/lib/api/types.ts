// Lattice API types — mirror backend Pydantic schemas (SPEC §5).

export type EntryType =
	| 'food'
	| 'drink'
	| 'mood'
	| 'energy'
	| 'focus'
	| 'symptom'
	| 'note'
	| 'workout_manual';

export interface Entry {
	id: number;
	timestamp: string;
	logged_at: string;
	type: EntryType;
	data: Record<string, unknown>;
	source: string;
}

export interface EntryListResponse {
	items: Entry[];
	total: number;
}

export interface EntryMarker {
	label: string;
	value: string;
	sentiment: 'good' | 'neutral' | 'bad' | 'info';
}

export interface EntryMarkers {
	entry_id: number;
	type: string;
	timestamp: string;
	markers: EntryMarker[];
}

export interface Metric {
	id: number;
	timestamp: string;
	metric_name: string;
	value: number;
	unit: string | null;
	source: string;
	metadata: string | null;
}

export interface MetricListResponse {
	items: Metric[];
	total: number;
}

export interface MetricsLatestResponse {
	items: Record<string, Metric | null>;
}

export interface BaselineResponse {
	name: string;
	mean: number | null;
	sd: number | null;
	n: number;
	window_days: number;
}

export interface CalendarEvent {
	id: number;
	google_event_id: string;
	start: string;
	end: string;
	title: string;
	description: string | null;
	location: string | null;
	is_all_day: boolean;
	fetched_at: string;
}

export interface HabitDefinition {
	id: number;
	name: string;
	target_per_week: number;
	active: boolean;
	created_at: string;
}

export interface HabitCheckin {
	id: number;
	habit_id: number;
	date: string;
	completed: boolean;
	note: string | null;
}

// Functions

export type ReadinessCategory = 'peak' | 'solid' | 'average' | 'low' | 'depleted';

export interface ReadinessExplanation {
	weights_used: Record<string, number>;
	missing: string[];
	components: Record<string, number>;
	notes: string[];
}

export interface ReadinessOutput {
	date: string;
	score: number;
	category: ReadinessCategory;
	provisional: boolean;
	explanation: ReadinessExplanation;
}

export interface WorkWindow {
	start: string;
	end: string;
	duration_minutes: number;
	predicted_focus: number;
	rationale: string[];
}

export interface WorkWindowsOutput {
	date: string;
	min_minutes: number;
	windows: WorkWindow[];
	peak_focus_hour: number | null;
	confidence_hint: 'low' | 'medium' | 'high';
}

export type TrainingRec = 'rest' | 'easy' | 'moderate' | 'hard';

export interface TrainingRecOutput {
	date: string;
	recommendation: TrainingRec;
	confidence: number;
	rationale: string[];
	inputs: Record<string, number | string | null>;
}

export type RecommendationSource = 'ai' | 'formula';

export interface SleepWindowOutput {
	date: string;
	bedtime: string;
	wake_time: string;
	target_duration_min: number;
	flags: string[];
	inputs: Record<string, string | number | null>;
	source: RecommendationSource;
	rationale: string | null;
	author: string | null;
}

export interface CaffeineStatusOutput {
	at: string;
	bedtime: string;
	residual_at_bedtime_mg: number;
	safe_for_new_cup: boolean;
	last_call_minutes: number | null;
	inputs: Record<string, number | string | null>;
}

export type AdvisorIntent =
	| 'learn'
	| 'train'
	| 'rest'
	| 'creative'
	| 'meeting'
	| 'physical_task';

export interface AdvisorOutput {
	intent: AdvisorIntent;
	recommendation: string;
	confidence: number;
	window: WorkWindow | null;
	reasons: string[];
	alternatives: WorkWindow[];
}

export interface HabitAdherence {
	habit_id: number;
	name: string;
	target_per_week: number;
	current_streak_days: number;
	longest_streak_days: number;
	week_completion_pct: number;
	period_completion_pct: number;
}

export interface HabitAdherenceOutput {
	from: string;
	to: string;
	items: HabitAdherence[];
}

export interface AuthStatus {
	authenticated: boolean;
	permissive: boolean;
}

export interface ApiError {
	error: string;
	message: string;
	details?: unknown;
}

// ---------- F7 weekly report ----------

export interface DailyAggregate {
	date: string;
	readiness: number | null;
	sleep_score: number | null;
	sleep_duration_min: number | null;
	hrv_overnight_avg: number | null;
	resting_hr: number | null;
	stress_avg: number | null;
}

export interface BestWorstDay {
	date: string;
	readiness: number;
	reason: string;
}

export interface HabitWeekStat {
	habit_id: number;
	name: string;
	target_per_week: number;
	completed_this_week: number;
	week_completion_pct: number;
	current_streak_days: number;
}

export interface Correlation {
	label: string;
	r: number;
	n: number;
	direction: 'positive' | 'negative';
}

export interface MeanShift {
	metric: string;
	this_week_mean: number;
	trailing_mean: number;
	trailing_sd: number;
	delta_sd: number;
	direction: 'up' | 'down';
}

export interface WeeklyStats {
	iso_week: string;
	week_start: string;
	week_end: string;
	daily: DailyAggregate[];
	averages: Record<string, number | null>;
	best_day: BestWorstDay | null;
	worst_day: BestWorstDay | null;
	habits: HabitWeekStat[];
	correlations: Correlation[];
	mean_shifts: MeanShift[];
	coverage_notes: string[];
}

export interface WeeklyReport {
	id: number;
	iso_week: string;
	generated_at: string;
	model_used: string;
	stats: WeeklyStats;
	summary_text: string;
}

// ---------- planning system ----------

export interface ProfileOut {
	id: number;
	display_name: string | null;
	birthday: string | null;
	sex_at_birth: string | null;
	height_cm: number | null;
	weight_kg: number | null;
	chronotype: string | null;
	work_pattern: string | null;
	health_flags: string | null;
	target_sleep_min: number | null;
	target_wake_time: string | null;
	caffeine_cutoff_hour: number | null;
	last_meal_cutoff_hour: number | null;
	screen_off_hour: number | null;
	calorie_goal: number | null;
	protein_g_goal: number | null;
	carbs_g_goal: number | null;
	fat_g_goal: number | null;
	fiber_g_goal: number | null;
	sugar_g_goal: number | null;
	updated_at: string | null;
	age: number | null;
}

export interface NutritionGoals {
	calorie_goal: number;
	protein_g_goal: number;
	carbs_g_goal: number;
	fat_g_goal: number;
	fiber_g_goal: number;
	sugar_g_goal: number;
	source: 'set' | 'suggested' | 'default';
}

export interface AreaOut {
	id: number;
	key: string;
	name: string;
	description: string | null;
	color: string | null;
	sort_order: number;
	archived: boolean;
	created_at: string;
}

export type InitiativeStatus = 'active' | 'paused' | 'completed' | 'abandoned';

export interface InitiativeOut {
	id: number;
	area_id: number;
	title: string;
	why: string | null;
	target_outcome: string | null;
	target_metric: string | null;
	target_value: number | null;
	target_date: string | null;
	status: InitiativeStatus;
	review_at: string | null;
	created_at: string;
	closed_at: string | null;
	outcome_note: string | null;
}

export type DecisionStatus = 'open' | 'decided' | 'reviewed' | 'abandoned';

export interface DecisionOut {
	id: number;
	question: string;
	area_id: number | null;
	initiative_id: number | null;
	options: string[] | null;
	criteria: string | null;
	deadline: string | null;
	decided_at: string | null;
	decision: string | null;
	reasoning: string | null;
	confidence: number | null;
	review_at: string | null;
	reviewed_at: string | null;
	outcome: string | null;
	outcome_rating: number | null;
	status: DecisionStatus;
	created_at: string;
}

export interface AIRuleOut {
	id: number;
	rule: string;
	scope: string;
	scope_id: number | null;
	active: boolean;
	created_at: string;
}

// ---------- nutrition ----------

export interface FoodNutrition {
	calories: number | null;
	protein_g: number | null;
	carbs_g: number | null;
	fat_g: number | null;
	fiber_g: number | null;
	sugar_g: number | null;
	estimated_grams: number | null;
	confidence: 'high' | 'medium' | 'low' | null;
	notes: string | null;
}

export interface NutritionDayPoint {
	date: string;
	calories: number;
	protein_g: number;
	carbs_g: number;
	fat_g: number;
	fiber_g: number;
	sugar_g: number;
}

export interface NutritionHistory {
	days: number;
	series: NutritionDayPoint[];
}

export interface DailyNutrition {
	date: string;
	meals_logged: number;
	has_nutrition: boolean;
	totals: {
		calories: number;
		protein_g: number;
		carbs_g: number;
		fat_g: number;
		fiber_g: number;
		sugar_g: number;
	};
	meals: Array<{
		id: number;
		timestamp: string;
		description: string;
		meal_type: string | null;
		grams: number | null;
		nutrition: FoodNutrition | null;
	}>;
}

// ---------- chat ----------

export interface ChatMessage {
	role: 'user' | 'assistant';
	content: string;
}

export interface ToolCallSummary {
	name: string;
	arguments: Record<string, unknown>;
	result: Record<string, unknown>;
	ok: boolean;
}

export interface ChatResponse {
	session_id: string;
	reply: string;
	tool_calls: ToolCallSummary[];
	actions_taken: string[];
	finish_reason: string;
}

// ---------- dashboard cards (Phase 2L-c) ----------

export interface DashboardSeriesSpec {
	name: string;
	metric?: string;
	value?: number;
	color?: string;
}

export type DashboardChartType = 'line' | 'bar' | 'table';

export interface ResolvedLineBar {
	chart_type: 'line' | 'bar';
	labels: string[];
	series: { name: string; data: (number | null)[]; color?: string }[];
}

export interface ResolvedTable {
	chart_type: 'table';
	columns: string[];
	rows: (string | number | null)[][];
}

export type ResolvedChart = ResolvedLineBar | ResolvedTable;

export interface DashboardCard {
	id: number;
	title: string;
	chart_type: DashboardChartType;
	position: number;
	created_at: string;
	data_source: Record<string, unknown>;
	resolved: ResolvedChart;
}

export interface DashboardCardListResponse {
	items: DashboardCard[];
}

// ---------- algorithms (Phase 2L-a) ----------

export interface AlgorithmRow {
	id: number;
	name: string;
	description: string;
	data_requirements: Record<string, unknown>;
	created_at: string;
	updated_at: string;
}

// ---------- F10 analytics ----------

export interface AllostaticLoadComponent {
	label: string;
	marker: string;
	recent_mean: number | null;
	flag: boolean;
	direction: string;
}

export interface AllostaticLoad {
	score: number;
	max_score: number;
	category: 'low' | 'moderate' | 'high' | 'very high';
	components: AllostaticLoadComponent[];
	interpretation: string;
	low_confidence: boolean;
}

export interface Changepoint {
	date: string;
	direction: 'up' | 'down';
	magnitude: number;
	z_score: number;
	recent_mean: number;
	baseline_mean: number;
}

export interface ChangepointResult {
	metric_name: string;
	days: number;
	changepoints: Changepoint[];
	n_points: number;
}

export interface LagResult {
	lag: number;
	r: number | null;
	n: number;
}

export interface LaggedCorrelation {
	metric_a: string;
	metric_b: string;
	days: number;
	lags: LagResult[];
	peak_lag: number | null;
	peak_r: number | null;
	interpretation: string;
}

// ---------- research papers ----------

export interface ResearchPaperMeta {
	filename: string;
	title: string;
	topic: string;
	date: string;
	sources: string[];
}

export interface ResearchPaper extends ResearchPaperMeta {
	content: string;
}

// ---------- alerts ----------

export interface AlertRuleOut {
	id: number;
	metric_name: string;
	operator: 'lt' | 'lte' | 'gt' | 'gte';
	threshold: number;
	label: string;
	cooldown_hours: number;
	active: boolean;
	created_at: string;
}

export interface AlertEventOut {
	id: number;
	rule_id: number;
	fired_at: string;
	value: number;
}

export type PlanStatus = 'active' | 'completed' | 'abandoned';

export interface PlanOut {
	id: number;
	goal: string;
	plan: string;
	metric: string | null;
	target_value: number | null;
	target_date: string | null;
	status: PlanStatus;
	progress_note: string | null;
	created_at: string;
	closed_at: string | null;
}

export interface Memory {
	id: number;
	content: string;
	created_at: string;
	updated_at: string;
}

export interface MemoryListResponse {
	items: Memory[];
	total: number;
}

// ---------- routines (Phase B) ----------

export type RoutineType = 'ai_review' | 'reminder';
export type Chattiness = 'always' | 'only_notable';

export interface Routine {
	id: number;
	name: string;
	type: RoutineType;
	hour: number;
	minute: number;
	weekday_mask: number;
	instruction: string | null;
	chattiness: Chattiness;
	reminder_text: string | null;
	enabled: boolean;
	last_run_at: string | null;
	created_at: string;
}

export interface RoutineInput {
	name: string;
	type: RoutineType;
	hour: number;
	minute: number;
	weekday_mask: number;
	instruction?: string | null;
	chattiness: Chattiness;
	reminder_text?: string | null;
	enabled: boolean;
}

export interface RoutineListResponse {
	items: Routine[];
	total: number;
}

// ---------- routine run history (P3-2) ----------

export interface RoutineRun {
	id: number;
	routine_id: number;
	fired_at: string;
	sent: boolean;
	suppressed: boolean;
	reply_excerpt: string | null;
	detail: string | null;
}

export interface RoutineRunListResponse {
	items: RoutineRun[];
}

// ---------- LLM observability (P3-1) ----------

export interface LlmUsageDay {
	date: string;
	input_tokens: number;
	output_tokens: number;
	total_tokens: number;
	est_cost_usd: number;
}

export interface LlmUsageSummary {
	days: LlmUsageDay[];
	totals: {
		input_tokens: number;
		output_tokens: number;
		total_tokens: number;
		est_cost_usd: number;
	};
	window_days: number;
	input_usd_per_mtok: number;
	output_usd_per_mtok: number;
}
