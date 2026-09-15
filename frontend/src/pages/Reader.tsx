import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as Dialog from '@radix-ui/react-dialog'
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Download,
  ExternalLink,
  FileText,
  Image,
  Info,
  Loader2,
  Maximize2,
  Play,
  RotateCcw,
  Square,
  X,
} from 'lucide-react'
import {
  client,
  downloadUrl,
  errorMessage,
  formatTime,
  frameUrl,
  getJob,
  getNote,
  isActive,
  modeName,
  statusName,
  videoUrl,
} from '../api/client'
import type { Job, NoteData } from '../api/client'

const steps = [
  { id: 'acquire', title: '获取视频素材', text: '读取视频与可用字幕' },
  { id: 'transcript', title: '听懂视频内容', text: '整理字幕，或识别视频语音' },
  { id: 'frames', title: '留下关键画面', text: '筛选清晰、不同的截图' },
  { id: 'section', title: '整理图文笔记', text: '组织章节、段落与来源' },
  { id: 'export', title: '准备阅读与导出', text: '检查图片和时间引用' },
]

function Processing({ job }: { job: Job }) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: async (action: 'cancel' | 'retry') => {
      const path =
        action === 'cancel' ? '/api/v1/jobs/{job_id}/cancel' : '/api/v1/jobs/{job_id}/retry'
      const { data, error } = await client.POST(path, { params: { path: { job_id: job.id } } })
      if (error || !data) throw new Error(errorMessage(error))
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['job', job.id] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
  const active = isActive(job)
  const index = job.stage === 'outline' ? 3 : steps.findIndex((step) => step.id === job.stage)
  return (
    <div className="processing-page">
      <Link to="/" className="back-link">
        <ArrowLeft size={16} />
        返回笔记库
      </Link>
      <div className="processing-card">
        <div className={'processing-symbol ' + (active ? 'active' : '')}>
          {active ? <BookOpen size={32} strokeWidth={1.3} /> : <Info size={30} />}
        </div>
        <div className="eyebrow">
          {active ? 'A LITTLE PATIENCE, A LOT TO LEARN' : 'YOUR PROGRESS IS SAVED'}
        </div>
        <h1>
          {job.status === 'queued'
            ? '视频已收到，等待开始。'
            : job.status === 'running'
              ? '正在为你整理这段视频。'
              : statusName(job.status)}
        </h1>
        <p>
          {active
            ? '你可以离开这个页面，完成后在笔记库继续阅读。'
            : job.error || '已完成的处理结果会保留，可随时继续。'}
        </p>
        <div className="processing-track">
          <span style={{ width: job.progress + '%' }} />
        </div>
        <div className="progress-caption">
          <span>{modeName(job.mode)}</span>
          <span>{active ? '按阶段展示进度' : '已保留处理记录'}</span>
        </div>
        <ol className="processing-steps">
          {steps.map((step, i) => (
            <li
              key={step.id}
              className={i < index ? 'done' : i === index && active ? 'current' : ''}
            >
              <span className="step-number">
                {i < index ? (
                  <Check size={16} />
                ) : i === index && active ? (
                  <Loader2 size={16} className="spin" />
                ) : (
                  i + 1
                )}
              </span>
              <div>
                <strong>{step.title}</strong>
                <span>{step.text}</span>
              </div>
            </li>
          ))}
        </ol>
        {mutation.error && (
          <p className="error-message" role="alert">
            {mutation.error.message}
          </p>
        )}
        <button
          className="button secondary"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate(active ? 'cancel' : 'retry')}
        >
          {active ? <Square size={14} /> : <RotateCcw size={15} />}
          {mutation.isPending ? '正在处理…' : active ? '取消本次整理' : '继续重试'}
        </button>
      </div>
    </div>
  )
}

function NoteReader({ data }: { data: NoteData }) {
  const { job, note, transcript, frames } = data
  const [activeSection, setActiveSection] = useState(0)
  const [tab, setTab] = useState<'note' | 'transcript'>('note')
  const [focus, setFocus] = useState(false)
  const [lightbox, setLightbox] = useState<string | null>(null)
  const [playerError, setPlayerError] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [seekError, setSeekError] = useState('')
  const player = useRef<HTMLVideoElement>(null)
  const segments = new Map(transcript.segments.map((segment) => [segment.segment_id, segment]))
  const frameMap = new Map(frames.map((frame) => [frame.frame_id, frame]))
  const ranges = note.sections.map((section) => {
    const evidence = section.paragraphs
      .flatMap((paragraph) => paragraph.source_segment_ids.map((id) => segments.get(id)))
      .filter((item) => item !== undefined)
    return {
      start: Math.min(...evidence.map((item) => item.start_ms)),
      end: Math.max(...evidence.map((item) => item.end_ms)),
    }
  })
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries)
          if (entry.isIntersecting)
            setActiveSection(Number((entry.target as HTMLElement).dataset.index))
      },
      { rootMargin: '-100px 0px -60% 0px' },
    )
    document.querySelectorAll('.article-section').forEach((section) => observer.observe(section))
    return () => observer.disconnect()
  }, [tab, note])
  async function seek(ms: number) {
    setSeekError('')
    if (!player.current || playerError) {
      if (job.source_url)
        window.open(job.source_url + '&t=' + Math.floor(ms / 1000), '_blank', 'noopener,noreferrer')
      else setSeekError('视频暂不可播放，请在本地播放器定位到 ' + formatTime(ms))
      return
    }
    try {
      player.current.currentTime = ms / 1000
      await player.current.play()
    } catch {
      setSeekError('已定位到 ' + formatTime(ms) + '，请点击播放器继续。')
    }
  }
  function jump(index: number) {
    setTab('note')
    setActiveSection(index)
    setTimeout(
      () =>
        document
          .getElementById('chapter-' + index)
          ?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
      0,
    )
  }
  return (
    <div className={'reader-page ' + (focus ? 'focus-mode' : '')}>
      <div className="reader-toolbar">
        <Link to="/" className="back-link">
          <ArrowLeft size={16} />
          我的笔记
        </Link>
        <div>
          <button className="button ghost small" onClick={() => setFocus(!focus)}>
            <BookOpen size={15} />
            {focus ? '退出专注' : '专注阅读'}
          </button>
          <details className="download-menu">
            <summary className="button primary small">
              <Download size={15} />
              导出笔记
              <ChevronDown size={13} />
            </summary>
            <div>
              <a href={downloadUrl(job.id, 'zip')}>完整图文包 · ZIP</a>
              <a href={downloadUrl(job.id, 'md')}>文字与图片引用 · Markdown</a>
              <a href={downloadUrl(job.id, 'html')}>网页文件 · HTML</a>
            </div>
          </details>
        </div>
      </div>
      <div className="reader-heading">
        <div className="reader-tags">
          <span>{job.source_url ? 'BILIBILI' : 'LOCAL VIDEO'}</span>
          <span>{modeName(job.mode)}</span>
          <span>
            <CheckCircle2 size={13} />
            已完成
          </span>
        </div>
        <h1>{note.title}</h1>
        <div className="reader-meta">
          <span className="author-avatar">{job.author.slice(0, 1) || 'K'}</span>
          <span>{job.author || '本地视频'}</span>
          <span className="meta-divider" />
          <span>
            <Clock3 size={14} />
            {formatTime(job.duration_ms)}
          </span>
          <span>
            <FileText size={14} />
            {note.sections.length} 章节
          </span>
          <span>
            <Image size={14} />
            {frames.length} 张配图
          </span>
        </div>
      </div>
      <div className="reader-columns">
        <aside className="video-column">
          <div className="video-panel">
            {data.video_available && !playerError ? (
              <video
                ref={player}
                controls
                preload="metadata"
                src={videoUrl(job.id)}
                poster={job.cover_frame_id ? frameUrl(job.id, job.cover_frame_id) : undefined}
                onError={() => setPlayerError(true)}
                onTimeUpdate={() => setCurrentTime((player.current?.currentTime || 0) * 1000)}
              />
            ) : (
              <div className="video-fallback">
                <Play size={30} />
                <p>{playerError ? '当前浏览器无法播放该视频格式' : '原视频不在本地'}</p>
                {job.source_url && (
                  <a href={job.source_url} target="_blank" rel="noreferrer">
                    前往 B 站观看 <ExternalLink size={14} />
                  </a>
                )}
              </div>
            )}
            <div className="video-caption">
              <span>
                <span className="live-dot on" />
                原视频对照
              </span>
              {job.source_url && (
                <a href={job.source_url} target="_blank" rel="noreferrer">
                  在 B 站打开
                  <ArrowUpRight size={13} />
                </a>
              )}
            </div>
          </div>
          {seekError && (
            <p role="status" className="seek-error">
              {seekError}
            </p>
          )}
          <div className="toc">
            <div className="toc-heading">
              <span>内容目录</span>
              <small>{note.sections.length} CHAPTERS</small>
            </div>
            {note.sections.map((section, index) => (
              <button
                key={index}
                onClick={() => jump(index)}
                className={activeSection === index ? 'active' : ''}
              >
                <span className="toc-number">{(index + 1).toString().padStart(2, '0')}</span>
                <span>
                  {section.title}
                  <small>
                    {formatTime(ranges[index].start)} – {formatTime(ranges[index].end)}
                  </small>
                </span>
                <ChevronDown size={13} />
              </button>
            ))}
          </div>
          <div className="reading-tip">
            <Info size={16} />
            <p>点击段落旁的时间，回到视频中的那一刻。知识与出处，始终在一起。</p>
          </div>
        </aside>
        <div className="article-column">
          <div className="article-tabs">
            <button className={tab === 'note' ? 'active' : ''} onClick={() => setTab('note')}>
              <BookOpen size={16} />
              图文笔记
            </button>
            <button
              className={tab === 'transcript' ? 'active' : ''}
              onClick={() => setTab('transcript')}
            >
              <FileText size={16} />
              原始转写
            </button>
            <span>可追溯的学习记录</span>
          </div>
          {(note.warnings || []).length > 0 && (
            <details className="note-notice">
              <summary>
                <Info size={15} />
                {note.mode === 'extractive'
                  ? '原文整理 · 保留转写内容，配图按时间匹配'
                  : 'AI 整理内容 · 结合原视频核对'}
                <ChevronDown size={14} />
              </summary>
              <ul>
                {(note.warnings || []).map((warning, i) => (
                  <li key={i}>{warning}</li>
                ))}
              </ul>
            </details>
          )}
          {tab === 'note' ? (
            <article className="note-article">
              {note.sections.map((section, index) => (
                <section
                  className="article-section"
                  data-index={index}
                  id={'chapter-' + index}
                  key={index}
                >
                  <div className="chapter-eyebrow">
                    <span>CHAPTER {(index + 1).toString().padStart(2, '0')}</span>
                    <button onClick={() => seek(ranges[index].start)}>
                      <Play size={11} />
                      {formatTime(ranges[index].start)}
                    </button>
                  </div>
                  <h2>{section.title}</h2>
                  {section.paragraphs.map((paragraph, i) => {
                    const first = Math.min(
                      ...paragraph.source_segment_ids.map((id) => segments.get(id)?.start_ms ?? 0),
                    )
                    return (
                      <div className="note-paragraph" key={i}>
                        <p>{paragraph.text}</p>
                        <button
                          className="timestamp-link"
                          onClick={() => seek(first)}
                          aria-label={'跳转视频 ' + formatTime(first)}
                        >
                          <Play size={10} />
                          {formatTime(first)}
                        </button>
                      </div>
                    )
                  })}
                  {(section.images || []).map((image) => (
                    <figure key={image.frame_id}>
                      <button
                        className="figure-button"
                        onClick={() => setLightbox(image.frame_id)}
                        aria-label="放大查看视频截图"
                      >
                        <img
                          src={frameUrl(job.id, image.frame_id)}
                          loading="lazy"
                          alt={image.caption}
                        />
                        <span>
                          <Maximize2 size={16} />
                        </span>
                      </button>
                      <figcaption>
                        <span>{image.caption}</span>
                        <button
                          onClick={() => seek(frameMap.get(image.frame_id)?.timestamp_ms || 0)}
                        >
                          <Play size={11} />
                          {formatTime(frameMap.get(image.frame_id)?.timestamp_ms || 0)}
                        </button>
                      </figcaption>
                    </figure>
                  ))}
                </section>
              ))}
            </article>
          ) : (
            <div className="transcript-list">
              {transcript.segments.map((segment) => (
                <button
                  key={segment.segment_id}
                  className={
                    currentTime >= segment.start_ms && currentTime < segment.end_ms ? 'active' : ''
                  }
                  onClick={() => seek(segment.start_ms)}
                >
                  <span>{formatTime(segment.start_ms)}</span>
                  <p>{segment.text}</p>
                </button>
              ))}
            </div>
          )}
          <footer className="article-end">
            <span>✳</span>
            <p>读到这里，让理解再深一点。</p>
            <Link to="/">
              回到我的笔记 <ArrowUpRight size={14} />
            </Link>
          </footer>
        </div>
      </div>
      <Dialog.Root
        open={!!lightbox}
        onOpenChange={(open) => {
          if (!open) setLightbox(null)
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay image-overlay" />
          <Dialog.Content className="image-dialog">
            <Dialog.Title className="sr-only">视频截图</Dialog.Title>
            <Dialog.Description className="sr-only">原视频中的关键画面</Dialog.Description>
            <Dialog.Close className="image-close icon-button" aria-label="关闭截图">
              <X size={23} />
            </Dialog.Close>
            {lightbox && <img src={frameUrl(job.id, lightbox)} alt="原视频截图大图" />}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  )
}

export default function Reader() {
  const { id = '' } = useParams()
  const jobQuery = useQuery({
    queryKey: ['job', id],
    queryFn: () => getJob(id),
    refetchInterval: (query) => (query.state.data && isActive(query.state.data) ? 1500 : false),
  })
  const noteQuery = useQuery({
    queryKey: ['note', id],
    queryFn: () => getNote(id),
    enabled: jobQuery.data?.status === 'completed',
  })
  if (jobQuery.error || noteQuery.error)
    return (
      <div className="empty-state">
        <Info size={28} />
        <h2>暂时无法打开这份笔记</h2>
        <p role="alert">{jobQuery.error?.message || noteQuery.error?.message}</p>
        <button
          className="button secondary"
          onClick={() => {
            jobQuery.refetch()
            if (jobQuery.data?.status === 'completed') noteQuery.refetch()
          }}
        >
          重新加载
        </button>
      </div>
    )
  if (!jobQuery.data)
    return (
      <div className="reader-loading">
        <Loader2 size={26} className="spin" />
        <span>正在打开笔记…</span>
      </div>
    )
  if (jobQuery.data.status !== 'completed') return <Processing job={jobQuery.data} />
  if (!noteQuery.data)
    return (
      <div className="reader-loading">
        <Loader2 size={26} className="spin" />
        <span>正在加载图文内容…</span>
      </div>
    )
  return <NoteReader key={id} data={noteQuery.data} />
}
