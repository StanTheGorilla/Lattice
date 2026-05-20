<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	let {
		series,
		labels,
		yMin,
		yMax,
		height = 180
	}: {
		series: { name: string; data: (number | null)[]; color?: string }[];
		labels: string[];
		yMin?: number;
		yMax?: number;
		height?: number;
	} = $props();

	let el: HTMLDivElement | undefined = $state();
	let chart: { setOption: (o: unknown) => void; resize: () => void; dispose: () => void } | null =
		null;

	$effect(() => {
		// Read reactive deps first so Svelte tracks them regardless of chart state.
		const opt = buildOption(series, labels, yMin, yMax);
		if (!chart) return;
		chart.setOption(opt);
	});

	function buildOption(
		ss: { name: string; data: (number | null)[]; color?: string }[],
		xs: string[],
		yLo?: number,
		yHi?: number
	) {
		return {
			grid: { left: 36, right: 12, top: 14, bottom: 28 },
			backgroundColor: 'transparent',
			tooltip: {
				trigger: 'axis',
				backgroundColor: '#17171c',
				borderColor: '#24242b',
				borderWidth: 1,
				textStyle: { color: '#e8e8ed', fontSize: 11 }
			},
			xAxis: {
				type: 'category',
				data: xs,
				axisLine: { lineStyle: { color: '#24242b' } },
				axisLabel: {
					color: '#5e5e68',
					fontSize: 10,
					fontFamily: 'JetBrains Mono, monospace'
				}
			},
			yAxis: {
				type: 'value',
				min: yLo,
				max: yHi,
				axisLine: { show: false },
				splitLine: { lineStyle: { color: '#1b1b21' } },
				axisLabel: {
					color: '#5e5e68',
					fontSize: 10,
					fontFamily: 'JetBrains Mono, monospace'
				}
			},
			series: ss.map((s) => ({
				name: s.name,
				type: 'line',
				data: s.data,
				showSymbol: false,
				smooth: true,
				lineStyle: { width: 1.5, color: s.color ?? '#5dd0c8' },
				itemStyle: { color: s.color ?? '#5dd0c8' },
				areaStyle: {
					color: {
						type: 'linear',
						x: 0,
						y: 0,
						x2: 0,
						y2: 1,
						colorStops: [
							{ offset: 0, color: (s.color ?? '#5dd0c8') + '40' },
							{ offset: 1, color: 'transparent' }
						]
					}
				}
			}))
		};
	}

	let ro: ResizeObserver | null = null;

	onMount(() => {
		void (async () => {
			if (!el) return;
			const echarts = await import('echarts');
			chart = echarts.init(el, undefined, { renderer: 'canvas' });
			chart.setOption(buildOption(series, labels, yMin, yMax));
			ro = new ResizeObserver(() => chart?.resize());
			ro.observe(el);
		})();
	});

	onDestroy(() => {
		ro?.disconnect();
		chart?.dispose();
		chart = null;
	});
</script>

<div bind:this={el} class="chart" style="height: {height}px;"></div>

<style>
	.chart {
		width: 100%;
	}
</style>
