<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	let {
		series,
		labels,
		height = 180
	}: {
		series: { name: string; data: (number | null)[]; color?: string }[];
		labels: string[];
		height?: number;
	} = $props();

	let el: HTMLDivElement | undefined = $state();
	let chart: { setOption: (o: unknown) => void; resize: () => void; dispose: () => void } | null =
		null;

	$effect(() => {
		const opt = buildOption(series, labels);
		if (!chart) return;
		chart.setOption(opt);
	});

	function buildOption(
		ss: { name: string; data: (number | null)[]; color?: string }[],
		xs: string[]
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
				type: 'bar',
				data: s.data,
				barMaxWidth: 32,
				itemStyle: {
					color: s.color ?? '#5dd0c8',
					borderRadius: [3, 3, 0, 0]
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
			chart.setOption(buildOption(series, labels));
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
