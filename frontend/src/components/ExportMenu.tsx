import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Download, FileText, Loader2 } from 'lucide-react'
import { apiBase, client, downloadUrl, errorMessage } from '../api/client'

export default function ExportMenu({ jobId }: { jobId: string }) {
  const queryClient = useQueryClient()
  const [requested, setRequested] = useState(false)
  const key = ['pdf-export', jobId]
  const query = useQuery({
    queryKey: key,
    queryFn: async () => {
      const { data, error } = await client.GET('/api/v1/jobs/{job_id}/exports/pdf', {
        params: { path: { job_id: jobId } },
      })
      if (error) throw new Error(errorMessage(error))
      return data ?? null
    },
    refetchInterval: (q) =>
      ['queued', 'running'].includes(q.state.data?.status || '') ? 1500 : false,
  })
  const mutation = useMutation({
    onMutate: async () => {
      setRequested(true)
      await queryClient.cancelQueries({ queryKey: key })
    },
    mutationFn: async () => {
      const { data, error } = await client.POST('/api/v1/jobs/{job_id}/exports/pdf', {
        params: { path: { job_id: jobId } },
      })
      if (error || !data) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(key, data)
      setRequested(true)
    },
  })
  const pending = mutation.isPending || ['queued', 'running'].includes(query.data?.status || '')
  const failure = mutation.error?.message || query.data?.error
  const visible = requested || query.data || mutation.error || query.error
  return (
    <div className="export-control">
      <details className="download-menu">
        <summary className="button primary small">
          <Download size={15} />
          导出笔记
          <ChevronDown size={13} />
        </summary>
        <div>
          <button disabled={pending} onClick={() => mutation.mutate()}>
            {pending ? <Loader2 size={14} className="spin" /> : <FileText size={14} />}
            {pending ? 'PDF 正在准备…' : 'PDF · 含图片'}
          </button>
          <a href={downloadUrl(jobId, 'zip')}>完整图文包 · ZIP</a>
          <a href={downloadUrl(jobId, 'md')}>文字与图片引用 · Markdown</a>
          <a href={downloadUrl(jobId, 'html')}>网页文件 · HTML</a>
        </div>
      </details>
      {visible && (
        <div className="pdf-export-status" role="status" aria-live="polite">
          {pending ? (
            <span>
              <Loader2 size={13} className="spin" />
              {query.data?.status === 'running' ? '正在排版 PDF…' : 'PDF 排队准备中…'}
            </span>
          ) : failure ? (
            <>
              <span>{failure}</span>
              <button onClick={() => mutation.mutate()}>重新生成 PDF</button>
            </>
          ) : query.data?.status === 'completed' ? (
            <a href={`${apiBase}/api/v1/exports/${query.data.id}/download`}>
              <Download size={13} />
              下载 PDF（含图片）
            </a>
          ) : null}
          {query.error && <button onClick={() => query.refetch()}>状态连接中断，点击重试</button>}
        </div>
      )}
    </div>
  )
}
