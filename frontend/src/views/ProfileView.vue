<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { addMemoryEvent, fetchEvents, fetchProfile, updateProfile } from '@/api'

const form = ref<any>({
  goal: '', height_cm: null, target_weight_kg: null,
  equipment: '', dietary_restrictions: '', injuries: '',
})
const events = ref<any[]>([])
const saving = ref(false)
const newEvent = ref<any>({ kind: 'travel', description: '', start_date: '', end_date: '' })

const EVENT_CN: Record<string, string> = { injury: '伤病', travel: '出差', checkup: '体检', other: '其他' }
const KIND_CN: Record<string, string> = { workout: '训练', diet: '饮食', habit: '习惯' }

function toList(s: string): string[] {
  return String(s || '')
    .split(/[,，、;；]/)
    .map((x) => x.trim())
    .filter(Boolean)
}

async function load() {
  const p = await fetchProfile()
  form.value = {
    goal: p.goal || '',
    height_cm: p.height_cm,
    target_weight_kg: p.target_weight_kg,
    equipment: (p.equipment || []).join('、'),
    dietary_restrictions: (p.dietary_restrictions || []).join('、'),
    injuries: (p.injuries || []).join('、'),
  }
  const ev = await fetchEvents()
  events.value = ev?.events || []
}

async function save() {
  saving.value = true
  try {
    await updateProfile({
      goal: form.value.goal || '保持健康',
      height_cm: form.value.height_cm === null || form.value.height_cm === '' ? null : Number(form.value.height_cm),
      target_weight_kg: form.value.target_weight_kg === null || form.value.target_weight_kg === '' ? null : Number(form.value.target_weight_kg),
      equipment: toList(form.value.equipment),
      dietary_restrictions: toList(form.value.dietary_restrictions),
      injuries: toList(form.value.injuries),
    })
    ElMessage.success('画像已保存')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    saving.value = false
  }
}

async function submitEvent() {
  if (!newEvent.value.description || !newEvent.value.start_date) {
    ElMessage.warning('请填写描述与开始日期')
    return
  }
  try {
    await addMemoryEvent({ ...newEvent.value, end_date: newEvent.value.end_date || null })
    ElMessage.success('事件已添加')
    newEvent.value = { kind: 'travel', description: '', start_date: '', end_date: '' }
    await load()
  } catch {
    /* 拦截器已提示 */
  }
}

onMounted(load)
</script>

<template>
  <div>
    <el-card shadow="never">
      <template #header>健康画像(计划与推荐都会参考它)</template>
      <el-form label-width="110px" style="max-width: 680px">
        <el-form-item label="目标">
          <el-radio-group v-model="form.goal">
            <el-radio-button label="减脂" />
            <el-radio-button label="增肌" />
            <el-radio-button label="保持健康" />
          </el-radio-group>
        </el-form-item>
        <el-form-item label="身高(cm)">
          <el-input-number v-model="form.height_cm" :min="50" :max="250" />
        </el-form-item>
        <el-form-item label="目标体重(kg)">
          <el-input-number v-model="form.target_weight_kg" :min="30" :max="300" :precision="1" />
        </el-form-item>
        <el-form-item label="器械(顿号分隔)">
          <el-input v-model="form.equipment" placeholder="哑铃、跑鞋、瑜伽垫" />
        </el-form-item>
        <el-form-item label="饮食禁忌">
          <el-input v-model="form.dietary_restrictions" placeholder="乳糖不耐受、海鲜过敏" />
        </el-form-item>
        <el-form-item label="伤病/限制">
          <el-input v-model="form.injuries" placeholder="右膝不适" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存画像</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" style="margin-top: 12px">
      <template #header>事件记忆(生效中;过期自动失效)</template>
      <el-table :data="events" size="small" style="margin-bottom: 12px">
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ EVENT_CN[row.kind] || row.kind }}</template>
        </el-table-column>
        <el-table-column prop="description" label="描述" />
        <el-table-column prop="start_date" label="开始" width="110" />
        <el-table-column label="结束" width="110">
          <template #default="{ row }">{{ row.end_date || '长期' }}</template>
        </el-table-column>
      </el-table>
      <el-form inline>
        <el-form-item label="类型">
          <el-select v-model="newEvent.kind" style="width: 110px">
            <el-option v-for="(v, k) in EVENT_CN" :key="k" :label="v" :value="k" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="newEvent.description" style="width: 220px" placeholder="上海出差" />
        </el-form-item>
        <el-form-item label="开始">
          <el-date-picker v-model="newEvent.start_date" type="date" value-format="YYYY-MM-DD" style="width: 150px" />
        </el-form-item>
        <el-form-item label="结束">
          <el-date-picker v-model="newEvent.end_date" type="date" value-format="YYYY-MM-DD" style="width: 150px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="submitEvent">添加事件</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>
