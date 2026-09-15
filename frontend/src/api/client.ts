import createClient from 'openapi-fetch'
import type { paths, components } from './schema'

export type Job = components['schemas']['JobView']
export type NoteData = components['schemas']['NoteView']
export type Capabilities = components['schemas']['Capabilities']
export type Mode = NonNullable<components['schemas']['JobCreate']['mode']>
export const client = createClient<paths>({ baseUrl: import.meta.env.VITE_API_BASE_URL || '' })
export const apiBase = import.meta.env.VITE_API_BASE_URL || ''
export function errorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'detail' in error) {
    const detail = error.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return '请检查输入的地址和选项后重试。'
  }
  return error instanceof Error ? error.message : '请求暂时失败，请稍后重试。'
}
export async function listJobs(): Promise<Job[]> {
  const { data, error } = await client.GET('/api/v1/jobs')
  if (error || !data) throw new Error(errorMessage(error))
  return data.items
}
export async function getJob(id: string): Promise<Job> {
  const { data, error } = await client.GET('/api/v1/jobs/{job_id}', {
    params: { path: { job_id: id } },
  })
  if (error || !data) throw new Error(errorMessage(error))
  return data
}
export async function getNote(id: string): Promise<NoteData> {
  const { data, error } = await client.GET('/api/v1/jobs/{job_id}/note', {
    params: { path: { job_id: id } },
  })
  if (error || !data) throw new Error(errorMessage(error))
  return data
}
export async function getCapabilities(): Promise<Capabilities> {
  const { data, error } = await client.GET('/api/v1/capabilities')
  if (error || !data) throw new Error(errorMessage(error))
  return data
}
export const frameUrl = (id: string, frame: string) =>
  apiBase + '/api/v1/jobs/' + id + '/frames/' + frame
export const downloadUrl = (id: string, kind: 'zip' | 'md' | 'html') =>
  apiBase + '/api/v1/jobs/' + id + '/download/' + kind
export const videoUrl = (id: string) => apiBase + '/api/v1/jobs/' + id + '/video'
export const modeName = (mode: string) =>
  ({ extractive: '原文整理', llm: '精读笔记', vision: '图文精读' })[mode] || mode
export const statusName = (status: string) =>
  ({
    queued: '等待处理',
    running: '正在整理',
    completed: '已完成',
    failed: '处理失败',
    cancelled: '已取消',
  })[status] || status
export const isActive = (job: Job) => ['queued', 'running'].includes(job.status)
export function formatTime(ms: number) {
  const seconds = Math.floor(ms / 1000)
  return (
    Math.floor(seconds / 60)
      .toString()
      .padStart(2, '0') +
    ':' +
    (seconds % 60).toString().padStart(2, '0')
  )
}
export const formatDate = (date: string) =>
  new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' }).format(new Date(date))
