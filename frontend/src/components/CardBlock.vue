<script setup lang="ts">
defineProps<{ card: any }>()
</script>

<template>
  <div class="card-block">
    <template v-if="card.type === 'record_confirm'">
      <el-alert :closable="false" type="success"
        :title="String(card.payload?.mode || '').startsWith('checkin') ? '✅ 打卡卡' : '✅ 记录卡'" />
      <el-descriptions v-if="card.payload?.record" :column="3" size="small" border style="margin-top: 6px">
        <el-descriptions-item label="日期">{{ card.payload.record.date }}</el-descriptions-item>
        <el-descriptions-item label="体重">{{ card.payload.record.weight_kg ?? '-' }} kg</el-descriptions-item>
        <el-descriptions-item label="睡眠">{{ card.payload.record.sleep_hours ?? '-' }} h</el-descriptions-item>
        <el-descriptions-item label="训练">
          {{ card.payload.record.workout_minutes ?? 0 }} 分钟({{ card.payload.record.workout_type || '-' }})
        </el-descriptions-item>
        <el-descriptions-item label="体感">{{ card.payload.record.feeling || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ card.payload.mode === 'duplicate' ? '幂等复放' : '已入库' }}</el-descriptions-item>
      </el-descriptions>
      <el-descriptions v-else-if="card.payload?.item" :column="3" size="small" border style="margin-top: 6px">
        <el-descriptions-item label="打卡项">{{ card.payload.item.title }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ card.payload.item.status }}</el-descriptions-item>
        <el-descriptions-item label="体感">{{ card.payload.item.feeling_score ?? '-' }}</el-descriptions-item>
      </el-descriptions>
    </template>

    <template v-else-if="card.type === 'stats'">
      <el-alert :closable="false" type="info" title="📊 统计卡" />
      <div class="stats" v-if="card.payload?.summary">
        <el-statistic title="训练次数" :value="card.payload.summary.workout?.days ?? 0" />
        <el-statistic title="训练分钟" :value="card.payload.summary.workout?.total_minutes ?? 0" />
        <el-statistic title="平均睡眠" :value="card.payload.summary.sleep?.avg ?? 0" suffix="h" />
        <el-statistic title="体重变化" :value="card.payload.summary.weight?.delta ?? 0" suffix="kg" />
      </div>
      <div v-if="card.payload?.anomalies?.length" class="anomalies">
        <el-tag v-for="(a, i) in card.payload.anomalies" :key="i"
          :type="a.level === 'warn' ? 'warning' : 'info'" size="small">{{ a.message }}</el-tag>
      </div>
    </template>

    <template v-else-if="card.type === 'plan'">
      <el-alert :closable="false" type="success"
        :title="`🗓️ 计划卡 v${card.payload?.version} · 强度档:${card.payload?.level}`" />
      <el-table :data="card.payload?.items || []" size="small" style="margin-top: 6px">
        <el-table-column prop="date" label="日期" width="110" />
        <el-table-column prop="kind" label="类型" width="90" />
        <el-table-column prop="title" label="内容" />
        <el-table-column prop="est_minutes" label="分钟" width="70" />
        <el-table-column prop="intensity" label="强度" width="70" />
      </el-table>
    </template>

    <pre v-else class="raw">{{ JSON.stringify(card, null, 2) }}</pre>
  </div>
</template>

<style scoped>
.card-block { margin: 8px 0; }
.stats { display: flex; gap: 24px; margin-top: 8px; flex-wrap: wrap; }
.anomalies { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.raw { background: #fafafa; padding: 8px; font-size: 12px; max-height: 200px; overflow: auto; }
</style>
