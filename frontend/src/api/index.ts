import client from './client'

export async function login(username: string, password: string) {
  const { data } = await client.post('/auth/login', { username, password })
  return data as { access_token: string; username: string }
}

export async function fetchOverview(date?: string) {
  const { data } = await client.get('/dashboard/overview', { params: { date } })
  return data
}

export async function fetchTrends(from: string, to: string) {
  const { data } = await client.get('/dashboard/trends', { params: { from, to } })
  return data as { series: Array<{ date: string; weight_kg: number | null; workout_minutes: number; sleep_hours: number | null }> }
}

export async function fetchHeatmap(days = 90) {
  const { data } = await client.get('/dashboard/heatmap', { params: { days } })
  return data as { from: string; to: string; days: Array<{ date: string; workout_minutes: number; checkin_done: number }> }
}

export async function fetchRadar(weeks = 4) {
  const { data } = await client.get('/dashboard/radar', { params: { weeks } })
  return data as { weeks: number; scores: Record<string, number>; detail: Record<string, any> }
}

export async function fetchCurrentPlan(date?: string) {
  const { data } = await client.get('/plans/current', { params: { date } })
  return data as { plan: any; progress: any }
}

export async function postCheckin(payload: Record<string, unknown>) {
  const { data } = await client.post('/checkins', payload)
  return data
}

export async function fetchProfile() {
  const { data } = await client.get('/profile')
  return data
}

export async function updateProfile(patch: Record<string, unknown>) {
  const { data } = await client.put('/profile', { patch })
  return data
}

export async function fetchEvents(date?: string) {
  const { data } = await client.get('/memory/events', { params: { date } })
  return data as { events?: any[]; count?: number }
}

export async function addMemoryEvent(payload: Record<string, unknown>) {
  const { data } = await client.post('/memory/events', payload)
  return data
}

export async function applyMemory(token: string) {
  const { data } = await client.post('/memory/apply', { token })
  return data as { status: string; kind?: string; summary?: string }
}
