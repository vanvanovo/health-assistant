<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { streamChat } from '@/api/sse'
import CardBlock from '@/components/CardBlock.vue'

interface Msg {
  role: 'user' | 'assistant'
  text: string
  cards: any[]
  intents?: string[]
  meta?: any
  streaming?: boolean
}

const messages = ref<Msg[]>([])
const input = ref('')
const sending = ref(false)
const listRef = ref<HTMLElement>()

const examples = [
  '今天跑了 5 公里,体重 68.2,睡了 7 个半小时,感觉不错',
  '我最近一个月状态怎么样?',
  '下周给我排训练计划,周三要出差',
  '今天的训练完成了,有点累',
]

async function send(text?: string) {
  const content = (text ?? input.value).trim()
  if (!content || sending.value) return
  input.value = ''
  messages.value.push({ role: 'user', text: content, cards: [] })
  const msg: Msg = { role: 'assistant', text: '', cards: [], streaming: true }
  messages.value.push(msg)
  sending.value = true
  scroll()
  try {
    await streamChat(content, (ev) => {
      if (ev.event === 'routing') msg.intents = ev.data.intents
      else if (ev.event === 'progress') msg.meta = { ...(msg.meta || {}), stage: ev.data.label }
      else if (ev.event === 'card') msg.cards.push(ev.data)
      else if (ev.event === 'token') { msg.text += ev.data.text || ''; scroll() }
      else if (ev.event === 'meta') msg.meta = { ...(msg.meta || {}), ...ev.data }
      else if (ev.event === 'done') msg.streaming = false
    })
  } catch (e: any) {
    msg.text += `\n[连接失败] ${e?.message || e}`
    ElMessage.error('对话连接失败')
  } finally {
    msg.streaming = false
    sending.value = false
    scroll()
  }
}

function scroll() {
  nextTick(() => {
    if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
  })
}
</script>

<template>
  <div class="chat">
    <div ref="listRef" class="list">
      <el-empty v-if="!messages.length" description="和你的健康助手聊聊吧~ 也可以点下面的示例" />
      <div v-for="(m, i) in messages" :key="i" :class="['row', m.role]">
        <el-card v-if="m.role === 'assistant'" class="bubble" shadow="never">
          <div v-if="m.intents?.length" class="chips">
            <el-tag v-for="t in m.intents" :key="t" size="small" type="info">{{ t }}</el-tag>
          </div>
          <CardBlock v-for="(c, ci) in m.cards" :key="ci" :card="c" />
          <div v-if="m.text" class="text">{{ m.text }}</div>
          <div v-if="m.streaming" class="typing">●正在输入…</div>
          <div v-if="m.meta?.elapsed_ms" class="meta">
            耗时 {{ m.meta.elapsed_ms }}ms<span v-if="m.meta.degraded"> · 已降级</span>
          </div>
        </el-card>
        <div v-else class="user-bubble">{{ m.text }}</div>
      </div>
    </div>
    <div class="examples">
      <el-tag v-for="t in examples" :key="t" class="ex" @click="send(t)">{{ t }}</el-tag>
    </div>
    <div class="input">
      <el-input v-model="input" placeholder="比如:今天跑了 5 公里,体重 68.2" @keyup.enter="send()" :disabled="sending" />
      <el-button type="primary" :loading="sending" @click="send()">发送</el-button>
    </div>
  </div>
</template>

<style scoped>
.chat { height: 100%; display: flex; flex-direction: column; }
.list { flex: 1; overflow-y: auto; padding: 8px 4px; }
.row { display: flex; margin-bottom: 12px; }
.row.assistant { justify-content: flex-start; }
.row.user { justify-content: flex-end; }
.bubble { max-width: 760px; }
.user-bubble { max-width: 640px; background: #409eff; color: #fff; padding: 10px 14px; border-radius: 10px; white-space: pre-wrap; }
.text { white-space: pre-wrap; line-height: 1.7; margin-top: 8px; }
.chips { margin-bottom: 6px; display: flex; gap: 6px; }
.typing { color: #409eff; font-size: 12px; margin-top: 6px; }
.meta { color: #999; font-size: 12px; margin-top: 6px; }
.examples { display: flex; gap: 8px; flex-wrap: wrap; padding: 6px 0; }
.ex { cursor: pointer; }
.input { display: flex; gap: 8px; padding-top: 8px; }
</style>
