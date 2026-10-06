<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login } from '@/api'
import { auth } from '@/stores/auth'

const username = ref('health-demo')
const password = ref('health-demo')
const loading = ref(false)
const router = useRouter()

async function submit() {
  if (!username.value || !password.value) return
  loading.value = true
  try {
    const data = await login(username.value, password.value)
    auth.setLogin(data.access_token, data.username)
    ElMessage.success('欢迎回来')
    router.push('/chat')
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-bg">
    <el-card class="login-card">
      <h2>🫀 个人健康助手</h2>
      <p class="sub">记录 · 分析 · 计划 · 打卡 —— 长期闭环的个性化健康管理</p>
      <el-form @submit.prevent="submit">
        <el-form-item><el-input v-model="username" placeholder="用户名" /></el-form-item>
        <el-form-item><el-input v-model="password" type="password" placeholder="密码" show-password /></el-form-item>
        <el-button type="primary" class="submit" :loading="loading" @click="submit">登 录</el-button>
      </el-form>
      <p class="hint">演示账号:health-demo / health-demo</p>
    </el-card>
  </div>
</template>

<style scoped>
.login-bg { height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #e8f4ff, #f6ffed); }
.login-card { width: 400px; padding: 12px 8px; }
h2 { margin: 0 0 6px; color: #409eff; }
.sub { color: #888; font-size: 13px; margin: 0 0 18px; }
.submit { width: 100%; margin-top: 4px; }
.hint { color: #aaa; font-size: 12px; text-align: center; margin-top: 14px; }
</style>
