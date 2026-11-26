<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button
          v-if="moduleKey === 'transcript_version'"
          class="btn"
          data-testid="open-version-ranges"
          type="button"
          @click="openVersionRanges()"
        >
          查回修订范围
        </button>
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <section v-if="isCorrection" class="batch-bar" data-testid="correction-batch-bar">
      <label class="select-all-label">
        <input
          type="checkbox"
          data-testid="select-all-corrections"
          :checked="allVisibleSelected"
          @change="toggleSelectAll"
        />
        全选本页
      </label>
      <span data-testid="selected-count">已多选 {{ selectedIds.length }} 笔</span>
      <span v-if="selectedDraft" data-testid="selected-draft">同一底稿：{{ selectedDraft }}</span>
      <span v-if="selectionError" class="error-text" data-testid="selection-error">{{ selectionError }}</span>
      <div class="batch-actions">
        <button class="btn" type="button" data-testid="load-scenario" :disabled="batchBusy" @click="loadScenario">
          载入「海风吹过港口」交会场景
        </button>
        <button class="btn" type="button" data-testid="query-version-ranges-inline" @click="openVersionRanges(selectedDraft || 'V1')">
          从转写版本查回范围
        </button>
        <button
          class="btn"
          type="button"
          data-testid="text-compare-button"
          :disabled="!selectedIds.length || batchBusy"
          @click="openBatchPreview"
        >
          提交前文本对照
        </button>
        <button
          class="btn primary"
          type="button"
          data-testid="batch-preview-button"
          :disabled="!selectedIds.length || batchBusy"
          @click="openBatchPreview"
        >
          多选预览并批量受理
        </button>
      </div>
    </section>

    <table class="data-table">
      <thead>
        <tr>
          <th v-if="isCorrection" class="checkbox-col">选择</th>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-if="isCorrection" class="checkbox-col">
            <input
              type="checkbox"
              :data-testid="`select-correction-${row.id}`"
              :aria-label="`选择纠错单 ${row.纠错编号 || row.id}`"
              :checked="selectedIds.includes(Number(row.id))"
              @change="toggleSelect(row)"
            />
          </td>
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + (isCorrection ? 3 : 2)" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input
            v-model="createValues[field]"
            :data-testid="`create-${field}`"
            :required="!(isCorrection && (field === '原文本' || field === '纠错范围毫秒'))"
          />
        </label>
        <template v-if="isCorrection">
          <label class="create-field">
            <span>底稿全文（可选；用于按字符坐标建立 V1 对照）</span>
            <textarea
              v-model="createValues['底稿全文']"
              data-testid="create-底稿全文"
              rows="3"
              placeholder="例如：海风吹过港口。灯塔照亮归航。"
            />
          </label>
          <label class="create-field">
            <span>原文字符起（半开坐标，0 表示文首）</span>
            <input v-model="createValues['字符起']" data-testid="create-字符起" type="number" min="0" />
          </label>
          <label class="create-field">
            <span>原文字符止（不含该位置）</span>
            <input v-model="createValues['字符止']" data-testid="create-字符止" type="number" min="0" />
          </label>
          <p class="form-hint">提交后可在列表多选同一底稿，先看文本对照与原坐标来源，再批量受理。</p>
        </template>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <CorrectionPreviewModal
      :open="previewOpen"
      :preview="batchPreview"
      :result="batchResult"
      :error="batchError"
      :busy="batchBusy"
      @close="previewOpen = false"
      @refresh="refreshPreview"
      @accept="acceptBatch"
    />

    <VersionRangesModal
      :open="rangesOpen"
      v-model:version-ref="versionRef"
      :ranges="versionRanges"
      :error="rangesError"
      :busy="rangesBusy"
      @close="rangesOpen = false"
      @query="queryVersionRanges"
    />

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  acceptCorrectionBatch,
  createEntry,
  downloadEntries,
  getVersionRanges,
  listEntries,
  loadCorrectionScenario,
  moduleMeta,
  previewCorrectionBatch,
  runAction as applyAction,
} from '@/api/backend-service'
import type { EntryRow } from '@/data/types'
import CorrectionPreviewModal from './CorrectionPreviewModal.vue'
import VersionRangesModal from './VersionRangesModal.vue'

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})

const isCorrection = computed(() => props.moduleKey === 'correction_loop')
const isTranscriptVersion = computed(() => props.moduleKey === 'transcript_version')
const selectedIds = ref<number[]>([])
const selectionError = ref('')
const previewOpen = ref(false)
const batchBusy = ref(false)
const batchError = ref('')
const batchPreview = ref<any>(null)
const batchResult = ref<any>(null)
const batchVersion = ref('')
const idempotencyKey = ref('')

const rangesOpen = ref(false)
const rangesBusy = ref(false)
const rangesError = ref('')
const versionRef = ref('V1')
const versionRanges = ref<any>(null)

const selectedRows = computed(() => rows.value.filter((row) => selectedIds.value.includes(Number(row.id))))
const selectedDrafts = computed(() => [
  ...new Set(selectedRows.value.map((row) => String(row['关联版本'] || '')).filter(Boolean)),
])
const selectedDraft = computed(() => (selectedDrafts.value.length === 1 ? selectedDrafts.value[0] : ''))
const allVisibleSelected = computed(() =>
  rows.value.length > 0 && rows.value.every((row) => selectedIds.value.includes(Number(row.id))),
)
const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function resetFilters() {
  filters.value = {}
  void reload()
}

function toggleSelect(row: EntryRow) {
  const id = Number(row.id)
  const version = String(row['关联版本'] || '')
  selectionError.value = ''
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((item) => item !== id)
    return
  }
  const firstVersion = selectedRows.value[0] ? String(selectedRows.value[0]['关联版本'] || '') : ''
  if (firstVersion && version && firstVersion !== version) {
    selectionError.value = `只能对同一底稿多选：已选底稿为 ${firstVersion}，不能加入 ${version}。`
    return
  }
  selectedIds.value = [...selectedIds.value, id]
}

function toggleSelectAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  selectionError.value = ''
  if (!checked) {
    const visibleIds = new Set(rows.value.map((row) => Number(row.id)))
    selectedIds.value = selectedIds.value.filter((id) => !visibleIds.has(id))
    return
  }
  const versions = new Set(rows.value.map((row) => String(row['关联版本'] || '')).filter(Boolean))
  if (versions.size > 1) {
    selectionError.value = '当前页包含多个底稿，请按“关联版本”筛选后再全选。'
  }
  selectedIds.value = [
    ...new Set([...selectedIds.value, ...rows.value.map((row) => Number(row.id))]),
  ]
}

function makeIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return `batch-${globalThis.crypto.randomUUID()}`
  return `batch-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

async function requestBatchPreview(useCurrentToken = false) {
  if (!batchVersion.value || !selectedIds.value.length) return
  batchBusy.value = true
  batchError.value = ''
  try {
    const payload: Record<string, unknown> = {
      version_id: batchVersion.value,
      correction_ids: [...selectedIds.value],
    }
    if (useCurrentToken && batchPreview.value?.preview_token) {
      payload.preview_token = batchPreview.value.preview_token
    }
    batchPreview.value = await previewCorrectionBatch(payload)
  } catch (error) {
    batchError.value = error instanceof Error ? error.message : '批量预览失败'
  } finally {
    batchBusy.value = false
  }
}

async function openBatchPreview() {
  if (!selectedIds.value.length) {
    selectionError.value = '请先勾选同一底稿下的纠错单。'
    return
  }
  if (selectedDrafts.value.length > 1) {
    selectionError.value = `只能对同一底稿多选，当前选择了：${selectedDrafts.value.join('、')}`
    return
  }
  batchVersion.value = selectedDraft.value
  batchResult.value = null
  batchError.value = ''
  idempotencyKey.value = makeIdempotencyKey()
  previewOpen.value = true
  await requestBatchPreview(false)
}

async function refreshPreview() {
  batchResult.value = null
  await requestBatchPreview(false)
}

async function acceptBatch() {
  if (!batchPreview.value) return
  batchBusy.value = true
  batchError.value = ''
  try {
    batchResult.value = await acceptCorrectionBatch({
      version_id: batchVersion.value,
      correction_ids: [...selectedIds.value],
      preview_token: batchPreview.value.preview_token,
      idempotency_key: idempotencyKey.value,
    })
    await reload()
    await requestBatchPreview(false)
  } catch (error) {
    batchError.value = error instanceof Error ? error.message : '批量受理失败'
  } finally {
    batchBusy.value = false
  }
}

async function loadScenario() {
  batchBusy.value = true
  batchError.value = ''
  selectionError.value = ''
  try {
    await loadCorrectionScenario(true)
    await reload()
    const jia = rows.value.find((row) => row['纠错编号'] === 'CRLP-JIA-0001')
    const tail = rows.value.find((row) => row['纠错编号'] === 'CRLP-WEI-0001')
    selectedIds.value = [jia ? Number(jia.id) : NaN, tail ? Number(tail.id) : NaN].filter(Number.isFinite)
    batchBusy.value = false
    await openBatchPreview()
  } catch (error) {
    batchError.value = error instanceof Error ? error.message : '场景载入失败'
  } finally {
    batchBusy.value = false
  }
}

function openVersionRanges(version?: string) {
  versionRef.value = version || selectedDraft.value || 'V1'
  rangesOpen.value = true
  versionRanges.value = null
  rangesError.value = ''
  void queryVersionRanges()
}

async function queryVersionRanges() {
  rangesBusy.value = true
  rangesError.value = ''
  try {
    versionRanges.value = await getVersionRanges(versionRef.value.trim() || 'V1')
  } catch (error) {
    rangesError.value = error instanceof Error ? error.message : '版本范围查回失败'
  } finally {
    rangesBusy.value = false
  }
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    const result = await applyAction(meta.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.checkbox-col { width: 42px; text-align: center; }
.batch-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 14px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
  font-size: 13px;
}
.select-all-label { display: inline-flex; align-items: center; gap: 6px; }
.batch-actions { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; }
.form-hint { font-size: 12px; color: var(--muted); margin: 0 0 10px; }
.create-field textarea { width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 8px; font: inherit; resize: vertical; }
@media (max-width: 900px) { .batch-actions { margin-left: 0; } }
</style>
