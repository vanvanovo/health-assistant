<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'

const route = useRoute()
const plain = computed(() => route.path === '/login')
</script>

<template>
  <router-view v-if="plain" />
  <AppLayout v-else>
    <router-view />
  </AppLayout>
</template>
