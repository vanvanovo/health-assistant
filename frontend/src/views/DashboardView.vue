<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { fetchOverview, fetchTrends } from '@/api'

const overview = ref<any>({})
const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

function isoDaysAgo(n: number) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

function num(v: any): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

onMounted(async () => {
  overview.value = await fetchOverview()
  const trends = await fetchTrends(isoDaysAgo(29), isoDaysAgo(0))
  chart = echarts.init(chartRef.value!)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['体重(kg)', '训练(分钟)', '睡眠(h)'] },
    grid: { left: 50, right: 50, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: trends.series.map((s) => s.date) },
    yAxis: [
      { type: 'value', name: 'kg/分钟' },
      { type: 'value', name: '小时', max: 12 },
    ],
    series: [
      { name: '体重(kg)', type: 'line', smooth: true, data: trends.series.map((s) => s.weight_kg) },
      { name: '训练(分钟)', type: 'bar', data: trends.series.map((s) => s.workout_minutes) },
      { name: '睡眠(h)', type: 'line', yAxisIndex: 1, data: trends.series.map((s) => s.sleep_hours) },
    ],
  })
  window.addEventListener('resize', resize)
})

function resize() {
  chart?.resize()
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})
</script>

<template>
  <div>
    <el-row :gutter="12">
      <el-col :span="6">
        <el-card shadow="never"><el-statistic title="最新体重(kg)" :value="num(overview.weight_latest)" /></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><el-statistic title="近7天训练(次)" :value="num(overview.workout_7d?.days)" /></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><el-statistic title="近7天平均睡眠(h)" :value="num(overview.sleep_7d?.avg)" /></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <el-statistic title="近7天完成率(%)"
            :value="overview.checkin_7d?.completion_rate != null ? Math.round(overview.checkin_7d.completion_rate * 100) : 0" />
        </el-card>
      </el-col>
    </el-row>
    <el-card shadow="never" style="margin-top: 12px">
      <template #header>近 30 天趋势(体重 / 训练 / 睡眠)</template>
      <div ref="chartRef" style="height: 420px"></div>
    </el-card>
  </div>
</template>
