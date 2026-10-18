<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: String, required: true },
  icon: { type: String, default: 'mdi-chart-line' },
  color: { type: String, default: 'primary' },
  hint: { type: String, default: '' },
})
</script>

<template>
  <VCard class="metric-card" rounded="xl" variant="tonal">
    <VCardText class="d-flex align-center ga-3">
      <VAvatar :color="color" variant="tonal" rounded="lg">
        <VIcon :icon="icon" />
      </VAvatar>
      <div class="min-w-0">
        <div class="text-caption text-medium-emphasis">{{ label }}</div>
        <div class="metric-card__value">{{ value }}</div>
        <div v-if="hint" class="text-caption text-medium-emphasis text-truncate">{{ hint }}</div>
      </div>
    </VCardText>
  </VCard>
</template>

<style scoped>
.metric-card {
  height: 100%;
}

.metric-card__value {
  font-size: clamp(1.05rem, 2vw, 1.45rem);
  font-weight: 750;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.min-w-0 {
  min-width: 0;
}
</style>
