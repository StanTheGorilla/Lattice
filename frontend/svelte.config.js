import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
		runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
	},
	kit: {
		// Static SPA build: served as plain files by the FastAPI backend.
		// fallback enables client-side routing for deep links (e.g. /trends).
		adapter: adapter({ fallback: 'index.html' })
	}
};

export default config;
