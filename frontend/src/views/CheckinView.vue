<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchCurrentPlan, postCheckin } from '@/api'

const plan = ref<any>(null)
const progress = ref<any>(null)

const rate = computed(() => {
  const r = progress.value?.progress?.completion_rate
  return r != null ? Math.round(r * 100) : 0
})

async function load() {
  const data = await fetchCurrentPlan()
  plan.value = data.plan
  progress.value = data.progress
}

async function doCheckin(item: any, status: string) {
  try {
    await postCheckin({ plan_item_id: item.id, status })
    ElMessage.success('打卡成功')
    await load()
  } catch {
    /* 拦截器已提示 */
  }
}

function tagType(status: string) {
  return status === 'done' ? 'success' : status === 'missed' ? 'danger' : status === 'partial' ? 'warning' : 'info'
}

onMounted(load)
</script>

<template>
  <div>
    <el-card shadow="never">
      <template v-if="plan">
        <div class="head">
          <span>本周计划(v{{ plan.version }}):{{ plan.summary }}</span>
          <el-progress :percentage="rate" style="width: 280px" />
        </div>
        <el-table :data="plan.items" size="small" style="margin-top: 10px">
          <el-table-column prop="date" label="日期" width="110" />
          <el-table-column prop="kind" label="类型" width="90" />
          <el-table-column prop="title" label="内容" />
          <el-table-column prop="est_minutes" label="分钟" width="80" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="tagType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="240">
            <template #default="{ row }">
              <el-button size="small" type="success" :disabled="row.status === 'done'" @click="doCheckin(row, 'done')">完成</el-button>
              <el-button size="small" type="warning" :disabled="row.status === 'partial'" @click="doCheckin(row, 'partial')">部分</el-button>
              <el-button size="small" type="danger" :disabled="row.status === 'missed'" @click="doCheckin(row, 'missed')">未完成</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <el-empty v-else description="本周还没有计划,去对话页说「下周给我排训练计划」试试" />
    </el-card>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; }
</style>
