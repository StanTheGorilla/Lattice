<script lang="ts">
	import type { Snippet } from 'svelte';
	let {
		tone = 'neutral',
		size = 'sm',
		children
	}: {
		tone?: 'neutral' | 'ok' | 'warn' | 'bad' | 'accent';
		size?: 'sm' | 'md';
		children: Snippet;
	} = $props();
</script>

<span class="pill {tone} {size}">{@render children()}</span>

<style>
	.pill {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		letter-spacing: 0.04em;
		border: 1px solid var(--color-border);
		border-radius: 999px;
		color: var(--color-fg-mute);
		background: var(--color-bg-2);
		white-space: nowrap;
	}
	.sm {
		font-size: 10.5px;
		padding: 2px 8px;
	}
	.md {
		font-size: 11.5px;
		padding: 3px 10px;
	}
	.ok {
		color: var(--color-ok);
		border-color: rgba(109, 191, 122, 0.35);
		background: var(--ok-12);
	}
	.warn {
		color: var(--color-warn);
		border-color: rgba(212, 177, 90, 0.35);
		background: var(--warn-12);
	}
	.bad {
		color: var(--color-bad);
		border-color: rgba(201, 106, 106, 0.35);
		background: var(--bad-12);
	}
	.accent {
		color: var(--color-accent);
		border-color: rgba(93, 208, 200, 0.4);
		background: var(--accent-12);
	}
</style>
