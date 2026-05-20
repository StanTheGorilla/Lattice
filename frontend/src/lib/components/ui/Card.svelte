<script lang="ts">
	import type { Snippet } from 'svelte';
	let {
		title,
		eyebrow,
		meta,
		padded = true,
		children
	}: {
		title?: string;
		eyebrow?: string;
		meta?: string;
		padded?: boolean;
		children: Snippet;
	} = $props();
</script>

<section class="card" class:padded>
	{#if eyebrow || title || meta}
		<header class="head">
			<div class="left">
				{#if eyebrow}<span class="eyebrow">{eyebrow}</span>{/if}
				{#if title}<h3>{title}</h3>{/if}
			</div>
			{#if meta}<span class="meta">{meta}</span>{/if}
		</header>
	{/if}
	{@render children()}
</section>

<style>
	.card {
		background: var(--color-bg-1);
		border: 1px solid var(--color-border);
		border-radius: var(--r-md);
		display: flex;
		flex-direction: column;
		gap: var(--s-4);
		transition: border-color 120ms ease;
	}
	.card.padded {
		padding: var(--s-5);
	}
	.card:hover {
		border-color: var(--color-border-strong);
	}
	.head {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: var(--s-3);
	}
	.left {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.eyebrow {
		font-size: 10.5px;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: var(--color-fg-dim);
		font-weight: 500;
	}
	h3 {
		font-size: 14px;
		font-weight: 600;
		margin: 0;
		color: var(--color-fg);
		letter-spacing: -0.005em;
	}
	.meta {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--color-fg-dim);
		font-variant-numeric: tabular-nums;
	}
</style>
