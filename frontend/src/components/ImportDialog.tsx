import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  ArrowUpRight,
  FileVideo2,
  Link2,
  Loader2,
  Sparkles,
  Upload,
  X,
  Check,
  ChevronDown,
} from 'lucide-react'
import { apiBase, client, errorMessage, getCapabilities } from '../api/client'
import type { Job, Mode } from '../api/client'

export default function ImportDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [tab, setTab] = useState<'url' | 'file'>('url')
  const [url, setUrl] = useState('')
  const [mode, setMode] = useState<Mode>('extractive')
  const [prompt, setPrompt] = useState('')
  const [video, setVideo] = useState<File | null>(null)
  const [subtitles, setSubtitles] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const key = useRef(crypto.randomUUID())
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: caps } = useQuery({
    queryKey: ['capabilities'],
    queryFn: getCapabilities,
    enabled: open,
  })
  const modes = [
    {
      id: 'extractive' as Mode,
      title: '原文整理',
      description: '保留原话，搭配视频截图',
      enabled: true,
    },
    {
      id: 'llm' as Mode,
      title: '精读笔记',
      description: '提炼主题，梳理重点与例子',
      enabled: !!caps?.text_model_ready,
    },
    {
      id: 'vision' as Mode,
      title: '图文精读',
      description: '结合画面理解与智能选图',
      enabled: !!caps?.vision_model_ready,
    },
  ]
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setError('')
    if (tab === 'file' && !video) {
      setError('请先选择一个视频文件。')
      return
    }
    if (video && caps && video.size > caps.max_upload_mb * 1024 * 1024) {
      setError('视频超过上传大小限制。')
      return
    }
    setBusy(true)
    try {
      let job: Job
      if (tab === 'url') {
        const result = await client.POST('/api/v1/jobs', {
          body: { url: url.trim(), mode, asr_prompt: prompt, language: 'zh', asr_model: 'small' },
          headers: { 'Idempotency-Key': key.current },
        })
        if (result.error || !result.data) throw new Error(errorMessage(result.error))
        job = result.data
      } else {
        const form = new FormData()
        form.append('video', video!)
        form.append('mode', mode)
        form.append('asr_prompt', prompt)
        if (subtitles) form.append('subtitles', subtitles)
        const response = await fetch(apiBase + '/api/v1/uploads', {
          method: 'POST',
          body: form,
          headers: { 'Idempotency-Key': key.current },
        })
        const data = await response.json()
        if (!response.ok) throw new Error(errorMessage(data))
        job = data
      }
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
      key.current = crypto.randomUUID()
      onOpenChange(false)
      navigate('/notes/' + job.id)
    } catch (error) {
      setError(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }
  function changeInput() {
    key.current = crypto.randomUUID()
    setError('')
  }
  return (
    <Dialog.Root open={open} onOpenChange={busy ? undefined : onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content">
          <div className="dialog-heading">
            <div className="dialog-symbol">
              <Sparkles size={23} />
            </div>
            <Dialog.Close className="icon-button" aria-label="关闭导入窗口" disabled={busy}>
              <X size={20} />
            </Dialog.Close>
          </div>
          <Dialog.Title>把下一段视频，变成你的笔记。</Dialog.Title>
          <Dialog.Description>从一个链接开始，留下值得反复阅读的内容。</Dialog.Description>
          <div className="segmented" role="tablist" aria-label="导入方式">
            <button
              role="tab"
              aria-selected={tab === 'url'}
              className={tab === 'url' ? 'selected' : ''}
              onClick={() => {
                setTab('url')
                changeInput()
              }}
            >
              <Link2 size={16} /> 视频链接
            </button>
            <button
              role="tab"
              aria-selected={tab === 'file'}
              className={tab === 'file' ? 'selected' : ''}
              onClick={() => {
                setTab('file')
                changeInput()
              }}
            >
              <Upload size={16} /> 本地上传
            </button>
          </div>
          <form onSubmit={submit}>
            {tab === 'url' ? (
              <label className="field-label">
                B 站视频地址
                <input
                  autoFocus
                  required
                  type="url"
                  placeholder="https://www.bilibili.com/video/BV…"
                  value={url}
                  onChange={(e) => {
                    setUrl(e.target.value)
                    changeInput()
                  }}
                />
                <small>支持完整视频链接与 b23.tv 短链接，一次整理一个分 P。</small>
              </label>
            ) : (
              <>
                <input
                  ref={fileInput}
                  className="sr-only"
                  type="file"
                  accept=".mp4,.mkv,.mov,.webm,.flv,.avi"
                  onChange={(e) => {
                    setVideo(e.target.files?.[0] || null)
                    changeInput()
                  }}
                />
                <button
                  className="drop-zone"
                  type="button"
                  onClick={() => fileInput.current?.click()}
                >
                  <FileVideo2 size={29} />
                  <strong>{video?.name || '选择一段本地视频'}</strong>
                  <span>
                    {video
                      ? (video.size / 1024 / 1024).toFixed(1) + ' MB · 点击更换'
                      : 'MP4、MOV、MKV 等格式'}
                  </span>
                </button>
                <label className="field-label compact">
                  字幕文件 <span className="muted">可选</span>
                  <input
                    type="file"
                    accept=".srt,.vtt,.json"
                    onChange={(e) => {
                      setSubtitles(e.target.files?.[0] || null)
                      changeInput()
                    }}
                  />
                </label>
              </>
            )}
            <fieldset className="mode-fieldset">
              <legend>你想怎样阅读？</legend>
              <div className="mode-options">
                {modes.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    aria-pressed={mode === item.id}
                    disabled={!item.enabled}
                    className={'mode-option ' + (mode === item.id ? 'active' : '')}
                    onClick={() => {
                      setMode(item.id)
                      changeInput()
                    }}
                  >
                    <span className="mode-title">
                      {item.title}
                      {mode === item.id && <Check size={15} />}
                    </span>
                    <small>{item.enabled ? item.description : '需要配置模型'}</small>
                  </button>
                ))}
              </div>
            </fieldset>
            <details className="advanced">
              <summary>
                转写选项 <ChevronDown size={14} />
              </summary>
              <label className="field-label">
                术语提示
                <input
                  placeholder="例如 MySQL、InnoDB、存储引擎"
                  value={prompt}
                  maxLength={500}
                  onChange={(e) => {
                    setPrompt(e.target.value)
                    changeInput()
                  }}
                />
                <small>给出视频中的专业词汇，帮助语音识别准确拼写。</small>
              </label>
            </details>
            {mode !== 'extractive' && (
              <p className="privacy-note">
                字幕{mode === 'vision' ? '和候选截图' : ''}会发送到你配置的模型服务。
              </p>
            )}
            {error && (
              <p role="alert" className="error-message">
                {error}
              </p>
            )}
            <button className="button primary full-width" disabled={busy}>
              {busy ? (
                <>
                  <Loader2 className="spin" size={18} />
                  {tab === 'file' ? '正在上传视频…' : '正在创建笔记…'}
                </>
              ) : (
                <>
                  开始整理 <ArrowUpRight size={18} />
                </>
              )}
            </button>
            <p className="dialog-footnote">任务会在后台处理，你可以继续浏览其他笔记。</p>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
