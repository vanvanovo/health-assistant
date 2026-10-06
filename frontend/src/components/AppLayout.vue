<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { fetchMessages } from '@/api'
import { auth } from '@/stores/auth'

const router = useRouter()
const unread = ref(0)

async function refreshUnread() {
  try {
    const d = await fetchMessages(true)
    unread.value = d.unread
  } catch {
    /* 网络异常时静默 */
  }
}

function onChanged() {
  refreshUnread()
}

onMounted(() => {
  refreshUnread()
  window.addEventListener('health:unread-changed', onChanged)
})

onBeforeUnmount(() => {
  window.removeEventListener('health:unread-changed', onChanged)
})

function logout() {
  auth.logout()
  ElMessage.success('已退出')
  router.push('/login')
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="208px" class="aside">
      <div class="logo">🫀 健康助手</div>
      <el-menu :default-active="$route.path" router class="menu">
        <el-menu-item index="/chat"><el-icon><ChatDotRound /></el-icon>对话</el-menu-item>
        <el-menu-item index="/dashboard"><el-icon><TrendCharts /></el-icon>数据看板</el-menu-item>
        <el-menu-item index="/checkin"><el-icon><Calendar /></el-icon>计划打卡</el-menu-item>
        <el-menu-item index="/profile"><el-icon><User /></el-icon>我的画像</el-menu-item>
        <el-menu-item index="/notices">
          <el-icon><Bell /></el-icon><span>报告与提醒</span>
          <el-badge v-if="unread > 0" :value="unread" :max="99" class="unread-badge" />
        </el-menu-item>
      </el-menu>
      <div class="user">
        <span>{{ auth.username || '未登录' }}</span>
        <el-button link type="danger" @click="logout">退出</el-button>
      </div>
    </el-aside>
    <el-main class="main"><slot /></el-main>
  </el-container>
</template>

<style>
html, body, #app { height: 100%; margin: 0; }
.layout { height: 100vh; }
.aside { border-right: 1px solid #e4e7ed; display: flex; flex-direction: column; background: #fff; }
.logo { font-weight: 700; font-size: 17px; padding: 16px; color: #409eff; }
.menu { border-right: none; }
.user { margin-top: auto; padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #eee; }
.unread-badge { margin-left: 8px; }
.main { background: #f5f7fa; padding: 16px; }
</style>
