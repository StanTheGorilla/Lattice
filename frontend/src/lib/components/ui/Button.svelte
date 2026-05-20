<script lang="ts">
	import type { Snippet } from 'svelte';
	let {
		variant = 'default',
		size = 'md',
		type = 'button',
		disabled = false,
		onclick,
		children
	}: {
		variant?: 'default' | 'primary' | 'ghost';
		size?: 'sm' | 'md';
		type?: 'button' | 'submit' | 'reset';
		disabled?: boolean;
		onclick?: (e: MouseEvent) => void;
		children: Snippet;
	} = $props();
</script>

<button class="btn {variant} size-{size}" {type} {disabled} {onclick}>
	{@render children()}
</button>

<style>
	.btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		color: var(--color-fg);
		background: var(--color-bg-2);
		font-weight: 500;
		cursor: pointer;
		transition: background 120ms, border-color 120ms;
	}
	.size-md {
		height: 32px;
		padding: 0 14px;
		font-size: 12.5px;
	}
	.size-sm {
		height: 26px;
		padding: 0 10px;
		font-size: 11.5px;
	}
	.btn:hover:not(:disabled) {
		background: var(--color-bg-3);
		border-color: var(--color-border-strong);
	}
	.primary {
		background: var(--color-accent);
		color: #062927;
		border-color: var(--color-accent);
		font-weight: 600;
	}
	.primary:hover:not(:disabled) {
		background: #74d8d1;
		border-color: #74d8d1;
	}
	.ghost {
		border-color: transparent;
		background: transparent;
		color: var(--color-fg-mute);
	}
	.ghost:hover:not(:disabled) {
		background: var(--color-bg-2);
		border-color: var(--color-border);
		color: var(--color-fg);
	}
	.btn:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
</style>
