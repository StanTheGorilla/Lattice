<script lang="ts">
	import { page } from '$app/state';
</script>

<div class="error">
	<div class="status">{page.status}</div>
	<div class="message">{page.error?.message ?? 'something went sideways'}</div>
	<a href="/" class="back">← back to today</a>
</div>

<style>
	.error {
		display: grid;
		place-items: center;
		gap: 12px;
		min-height: 60vh;
		font-family: var(--font-mono);
		color: var(--color-fg);
		text-align: center;
	}
	.status {
		font-size: 64px;
		letter-spacing: -0.02em;
		color: var(--color-fg);
		font-weight: 500;
	}
	.message {
		color: var(--color-fg-dim);
		font-size: 13px;
		letter-spacing: 0.04em;
		max-width: 48ch;
	}
	.back {
		color: var(--color-accent);
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.12em;
		margin-top: 8px;
		text-decoration: none;
	}
	.back:hover {
		color: var(--color-fg);
	}
</style>
