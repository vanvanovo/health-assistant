<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ card: any }>()

const MEAL_CN: Record<string, string> = { breakfast: '早餐', lunch: '午餐', dinner: '晚餐', snack: '加餐' }

const mealRows = computed(() => {
  const meals = props.card?.payload?.meals || {}
  const rows: any[] = []
  for (const [slot, items] of Object.entries(meals)) {
    for (const it of ((items as any[]) || [])) {
      rows.push({ slot: MEAL_CN[slot] || slot, ...it })
    }
  }
  return rows
})
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
          <template v-if="card.payload.record.workout_type === 'rest'">休息日</template>
          <template v-else-if="!card.payload.record.workout_type && !(card.payload.record.workout_minutes > 0)">-</template>
          <template v-else>
            <span v-if="card.payload.record.workout_minutes > 0">{{ card.payload.record.workout_minutes }} 分钟</span>
            <span v-else>时长未记录</span>
            <span v-if="card.payload.record.workout_type"> · {{ card.payload.record.workout_type }}</span>
          </template>
        </el-descriptions-item>
        <el-descriptions-item label="体感">{{ card.payload.record.feeling || '-' }}</el-descriptions-item>
        <el-descriptions-item label="备注" :span="2">{{ card.payload.record.note || '-' }}</el-descriptions-item>
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

    <template v-else-if="card.type === 'diet'">
      <el-alert :closable="false" type="success"
        :title="card.payload?.mode === 'recommend' ? '🍽️ 食谱卡' : '🍽️ 饮食卡'" />
      <template v-if="card.payload?.mode === 'log'">
        <el-table :data="card.payload.items || []" size="small" style="margin-top: 6px">
          <el-table-column prop="food" label="食物" />
          <el-table-column prop="amount_g" label="克数" width="80" />
          <el-table-column prop="kcal" label="热量" width="80" />
          <el-table-column prop="protein_g" label="蛋白" width="80" />
        </el-table>
        <div class="diet-total" v-if="card.payload.day_totals">
          今日累计约 {{ card.payload.day_totals.kcal }} kcal / 蛋白 {{ card.payload.day_totals.protein_g }}g
        </div>
        <div class="diet-total" v-if="card.payload.errors?.length">
          未识别:{{ card.payload.errors.map((e: any) => e.food).join('、') }}
        </div>
      </template>
      <template v-else>
        <div class="diet-total">
          需求:{{ card.payload.needs?.kcal }} kcal / 蛋白 {{ card.payload.needs?.protein_g }}g({{ card.payload.needs?.goal }})
        </div>
        <el-table :data="mealRows" size="small" style="margin-top: 6px">
          <el-table-column prop="slot" label="餐次" width="80" />
          <el-table-column prop="food" label="食物" />
          <el-table-column prop="amount_g" label="克数" width="80" />
          <el-table-column prop="kcal" label="热量" width="80" />
        </el-table>
        <div class="diet-total">
          合计约 {{ card.payload.totals?.kcal }} kcal / 蛋白 {{ card.payload.totals?.protein_g }}g
        </div>
      </template>
      <div class="diet-note" v-if="card.payload?.note">{{ card.payload.note }}</div>
    </template>

    <pre v-else class="raw">{{ JSON.stringify(card, null, 2) }}</pre>
  </div>
</template>

<style scoped>
.card-block { margin: 8px 0; }
.stats { display: flex; gap: 24px; margin-top: 8px; flex-wrap: wrap; }
.anomalies { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.diet-total { margin-top: 6px; color: #606266; font-size: 13px; }
.diet-note { margin-top: 4px; color: #999; font-size: 12px; }
.raw { background: #fafafa; padding: 8px; font-size: 12px; max-height: 200px; overflow: auto; }
</style>
