<script lang="ts">
	let {
		label,
		value,
		unit,
		size = 'md',
		tone = 'default'
	}: {
		label: string;
		value: string | number;
		unit?: string;
		size?: 'sm' | 'md' | 'lg' | 'xl';
		tone?: 'default' | 'accent' | 'warn' | 'bad';
	} = $props();
</script>

<div class="stat size-{size} tone-{tone}">
	<span class="label">{label}</span>
	<span class="value">
		<span class="num">{value}</span>
		{#if unit}<span class="unit">{unit}</span>{/if}
	</span>
</div>

<style>
	.stat {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}
	.label {
		font-size: 10.5px;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--color-fg-dim);
		font-weight: 500;
	}
	.value {
		display: flex;
		align-items: baseline;
		gap: 5px;
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		color: var(--color-fg);
		line-height: 1;
	}
	.size-sm .num {
		font-size: 15px;
	}
	.size-md .num {
		font-size: 20px;
	}
	.size-lg .num {
		font-size: 26px;
	}
	.size-xl .num {
		font-size: 32px;
		letter-spacing: -0.02em;
	}
	.unit {
		font-size: 11px;
		color: var(--color-fg-dim);
		font-weight: 400;
	}
	.tone-accent .num {
		color: var(--color-accent);
	}
	.tone-warn .num {
		color: var(--color-warn);
	}
	.tone-bad .num {
		color: var(--color-bad);
	}
</style>
