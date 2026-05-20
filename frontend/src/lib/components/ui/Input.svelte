<script lang="ts">
	let {
		value = $bindable(''),
		type = 'text',
		placeholder,
		disabled = false,
		id,
		min,
		max,
		step
	}: {
		value?: string | number;
		type?: string;
		placeholder?: string;
		disabled?: boolean;
		id?: string;
		min?: number | string;
		max?: number | string;
		step?: number | string;
	} = $props();
</script>

<input
	class="input"
	{id}
	{type}
	{placeholder}
	{disabled}
	{min}
	{max}
	{step}
	bind:value
/>

<style>
	.input {
		height: 34px;
		padding: 0 12px;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		background: var(--color-bg-2);
		color: var(--color-fg);
		font-size: 13px;
		line-height: 1;
		outline: none;
		transition: border-color 120ms;
		width: 100%;
	}
	.input:focus {
		border-color: var(--color-accent);
		background: var(--color-bg-1);
	}
	.input::placeholder {
		color: var(--color-fg-dim);
	}
	.input:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
