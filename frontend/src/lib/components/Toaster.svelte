<script lang="ts">
	import { toast } from '$lib/toast.svelte';
</script>

<div class="stack" role="region" aria-label="notifications" aria-live="polite">
	{#each toast.items as t (t.id)}
		<button
			class="toast {t.kind}"
			onclick={() => toast.dismiss(t.id)}
			title="dismiss"
			type="button"
		>
			<span class="msg">{t.message}</span>
			<span class="x">×</span>
		</button>
	{/each}
</div>

<style>
	.stack {
		position: fixed;
		bottom: 16px;
		right: 16px;
		display: flex;
		flex-direction: column;
		gap: 6px;
		z-index: 100;
		pointer-events: none;
	}
	.toast {
		pointer-events: auto;
		display: flex;
		align-items: center;
		gap: 12px;
		min-width: 240px;
		max-width: 400px;
		padding: 10px 14px;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--r-md);
		background: var(--color-bg-2);
		color: var(--color-fg);
		font-size: 12.5px;
		cursor: pointer;
		text-align: left;
		box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
		animation: in 160ms ease-out;
	}
	.toast.error {
		border-color: rgba(201, 106, 106, 0.45);
		color: var(--color-bad);
		background: var(--bad-12);
	}
	.msg {
		flex: 1;
		word-break: break-word;
	}
	.x {
		color: var(--color-fg-faint);
		font-size: 14px;
		line-height: 1;
	}
	@keyframes in {
		from {
			opacity: 0;
			transform: translateY(4px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
</style>
