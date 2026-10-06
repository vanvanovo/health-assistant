import { auth } from '@/stores/auth'

export interface ChatEvent {
  event: 'routing' | 'progress' | 'card' | 'token' | 'meta' | 'done' | string
  data: any
}

/** SSE 对话流:fetch + reader 解析 event:/data: 行(支持 Bearer 头)。 */
export async function streamChat(message: string, onEvent: (ev: ChatEvent) => void): Promise<void> {
  const resp = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${auth.token}`,
    },
    body: JSON.stringify({ message }),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  const reader = resp.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const part of parts) {
      let evName = 'message'
      let dataRaw = ''
      for (const line of part.split('\n')) {
        if (line.startsWith('event:')) evName = line.slice(6).trim()
        else if (line.startsWith('data:')) dataRaw += line.slice(5).trim()
      }
      if (!dataRaw) continue
      try {
        onEvent({ event: evName, data: JSON.parse(dataRaw) })
      } catch {
        /* 忽略非 JSON 行 */
      }
    }
  }
}
