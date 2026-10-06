import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { auth } from '@/stores/auth'

const client = axios.create({ baseURL: '/api/v1', timeout: 60_000 })

client.interceptors.request.use((config) => {
  if (auth.token) config.headers.Authorization = `Bearer ${auth.token}`
  return config
})

client.interceptors.response.use(
  (res) => res,
  (error) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail
    if (status === 401) {
      auth.logout()
      router.push('/login').catch(() => {})
    } else if (detail) {
      ElMessage.error(detail)
    } else if (status && status >= 500) {
      ElMessage.error('服务异常,请稍后重试')
    }
    return Promise.reject(error)
  },
)

export default client
