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

export async function fetchCurrentPlan(date?: string) {
  const { data } = await client.get('/plans/current', { params: { date } })
  return data as { plan: any; progress: any }
}

export async function postCheckin(payload: Record<string, unknown>) {
  const { data } = await client.post('/checkins', payload)
  return data
}
