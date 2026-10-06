import { createRouter, createWebHistory } from 'vue-router'
import { auth } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('@/views/LoginView.vue') },
    { path: '/', redirect: '/chat' },
    { path: '/chat', component: () => import('@/views/ChatView.vue') },
    { path: '/dashboard', component: () => import('@/views/DashboardView.vue') },
    { path: '/checkin', component: () => import('@/views/CheckinView.vue') },
  ],
})

router.beforeEach((to) => {
  if (to.path !== '/login' && !auth.isLoggedIn) return '/login'
})

export default router
