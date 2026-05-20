// Lightweight toast queue using Svelte 5 runes.
//
// Import `toast` anywhere to push a transient message. The Toaster component
// (rendered once in +layout.svelte) reads `toast.items` reactively.

export type ToastKind = 'info' | 'error';

export interface ToastItem {
	id: number;
	kind: ToastKind;
	message: string;
}

let nextId = 1;

function createToaster() {
	const items = $state<ToastItem[]>([]);
	const timers = new Map<number, ReturnType<typeof setTimeout>>();

	function push(kind: ToastKind, message: string, ttlMs = 3000) {
		const id = nextId++;
		items.push({ id, kind, message });
		const t = setTimeout(() => dismiss(id), ttlMs);
		timers.set(id, t);
	}

	function dismiss(id: number) {
		const idx = items.findIndex((i) => i.id === id);
		if (idx >= 0) items.splice(idx, 1);
		const t = timers.get(id);
		if (t) {
			clearTimeout(t);
			timers.delete(id);
		}
	}

	return {
		get items() {
			return items;
		},
		info: (m: string) => push('info', m),
		error: (m: string) => push('error', m, 5000),
		dismiss
	};
}

export const toast = createToaster();
