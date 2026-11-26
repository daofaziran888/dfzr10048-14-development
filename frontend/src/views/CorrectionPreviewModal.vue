<template>
  <div v-if="open" class="modal-backdrop" data-testid="batch-preview-modal" @click.self="$emit('close')">
    <section
      class="modal revision-modal"
      data-testid="batch-preview"
      :data-submittable="String(Boolean(preview?.submittable))"
      :data-confirm-enabled="String(Boolean(preview?.confirm_enabled))"
      role="dialog"
      aria-modal="true"
      aria-label="纠错批量预览与受理"
    >
      <header class="revision-head">
        <h3>提交前文本对照 · 版本修订明细</h3>
        <button class="btn ghost" type="button" data-testid="close-preview" @click="$emit('close')">关闭</button>
      </header>

      <p v-if="error" class="error-text" data-testid="preview-error">{{ error }}</p>

      <template v-if="preview">
        <div class="revision-status" :data-submittable="String(Boolean(preview.submittable))">
          <span
            class="status-pill"
            data-testid="preview-submittable"
            :class="preview.submittable ? 'ok' : 'blocked'"
          >
            {{ preview.submittable ? '预览可提交' : '预览不可提交' }}
          </span>
          <span v-if="!preview.submittable && preview.partially_acceptable" class="status-pill warn" data-testid="partial-acceptable">
            有独立更正可受理
          </span>
          <span v-if="preview.stale" class="status-pill warn" data-testid="preview-stale">预览已过期</span>
          <span class="muted">底稿：{{ preview.version_id }}（{{ preview.base_version }}）</span>
        </div>
        <p class="revision-message" data-testid="preview-message">{{ preview.message }}</p>

        <div v-if="preview.remaining_overlap || preview.next_sentence" class="overlap-guidance" data-testid="overlap-guidance">
          <strong data-testid="continue-sentence" :data-sentence-no="preview.remaining_overlap?.sentence_no || 1">
            余下重叠处理位置：{{ preview.next_sentence_label || preview.next_sentence || '对应句子' }}
          </strong>
          <span>{{ preview.remaining_overlap?.message || '请回到重叠起点所在句子继续处理。' }}</span>
        </div>

        <div class="compare-grid" data-testid="text-compare">
          <article class="compare-col">
            <h4>V1 原文（继续可读，不会被覆盖）</h4>
            <p class="compare-text" data-testid="original-text">
              <span
                v-for="(part, index) in preview.text_compare?.original_parts || []"
                :key="`o-${index}`"
                :class="`diff-${part.op}`"
              >{{ part.text }}</span>
            </p>
          </article>
          <article class="compare-col">
            <h4>本次预览产出</h4>
            <p class="compare-text" data-testid="preview-text">
              <span
                v-for="(part, index) in preview.text_compare?.candidate_parts || []"
                :key="`c-${index}`"
                :class="`diff-${part.op}`"
              >{{ part.text }}</span>
            </p>
          </article>
        </div>

        <section class="provenance" data-testid="output-provenance">
          <h4>产出字句来自哪些原坐标</h4>
          <ul>
            <li v-for="(segment, index) in preview.output_provenance || []" :key="`p-${index}`">
              <code>{{ segment.text || '（空串/插入点）' }}</code>
              <span v-if="segment.kind === 'original'">
                来自 {{ preview.version_id }} 原坐标
                <strong>[{{ segment.source_coordinates?.[0] }},{{ segment.source_coordinates?.[1] }})</strong>
              </span>
              <span v-else-if="segment.kind === 'correction_output'">
                由 {{ segment.correction_id }} 产出，锚定/替换原坐标
                <strong>[{{ segment.source_coordinates?.[0] }},{{ segment.source_coordinates?.[1] }})</strong>
                <em v-if="segment.coordinate_text">（原区间字句：{{ segment.coordinate_text }}）</em>
              </span>
              <span v-else>未解决重叠段，原坐标
                <strong>[{{ segment.source_coordinates?.[0] }},{{ segment.source_coordinates?.[1] }})</strong>
              </span>
            </li>
          </ul>
        </section>

        <section class="revision-items">
          <h4>服务端版本修订明细</h4>
          <table class="data-table">
            <thead>
              <tr>
                <th>纠错单</th><th>提交人</th><th>句子</th><th>原文坐标</th>
                <th>原文</th><th>改为</th><th>状态</th><th>受理判断</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in preview.items || []" :key="item.correction_id" :data-testid="`revision-item-${item.correction_id}`">
                <td>{{ item.correction_id }}</td>
                <td>{{ item.author || '—' }}</td>
                <td data-testid="item-sentence">{{ item.sentence_label || item.continue_sentence || (item.sentence_no ? `第${item.sentence_no}句` : '—') }}</td>
                <td data-testid="item-coordinate">{{ item.coordinate_label }}</td>
                <td>{{ item.source_text || item.coordinate_text || '（插入点）' }}</td>
                <td>{{ item.replacement_text }}</td>
                <td>{{ item.status === 'adopted' ? '已采用' : item.status === 'rejected' ? '已拒绝' : '待处理' }}</td>
                <td>
                  <span v-if="item.can_accept" class="ok-text">可受理</span>
                  <span v-else-if="item.already_adopted" class="muted">已采用，重报不重复插入</span>
                  <span v-else class="error-text">重叠/无效</span>
                  <div v-for="conflict in item.conflicts || []" :key="conflict.message" class="conflict-line">
                    {{ conflict.message }}
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </section>

        <div v-if="result" class="batch-result" :class="{ 'batch-error': result.ok === false }" data-testid="batch-result">
          <strong>{{ result.message }}</strong>
          <p v-if="result.accepted_ids?.length">已受理：{{ result.accepted_ids.join('、') }}</p>
          <p v-if="result.duplicate_ids?.length">重报去重：{{ result.duplicate_ids.join('、') }}（只保留一次插入）</p>
          <p v-if="result.failed_ids?.length" class="error-text">未受理：{{ result.failed_ids.join('、') }}</p>
          <p>受理后版本当前文本：<code data-testid="current-text">{{ result.current_text }}</code></p>
        </div>
      </template>

      <footer class="page-actions modal-footer">
        <span v-if="preview && !preview.submittable && preview.acceptable_count > 0" class="partial-hint" data-testid="partial-accept-hint">
          整批不可全部提交；确认批量受理时仅写入 {{ preview.acceptable_count }} 个无冲突项。
        </span>
        <button class="btn" type="button" data-testid="refresh-preview" :disabled="busy" @click="$emit('refresh')">
          重新预览
        </button>
        <button
          class="btn primary"
          type="button"
          data-testid="confirm-batch-accept"
          data-qa="batch-accept"
          :disabled="busy || !preview"
          :aria-disabled="preview && preview.confirm_enabled === false ? 'true' : 'false'"
          @click="$emit('accept')"
        >
          {{ busy ? '受理中…' : '确认批量受理' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  open: boolean
  preview: any
  result?: any
  error?: string
  busy?: boolean
}>()

defineEmits<{
  (e: 'close'): void
  (e: 'refresh'): void
  (e: 'accept'): void
}>()
</script>

<style scoped>
.revision-modal { width: min(980px, 100%); }
.revision-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.revision-status { display: flex; align-items: center; gap: 10px; margin: 10px 0; }
.status-pill { border-radius: 999px; padding: 3px 10px; font-size: 12px; border: 1px solid var(--border); }
.status-pill.ok { background: #ecfdf3; color: #027a48; border-color: #abefc6; }
.status-pill.blocked { background: #fef3f2; color: #b42318; border-color: #fecdca; }
.status-pill.warn { background: #fffaeb; color: #b54708; border-color: #fedf89; }
.muted { color: var(--muted); font-size: 12px; }
.revision-message { font-weight: 600; }
.overlap-guidance { display: grid; gap: 4px; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 8px; padding: 10px; margin: 10px 0; }
.compare-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 12px 0; }
.compare-col { border: 1px solid var(--border); border-radius: 8px; padding: 10px; background: #fbfdff; }
.compare-col h4, .provenance h4, .revision-items h4 { margin: 0 0 8px; }
.compare-text { min-height: 72px; line-height: 1.9; font-size: 15px; margin: 0; white-space: pre-wrap; }
.diff-insert, .diff-replace { background: #dcfce7; color: #166534; border-radius: 3px; }
.diff-delete { background: #fee2e2; color: #991b1b; text-decoration: line-through; border-radius: 3px; }
.provenance { border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin: 12px 0; }
.provenance ul { margin: 0; padding-left: 18px; display: grid; gap: 6px; }
.provenance code, .batch-result code { background: #f1f5f9; padding: 1px 5px; border-radius: 4px; }
.revision-items { max-height: 280px; overflow: auto; }
.conflict-line { color: #b42318; font-size: 12px; margin-top: 3px; }
.ok-text { color: #027a48; }
.batch-result { margin-top: 12px; padding: 10px; border-radius: 8px; background: #f0f9ff; border: 1px solid #bae6fd; }
.batch-result.batch-error { background: #fef3f2; border-color: #fecdca; color: #b42318; }
.modal-footer { justify-content: flex-end; align-items: center; gap: 10px; margin-top: 14px; }
.partial-hint { margin-right: auto; color: #b54708; font-size: 12px; }
@media (max-width: 820px) { .compare-grid { grid-template-columns: 1fr; } }
</style>
