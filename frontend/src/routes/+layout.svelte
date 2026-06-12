<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	import { auth } from '$lib/api/client';
	import SyncPill from '$lib/components/SyncPill.svelte';
	import Toaster from '$lib/components/Toaster.svelte';

	let { children } = $props();

	if (typeof window !== 'undefined' && 'serviceWorker' in navigator) {
		navigator.serviceWorker.register('/sw.js').catch(() => {});
	}

	const NAV = [
		{ href: '/', label: 'Today', key: 'T', section: 'primary' },
		{ href: '/trends', label: 'Trends', key: 'R', section: 'primary' },
		{ href: '/log', label: 'Log', key: 'L', section: 'primary' },
		{ href: '/habits', label: 'Habits', key: 'H', section: 'primary' },
		{ href: '/routines', label: 'Routines', key: 'O', section: 'primary' },
		{ href: '/chat', label: 'Chat', key: 'C', section: 'primary' },
		{ href: '/report', label: 'Report', key: 'W', section: 'more' },
		{ href: '/protocol', label: 'Protocol', key: 'P', section: 'more' },
		{ href: '/research', label: 'Research', key: 'E', section: 'more' },
		{ href: '/memory', label: 'Memory', key: 'M', section: 'more' },
		{ href: '/algorithms', label: 'Algorithms', key: 'A', section: 'more' },
		{ href: '/alerts', label: 'Alerts', key: 'N', section: 'more' },
		{ href: '/settings', label: 'Settings', key: 'S', section: 'more' }
	];

	const NAV_PRIMARY = NAV.filter((n) => n.section === 'primary');
	const NAV_MORE = NAV.filter((n) => n.section === 'more');

	let authChecked = $state(false);
	let permissive = $state(false);
	let mobileNavOpen = $state(false);

	const isLogin = $derived(page.url.pathname.startsWith('/login'));

	function isTypingTarget(t: EventTarget | null): boolean {
		if (!(t instanceof HTMLElement)) return false;
		if (t.isContentEditable) return true;
		const tag = t.tagName;
		return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
	}

	function onKeydown(e: KeyboardEvent) {
		if (isLogin || !authChecked) return;
		if (e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;
		if (isTypingTarget(e.target)) return;
		const match = NAV.find((n) => n.key.toLowerCase() === e.key.toLowerCase());
		if (!match) return;
		e.preventDefault();
		goto(match.href);
	}

	onMount(async () => {
		if (isLogin) {
			authChecked = true;
			return;
		}
		try {
			const s = await auth.status();
			if (!s.authenticated) {
				await goto('/login');
				return;
			}
			permissive = s.permissive;
		} catch (e) {
			console.warn('auth status failed', e);
			await goto('/login');
			return;
		}
		authChecked = true;
	});

	async function logout() {
		try {
			await auth.logout();
		} catch (e) {
			console.warn('logout failed', e);
		}
		await goto('/login');
	}
</script>

<svelte:window onkeydown={onKeydown} />

{#if isLogin}
	{@render children()}
{:else if !authChecked}
	<div class="loading">
		<span>checking session…</span>
	</div>
{:else}
	<div class="app">
		<aside class="sidebar">
			<div class="brand">
				<span class="wordmark">LATTICE</span>
				<span class="tag">v1</span>
			</div>

			<nav class="nav">
				{#each NAV_PRIMARY as item (item.href)}
					<a
						class="nav-item"
						class:active={page.url.pathname === item.href ||
							(item.href !== '/' && page.url.pathname.startsWith(item.href))}
						href={item.href}
					>
						<span class="nav-label">{item.label}</span>
						<span class="nav-key">{item.key}</span>
					</a>
				{/each}
				<div class="nav-divider">More</div>
				{#each NAV_MORE as item (item.href)}
					<a
						class="nav-item"
						class:active={page.url.pathname === item.href ||
							(item.href !== '/' && page.url.pathname.startsWith(item.href))}
						href={item.href}
					>
						<span class="nav-label">{item.label}</span>
						<span class="nav-key">{item.key}</span>
					</a>
				{/each}
			</nav>

			<div class="sidebar-spacer"></div>

			<SyncPill />

			<div class="user-row">
				<span class="av">S</span>
				<span class="nm">stan</span>
				{#if permissive}<span class="badge">dev</span>{/if}
				<button class="logout" onclick={logout}>logout</button>
			</div>
		</aside>

		<!-- Mobile top bar -->
		<div class="mobile-bar">
			<span class="wordmark">LATTICE</span>
			<button class="mobile-menu-btn" onclick={() => { mobileNavOpen = !mobileNavOpen; }} aria-label="Menu">
				{mobileNavOpen ? '✕' : '☰'}
			</button>
		</div>

		<!-- Mobile nav drawer -->
		{#if mobileNavOpen}
			<div
				class="mobile-overlay"
				onclick={() => { mobileNavOpen = false; }}
				role="presentation"
				transition:fade={{ duration: 160 }}
			></div>
			<nav class="mobile-drawer" transition:fly={{ x: 280, duration: 240, opacity: 1 }}>
				{#each NAV_PRIMARY as item (item.href)}
					<a
						class="nav-item"
						class:active={page.url.pathname === item.href ||
							(item.href !== '/' && page.url.pathname.startsWith(item.href))}
						href={item.href}
						onclick={() => { mobileNavOpen = false; }}
					>
						<span class="nav-label">{item.label}</span>
						<span class="nav-key">{item.key}</span>
					</a>
				{/each}
				<div class="nav-divider">More</div>
				{#each NAV_MORE as item (item.href)}
					<a
						class="nav-item"
						class:active={page.url.pathname === item.href ||
							(item.href !== '/' && page.url.pathname.startsWith(item.href))}
						href={item.href}
						onclick={() => { mobileNavOpen = false; }}
					>
						<span class="nav-label">{item.label}</span>
						<span class="nav-key">{item.key}</span>
					</a>
				{/each}
				<div class="mobile-drawer-footer">
					{#if permissive}<span class="badge">dev</span>{/if}
					<button class="logout" onclick={logout}>logout</button>
				</div>
			</nav>
		{/if}

		<main>
			{#key page.url.pathname}
				<div class="container page-enter">
					{@render children()}
				</div>
			{/key}
		</main>
	</div>
{/if}

<Toaster />

<style>
	.loading {
		display: grid;
		place-items: center;
		min-height: 100vh;
		color: var(--color-fg-dim);
		font-family: var(--font-mono);
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.12em;
	}
	.app {
		display: grid;
		grid-template-columns: 220px 1fr;
		min-height: 100vh;
		position: relative;
		z-index: 1;
	}
	.sidebar {
		border-right: 1px solid var(--color-border);
		background: var(--color-bg-0);
		position: sticky;
		top: 0;
		height: 100vh;
		display: flex;
		flex-direction: column;
		padding: 22px 0 0;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 0 22px 22px;
		font-family: var(--font-mono);
		font-size: 13px;
		letter-spacing: 0.16em;
	}
	.wordmark {
		color: var(--color-fg);
		font-weight: 600;
	}
	.tag {
		color: var(--color-fg-dim);
		font-size: 10.5px;
		margin-left: auto;
		font-weight: 400;
	}
	.nav {
		display: flex;
		flex-direction: column;
		padding: 0 12px;
		gap: 2px;
	}
	.nav-divider {
		font-family: var(--font-mono);
		font-size: 9.5px;
		text-transform: uppercase;
		letter-spacing: 0.14em;
		color: var(--color-fg-faint);
		padding: 14px 12px 6px;
		margin-top: 4px;
		border-top: 1px solid var(--color-border);
	}
	.nav-item {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 9px 12px;
		border-radius: var(--r-sm);
		color: var(--color-fg-mute);
		font-size: 13px;
		font-weight: 500;
		position: relative;
		cursor: pointer;
		user-select: none;
		transition: background 120ms, color 120ms;
	}
	.nav-label {
		flex: 1;
	}
	.nav-item:hover {
		color: var(--color-fg);
		background: var(--color-bg-1);
	}
	.nav-item.active {
		color: var(--color-fg);
		background: var(--color-bg-2);
	}
	.nav-item.active::before {
		content: '';
		position: absolute;
		left: -12px;
		top: 8px;
		bottom: 8px;
		width: 2px;
		background: var(--color-accent);
		border-radius: 0 2px 2px 0;
	}
	.nav-item.active .nav-key {
		color: var(--color-accent);
		border-color: rgba(93, 208, 200, 0.3);
		background: var(--accent-12);
	}
	.nav-key {
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--color-fg-faint);
		border: 1px solid var(--color-border);
		padding: 1px 6px;
		border-radius: 3px;
		min-width: 18px;
		text-align: center;
		line-height: 1.2;
		transition: color 120ms, background 120ms, border-color 120ms;
	}
	.sidebar-spacer {
		flex: 1;
	}
	.user-row {
		padding: 14px 20px;
		display: flex;
		align-items: center;
		gap: 10px;
		border-top: 1px solid var(--color-border);
		font-size: 12px;
	}
	.av {
		width: 24px;
		height: 24px;
		border: 1px solid var(--color-border);
		background: var(--color-bg-2);
		border-radius: 50%;
		display: grid;
		place-items: center;
		font-size: 10.5px;
		font-family: var(--font-mono);
		color: var(--color-fg-mute);
	}
	.nm {
		color: var(--color-fg);
		font-weight: 500;
	}
	.badge {
		font-family: var(--font-mono);
		font-size: 9.5px;
		text-transform: uppercase;
		color: var(--color-warn);
		border: 1px solid rgba(212, 177, 90, 0.4);
		background: var(--warn-12);
		padding: 1px 5px;
		border-radius: 3px;
		letter-spacing: 0.08em;
	}
	.logout {
		margin-left: auto;
		color: var(--color-fg-dim);
		font-size: 11.5px;
		background: none;
		border: 0;
		padding: 0;
		cursor: pointer;
		transition: color 120ms;
	}
	.logout:hover {
		color: var(--color-fg);
	}
	main {
		min-width: 0;
		padding: 28px 40px 64px;
	}
	.container {
		max-width: 1400px;
		margin: 0 auto;
	}
	.page-enter {
		animation: fade-up var(--t-med) var(--ease) both;
	}
	@media (max-width: 900px) {
		main {
			padding: 24px 24px 48px;
		}
	}

	/* ── Mobile layout (≤720px) ── */
	.mobile-bar {
		display: none;
	}
	.mobile-overlay {
		display: none;
	}
	.mobile-drawer {
		display: none;
	}
	@media (max-width: 720px) {
		.app {
			grid-template-columns: 1fr;
		}
		.sidebar {
			display: none;
		}
		.mobile-bar {
			display: flex;
			align-items: center;
			justify-content: space-between;
			padding: 12px 18px;
			background: var(--color-bg-0);
			border-bottom: 1px solid var(--color-border);
			position: sticky;
			top: 0;
			z-index: 100;
			font-family: var(--font-mono);
			font-size: 13px;
			letter-spacing: 0.14em;
		}
		.mobile-menu-btn {
			font-size: 18px;
			color: var(--color-fg-mute);
			background: none;
			border: 0;
			padding: 4px 8px;
			cursor: pointer;
		}
		.mobile-overlay {
			display: block;
			position: fixed;
			inset: 0;
			background: rgba(0, 0, 0, 0.6);
			z-index: 110;
		}
		.mobile-drawer {
			display: flex;
			flex-direction: column;
			position: fixed;
			top: 0;
			right: 0;
			bottom: 0;
			width: min(280px, 85vw);
			background: var(--color-bg-1);
			border-left: 1px solid var(--color-border);
			z-index: 120;
			padding: 56px 12px 24px;
			overflow-y: auto;
		}
		.mobile-drawer-footer {
			margin-top: auto;
			padding-top: 16px;
			display: flex;
			align-items: center;
			gap: 10px;
		}
		main {
			padding: 16px 16px 80px;
		}
	}
</style>
