<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { auth } from '@/stores/auth'

const router = useRouter()

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
.main { background: #f5f7fa; padding: 16px; }
</style>
