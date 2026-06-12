<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/api/client';

	let password = $state('');
	let error = $state('');
	let submitting = $state(false);

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		if (submitting) return;
		submitting = true;
		error = '';
		try {
			await auth.login(password);
			await goto('/');
		} catch (err) {
			const msg = err instanceof Error ? err.message : String(err);
			error = msg.includes('bad_password') ? 'Incorrect password.' : 'Login failed: ' + msg;
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>Lattice · Sign in</title>
</svelte:head>

<div class="page">
	<div class="box">
		<div class="brand">
			<span class="wordmark">LATTICE</span>
			<span class="sub">personal optimization</span>
		</div>

		<form onsubmit={submit}>
			<label class="field">
				<span class="label">Password</span>
				<input
					id="pw"
					class="input"
					type="password"
					placeholder="••••••••"
					autocomplete="current-password"
					bind:value={password}
					disabled={submitting}
				/>
			</label>
			{#if error}
				<div class="err">{error}</div>
			{/if}
			<button class="btn primary" type="submit" disabled={submitting}>
				{submitting ? 'Signing in…' : 'Sign in'}
			</button>
		</form>

		<div class="foot">POST /api/auth/login · cookie · 30d</div>
	</div>
</div>

<style>
	.page {
		position: relative;
		z-index: 1;
		min-height: 100vh;
		display: grid;
		place-items: center;
		background: var(--color-bg-0);
	}
	.box {
		width: 360px;
		padding: 36px 32px 28px;
		background: var(--color-bg-1);
		border: 1px solid var(--color-border);
		border-radius: var(--r-lg);
		box-shadow: var(--shadow-lg);
		animation: fade-up var(--t-med) var(--ease) both;
	}
	.brand {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
		margin-bottom: 28px;
	}
	.wordmark {
		font-family: var(--font-mono);
		font-size: 20px;
		letter-spacing: 0.16em;
		color: var(--color-fg);
		font-weight: 600;
	}
	.sub {
		font-size: 11px;
		color: var(--color-fg-dim);
		text-transform: uppercase;
		letter-spacing: 0.16em;
	}
	form {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.label {
		font-size: 11px;
		color: var(--color-fg-mute);
		text-transform: uppercase;
		letter-spacing: 0.12em;
		font-weight: 500;
	}
	.input {
		height: 36px;
		padding: 0 12px;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		background: var(--color-bg-2);
		color: var(--color-fg);
		font-size: 13px;
		line-height: 1;
		outline: none;
		transition: border-color 120ms, background 120ms;
	}
	.input:focus {
		border-color: var(--color-accent);
		background: var(--color-bg-1);
		box-shadow: var(--ring);
	}
	.input::placeholder {
		color: var(--color-fg-dim);
	}
	.err {
		padding: 8px 12px;
		border-radius: var(--r-sm);
		background: var(--bad-12);
		color: var(--color-bad);
		font-size: 12px;
		border: 1px solid rgba(201, 106, 106, 0.3);
	}
	.btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		height: 38px;
		padding: 0 14px;
		border: 1px solid var(--color-border);
		border-radius: var(--r-sm);
		font-size: 13px;
		color: var(--color-fg);
		background: var(--color-bg-2);
		font-weight: 500;
		cursor: pointer;
		transition: background 120ms;
	}
	.btn.primary {
		background: var(--color-accent);
		color: #062927;
		border-color: var(--color-accent);
		font-weight: 600;
	}
	.btn.primary:hover:not(:disabled) {
		background: #74d8d1;
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.foot {
		margin-top: 24px;
		text-align: center;
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--color-fg-dim);
		letter-spacing: 0.04em;
	}
</style>
