<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { fetchCurrentPlan, fetchHeatmap, fetchOverview, fetchRadar, fetchTrends } from '@/api'

const overview = ref<any>({})
const radarData = ref<any>({})
const heatMetric = ref<'workout_minutes' | 'checkin_done'>('workout_minutes')
const focusRange = ref<{ from: string; to: string } | null>(null)

const trendRef = ref<HTMLElement>()
const heatRef = ref<HTMLElement>()
const radarRef = ref<HTMLElement>()
const donutRef = ref<HTMLElement>()
let trendChart: echarts.ECharts | null = null
let heatChart: echarts.ECharts | null = null
let radarChart: echarts.ECharts | null = null
let donutChart: echarts.ECharts | null = null

let heatDays: any[] = []
let heatFrom = ''
let heatTo = ''

function isoDaysAgo(n: number) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

function num(v: any): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function renderTrend(series: any[]) {
  trendChart?.setOption(
    {
      tooltip: { trigger: 'axis' },
      legend: { data: ['体重(kg)', '训练(分钟)', '睡眠(h)'] },
      grid: { left: 55, right: 55, top: 40, bottom: 62 },
      dataZoom: [
        { type: 'inside' },
        { type: 'slider', height: 18, bottom: 12 },
      ],
      xAxis: { type: 'category', data: series.map((s) => s.date) },
      yAxis: [
        { type: 'value', name: 'kg/分钟' },
        { type: 'value', name: '小时', max: 12 },
      ],
      series: [
        {
          name: '体重(kg)', type: 'line', smooth: true, data: series.map((s) => s.weight_kg),
          markArea: focusRange.value
            ? {
                silent: true,
                itemStyle: { color: 'rgba(64,158,255,0.14)' },
                data: [[{ xAxis: focusRange.value.from }, { xAxis: focusRange.value.to }]],
              }
            : undefined,
        },
        { name: '训练(分钟)', type: 'bar', data: series.map((s) => s.workout_minutes) },
        { name: '睡眠(h)', type: 'line', yAxisIndex: 1, data: series.map((s) => s.sleep_hours) },
      ],
    },
    true,
  )
}

function renderHeat() {
  const values = heatDays.map((d) => [
    d.date,
    heatMetric.value === 'workout_minutes' ? d.workout_minutes : d.checkin_done,
  ])
  const maxVal = Math.max(4, ...values.map((v) => Number(v[1]) || 0))
  heatChart?.setOption(
    {
      tooltip: {
        formatter: (p: any) =>
          `${p.data[0]} : ${p.data[1]}${heatMetric.value === 'workout_minutes' ? ' 分钟' : ' 次打卡'}`,
      },
      visualMap: {
        min: 0, max: maxVal, orient: 'horizontal', left: 'center', top: 0,
        inRange: { color: ['#ebedf0', '#c6e48b', '#7bc96f', '#239a3b', '#196127'] },
      },
      calendar: {
        range: [heatFrom, heatTo], cellSize: ['auto', 15], top: 52, left: 42, right: 16,
        dayLabel: { nameMap: 'ZH' }, monthLabel: { nameMap: 'ZH' }, yearLabel: { show: false },
      },
      series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: values }],
    },
    true,
  )
}

function renderRadar() {
  const s = radarData.value?.scores || {}
  radarChart?.setOption(
    {
      tooltip: {},
      radar: {
        radius: '62%',
        indicator: [
          { name: '运动', max: 100 }, { name: '睡眠', max: 100 },
          { name: '饮食', max: 100 }, { name: '恢复', max: 100 },
        ],
      },
      series: [
        {
          type: 'radar',
          areaStyle: { opacity: 0.25 },
          data: [{ value: [num(s.sport), num(s.sleep), num(s.diet), num(s.recovery)], name: '近 4 周评分' }],
        },
      ],
    },
    true,
  )
}

function renderDonut(plan: any, progress: any) {
  const rate = progress?.progress?.completion_rate
  const done = rate != null ? Math.round(rate * 100) : null
  donutChart?.setOption(
    {
      title: {
        text: done != null ? `${done}%` : '无计划',
        subtext: '本周完成率',
        left: 'center',
        top: '40%',
      },
      series: [
        {
          type: 'pie',
          radius: ['58%', '76%'],
          label: { show: false },
          data:
            done != null
              ? [
                  { value: done, name: '已完成', itemStyle: { color: '#409eff' } },
                  { value: 100 - done, name: '未完成', itemStyle: { color: '#eef1f6' } },
                ]
              : [{ value: 1, name: '暂无计划', itemStyle: { color: '#eef1f6' } }],
        },
      ],
    },
    true,
  )
}

async function reloadTrend() {
  const trends = await fetchTrends(isoDaysAgo(29), isoDaysAgo(0))
  renderTrend(trends.series || [])
}

function clearFocus() {
  sessionStorage.removeItem('health:focusRange')
  focusRange.value = null
  reloadTrend()
}

watch(heatMetric, renderHeat)

onMounted(async () => {
  const stored = sessionStorage.getItem('health:focusRange')
  if (stored) {
    try {
      focusRange.value = JSON.parse(stored)
    } catch {
      focusRange.value = null
    }
  }
  overview.value = await fetchOverview()
  const trends = await fetchTrends(isoDaysAgo(29), isoDaysAgo(0))
  const heat = await fetchHeatmap(90)
  radarData.value = await fetchRadar(4)
  const planData = await fetchCurrentPlan()

  await nextTick()
  trendChart = echarts.init(trendRef.value!)
  heatChart = echarts.init(heatRef.value!)
  radarChart = echarts.init(radarRef.value!)
  donutChart = echarts.init(donutRef.value!)

  heatDays = heat.days || []
  heatFrom = heat.from
  heatTo = heat.to
  renderTrend(trends.series || [])
  renderHeat()
  renderRadar()
  renderDonut(planData.plan, planData.progress)
  window.addEventListener('resize', resize)
})

function resize() {
  trendChart?.resize()
  heatChart?.resize()
  radarChart?.resize()
  donutChart?.resize()
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  ;[trendChart, heatChart, radarChart, donutChart].forEach((c) => c?.dispose())
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
      <template #header>
        <div class="card-head">
          <span>近 30 天趋势(体重 / 训练 / 睡眠)</span>
          <el-tag v-if="focusRange" closable type="primary" @close="clearFocus">
            对话高亮:{{ focusRange.from }} ~ {{ focusRange.to }}
          </el-tag>
        </div>
      </template>
      <div ref="trendRef" style="height: 340px"></div>
    </el-card>

    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>近 90 天日历热力图</span>
              <el-radio-group v-model="heatMetric" size="small">
                <el-radio-button value="workout_minutes">训练分钟</el-radio-button>
                <el-radio-button value="checkin_done">打卡次数</el-radio-button>
              </el-radio-group>
            </div>
          </template>
          <div ref="heatRef" style="height: 280px"></div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <template #header>四维健康评分(近 4 周,规则加权)</template>
          <div ref="radarRef" style="height: 280px"></div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <template #header>本周计划完成率</template>
          <div ref="donutRef" style="height: 280px"></div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
