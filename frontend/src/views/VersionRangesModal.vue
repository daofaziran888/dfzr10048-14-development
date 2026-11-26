<template>
  <div v-if="open" class="modal-backdrop" data-testid="version-ranges-modal" @click.self="$emit('close')">
    <section class="modal ranges-modal" role="dialog" aria-modal="true" aria-label="转写版本修订范围查回">
      <header class="revision-head">
        <h3>转写版本 · 已采用与待处理范围查回</h3>
        <button class="btn ghost" type="button" @click="$emit('close')">关闭</button>
      </header>

      <form class="ranges-query" @submit.prevent="$emit('query')">
        <label>
          <span>版本号 / 版本编号</span>
          <input
            :value="versionRef"
            data-testid="version-ref-input"
            placeholder="例如 V1 或 TRSV-0001"
            @input="$emit('update:versionRef', ($event.target as HTMLInputElement).value)"
          />
        </label>
        <button class="btn primary" type="submit" data-testid="query-ranges" :disabled="busy">查回修订范围</button>
      </form>

      <p v-if="error" class="error-text" data-testid="ranges-error">{{ error }}</p>

      <template v-if="ranges">
        <div class="range-text">
          <h4>V1 / 版本原文（持续可读）</h4>
          <p data-testid="version-original-text">{{ ranges.original_text || '该版本尚未登记原文' }}</p>
        </div>
        <div class="range-text">
          <h4>按已采用范围重算文本</h4>
          <p data-testid="version-current-text">{{ ranges.current_text }}</p>
        </div>

        <div class="range-columns">
          <section>
            <h4>已采用范围（{{ ranges.adopted_ranges?.length || 0 }}）</h4>
            <ul data-testid="adopted-ranges">
              <li v-for="item in ranges.adopted_ranges || []" :key="`a-${item.correction_id}`">
                <code>{{ item.coordinate_label }}</code>
                {{ item.correction_id }}：{{ item.source_text || item.coordinate_text || '插入点' }} → {{ item.replacement_text }}
                <span class="muted">（{{ item.sentence_no ? `第${item.sentence_no}句` : '句子未知' }}）</span>
              </li>
            </ul>
          </section>
          <section>
            <h4>待处理范围（{{ ranges.pending_ranges?.length || 0 }}）</h4>
            <ul data-testid="pending-ranges">
              <li v-for="item in ranges.pending_ranges || []" :key="`p-${item.correction_id}`">
                <code>{{ item.coordinate_label }}</code>
                {{ item.correction_id }}：{{ item.source_text || item.coordinate_text || '插入点' }} → {{ item.replacement_text }}
                <span class="muted">（{{ item.sentence_no ? `第${item.sentence_no}句` : '句子未知' }}）</span>
              </li>
            </ul>
          </section>
        </div>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  open: boolean
  versionRef: string
  ranges: any
  error?: string
  busy?: boolean
}>()

defineEmits<{
  (e: 'close'): void
  (e: 'query'): void
  (e: 'update:versionRef', value: string): void
}>()
</script>

<style scoped>
.revision-head { display: flex; justify-content: space-between; align-items: center; }
.ranges-query { display: flex; gap: 10px; align-items: end; margin: 14px 0; }
.ranges-query label { display: grid; gap: 4px; font-size: 12px; color: var(--muted); flex: 1; }
.ranges-query input { padding: 8px; border: 1px solid var(--border); border-radius: 6px; }
.range-text { border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin: 10px 0; background: #fbfdff; }
.range-text p { font-size: 15px; line-height: 1.8; margin: 6px 0 0; }
.range-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.range-columns section { border: 1px solid var(--border); border-radius: 8px; padding: 10px; }
.range-columns ul { margin: 0; padding-left: 18px; display: grid; gap: 8px; font-size: 13px; }
.range-columns code { background: #f1f5f9; padding: 1px 5px; border-radius: 4px; }
.muted { color: var(--muted); }
@media (max-width: 820px) { .range-columns { grid-template-columns: 1fr; } }
</style>
