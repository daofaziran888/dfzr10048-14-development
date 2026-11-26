import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

export type RevisionPayload = Record<string, unknown>

export async function previewCorrectionBatch(payload: RevisionPayload): Promise<any> {
  const response = await request('/api/correction_loop/batch-preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return await response.json()
}

export async function acceptCorrectionBatch(payload: RevisionPayload): Promise<any> {
  const response = await request('/api/correction_loop/batch-accept', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return await response.json()
}

export async function loadCorrectionScenario(reset = false): Promise<any> {
  const response = await request('/api/correction_loop/scenario/load', {
    method: 'POST',
    body: JSON.stringify({ reset }),
  })
  return await response.json()
}

export async function getVersionRanges(versionRef: string): Promise<any> {
  const response = await request(`/api/transcript_version/${encodeURIComponent(versionRef)}/ranges`)
  if (!response.ok) throw new Error('版本修订范围查回失败')
  return await response.json()
}
