<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchMessages, fetchReports, markMessagesRead } from '@/api'

const tab = ref<'messages' | 'reports'>('messages')
const messages = ref<any[]>([])
const unread = ref(0)
const reports = ref<any[]>([])

const TYPE_CN: Record<string, { label: string; type: string }> = {
  checkin_remind: { label: '提醒', type: 'warning' },
  brief: { label: '简报', type: 'info' },
  weekly: { label: '周报', type: 'success' },
  alert: { label: '预警', type: 'danger' },
}

async function loadMessages() {
  const d = await fetchMessages()
  messages.value = d.messages
  unread.value = d.unread
}

async function loadReports() {
  const d = await fetchReports()
  reports.value = d.reports
}

async function readOne(m: any) {
  if (m.read) return
  await markMessagesRead({ id: m.id })
  m.read = true
  unread.value = Math.max(0, unread.value - 1)
  window.dispatchEvent(new Event('health:unread-changed'))
}

async function readAll() {
  await markMessagesRead({ all: true })
  messages.value.forEach((m) => (m.read = true))
  unread.value = 0
  window.dispatchEvent(new Event('health:unread-changed'))
  ElMessage.success('已全部标为已读')
}

onMounted(async () => {
  await loadMessages()
  await loadReports()
})
</script>

<template>
  <el-card shadow="never">
    <el-tabs v-model="tab">
      <el-tab-pane :label="`站内信${unread ? ` (${unread})` : ''}`" name="messages">
        <div class="bar">
          <el-button size="small" :disabled="!unread" @click="readAll">全部已读</el-button>
        </div>
        <el-empty v-if="!messages.length" description="暂无站内信;定时任务会在这里推送提醒/简报/周报/预警" />
        <div v-for="m in messages" :key="m.id" class="msg" :class="{ unread: !m.read }">
          <div class="msg-head">
            <el-tag size="small" :type="(TYPE_CN[m.type]?.type as any) || 'info'">
              {{ TYPE_CN[m.type]?.label || m.type }}
            </el-tag>
            <b class="title">{{ m.title }}</b>
            <span class="time">{{ String(m.created_at || '').replace('T', ' ').slice(0, 16) }}</span>
            <el-button v-if="!m.read" size="small" text type="primary" @click="readOne(m)">标为已读</el-button>
            <el-tag v-else size="small" type="info" effect="plain">已读</el-tag>
          </div>
          <div class="msg-body">{{ m.body }}</div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="报告" name="reports">
        <el-collapse v-if="reports.length">
          <el-collapse-item v-for="r in reports" :key="r.id" :name="r.id">
            <template #title>
              <el-tag size="small" :type="r.type === 'weekly' ? 'success' : 'info'">
                {{ r.type === 'weekly' ? '周报' : '简报' }}
              </el-tag>
              <span style="margin-left: 8px">{{ r.period_start }} ~ {{ r.period_end }}</span>
            </template>
            <div class="report-body">{{ r.content_md }}</div>
          </el-collapse-item>
        </el-collapse>
        <el-empty v-else description="暂无报告;定时任务(或演示触发端点)会生成简报/周报" />
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<style scoped>
.bar { display: flex; justify-content: flex-end; margin-bottom: 8px; }
.msg { padding: 10px 12px; border-bottom: 1px solid #f0f2f5; }
.msg.unread { background: #f7fbff; }
.msg-head { display: flex; align-items: center; gap: 8px; }
.msg-head .title { flex: 0 0 auto; }
.msg-head .time { color: #999; font-size: 12px; margin-left: auto; }
.msg-body { margin-top: 6px; color: #444; white-space: pre-wrap; line-height: 1.7; }
.report-body { white-space: pre-wrap; line-height: 1.8; color: #333; }
</style>
