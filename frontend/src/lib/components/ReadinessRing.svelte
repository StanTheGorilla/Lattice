<script lang="ts">
	import type { ReadinessOutput } from '$lib/api/types';
	let {
		data,
		size = 140
	}: {
		data: ReadinessOutput | null;
		size?: number;
	} = $props();

	const STROKE = 5;
	const R = $derived((size - STROKE * 2) / 2);
	const CIRC = $derived(Math.PI * 2 * R);
	const dashOffset = $derived(
		data ? CIRC - (CIRC * Math.max(0, Math.min(100, data.score))) / 100 : CIRC
	);

	function categoryTone(c: string) {
		if (c === 'peak') return 'accent';
		if (c === 'solid') return 'ok';
		if (c === 'average') return 'neutral';
		if (c === 'low') return 'warn';
		return 'bad';
	}

	function strokeColor(c: string): string {
		switch (c) {
			case 'peak':
			case 'solid':
				return 'var(--color-accent)';
			case 'average':
				return 'var(--color-fg-mute)';
			case 'low':
				return 'var(--color-warn)';
			default:
				return 'var(--color-bad)';
		}
	}
</script>

<div class="wrap" style="--ring-size: {size}px;">
	<div class="gauge-wrap">
		<svg viewBox="0 0 {size} {size}" class="gauge">
			<circle class="track" cx={size / 2} cy={size / 2} r={R} stroke-width={STROKE}></circle>
			<circle
				class="arc"
				cx={size / 2}
				cy={size / 2}
				r={R}
				stroke-width={STROKE}
				stroke-dasharray={CIRC}
				stroke-dashoffset={dashOffset}
				style="stroke: {data ? strokeColor(data.category) : 'var(--color-fg-dim)'}"
			></circle>
		</svg>
		<div class="inner">
			<div class="num">{data?.score ?? '—'}</div>
			<div class="slash">/ 100</div>
		</div>
	</div>

	{#if data}
		<div class="meta-row">
			<span class="category tone-{categoryTone(data.category)}">{data.category}</span>
			{#if data.provisional}<span class="prov">provisional</span>{/if}
		</div>
	{/if}
</div>

<style>
	.wrap {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 12px;
		user-select: none;
	}
	.gauge-wrap {
		position: relative;
		width: var(--ring-size);
		height: var(--ring-size);
	}
	.gauge {
		width: 100%;
		height: 100%;
		transform: rotate(-90deg);
	}
	.track {
		stroke: var(--color-bg-3);
		fill: none;
	}
	.arc {
		fill: none;
		stroke-linecap: round;
		transition:
			stroke-dashoffset 500ms ease-out,
			stroke 200ms ease;
	}
	.inner {
		position: absolute;
		inset: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 2px;
	}
	.num {
		font-family: var(--font-mono);
		font-size: calc(var(--ring-size) * 0.34);
		font-variant-numeric: tabular-nums;
		color: var(--color-fg);
		font-weight: 500;
		letter-spacing: -0.03em;
		line-height: 1;
	}
	.slash {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--color-fg-dim);
		letter-spacing: 0.06em;
	}
	.meta-row {
		display: flex;
		align-items: center;
		gap: 10px;
		font-size: 11.5px;
	}
	.category {
		text-transform: uppercase;
		letter-spacing: 0.14em;
		font-family: var(--font-mono);
		font-weight: 600;
	}
	.tone-accent {
		color: var(--color-accent);
	}
	.tone-ok {
		color: var(--color-ok);
	}
	.tone-neutral {
		color: var(--color-fg);
	}
	.tone-warn {
		color: var(--color-warn);
	}
	.tone-bad {
		color: var(--color-bad);
	}
	.prov {
		color: var(--color-warn);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		font-size: 10px;
		font-family: var(--font-mono);
		border: 1px solid rgba(212, 177, 90, 0.35);
		background: var(--warn-12);
		padding: 1px 5px;
		border-radius: 3px;
	}
</style>
