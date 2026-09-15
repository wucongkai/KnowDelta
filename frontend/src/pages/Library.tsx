import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronRight,
  CirclePlay,
  Clock3,
  FileText,
  LayoutGrid,
  List,
  Plus,
  Search,
  Sparkles,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatTime, listJobs } from '../api/client'
import JobCard from '../components/JobCard'

export default function Library({
  onImport,
  activeOnly = false,
}: {
  onImport: () => void
  activeOnly?: boolean
}) {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [view, setView] = useState<'grid' | 'list'>('grid')
  const {
    data: jobs = [],
    isPending,
    error,
    refetch,
  } = useQuery({ queryKey: ['jobs'], queryFn: listJobs, refetchInterval: 3000 })
  const completed = jobs.filter((job) => job.status === 'completed')
  const active = jobs.filter((job) => ['queued', 'running'].includes(job.status))
  const totalMinutes = Math.round(completed.reduce((sum, job) => sum + job.duration_ms, 0) / 60000)
  const filtered = useMemo(
    () =>
      jobs.filter(
        (job) =>
          (!activeOnly || ['queued', 'running'].includes(job.status)) &&
          (filter === 'all' ||
            (filter === 'running'
              ? ['queued', 'running'].includes(job.status)
              : filter === 'failed'
                ? ['failed', 'cancelled'].includes(job.status)
                : job.status === filter)) &&
          (job.source_name + ' ' + job.author).toLowerCase().includes(search.toLowerCase()),
      ),
    [jobs, activeOnly, filter, search],
  )
  return (
    <div className="library-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR LEARNING SPACE</div>
          <h1>{activeOnly ? '正在整理' : '让看过的，成为学会的。'}</h1>
          <p>
            {activeOnly
              ? '每一次整理，都在为下一次理解做准备。'
              : '把视频中的灵感和知识，留在自己的笔记里。'}
          </p>
        </div>
        <div className="heading-mark">
          <BookOpen size={28} strokeWidth={1.3} />
          <span>
            一点一滴
            <br />
            皆有所得
          </span>
        </div>
      </div>
      {!activeOnly && (
        <section className="import-banner">
          <div className="banner-grid" aria-hidden="true" />
          <div className="banner-content">
            <span className="banner-kicker">
              <span />
              从一段视频开始
            </span>
            <h2>好内容，值得慢慢读。</h2>
            <p>
              粘贴 B 站链接，或上传本地视频。
              <br />
              让每个重点都有文字，每个画面都有出处。
            </p>
            <button className="button banner-button" onClick={onImport}>
              <Plus size={17} /> 新建视频笔记 <ArrowUpRight size={17} />
            </button>
            <span className="banner-support">
              Bilibili <span>·</span> 本地视频 <span>·</span> Markdown 导出
            </span>
          </div>
          <div className="paper-scene" aria-hidden="true">
            <div className="paper-back" />
            <div className="paper-front">
              <div className="paper-top">
                <span>VIDEO → NOTES</span>
                <BookOpen size={15} />
              </div>
              <div className="paper-title">把知识，留在纸上。</div>
              <div className="paper-line long" />
              <div className="paper-line" />
              <div className="paper-visual">
                <div className="diagram-box">看见</div>
                <ChevronRight size={18} />
                <div className="diagram-box filled">理解</div>
                <ChevronRight size={18} />
                <div className="diagram-box">记住</div>
              </div>
              <div className="paper-line long" />
              <div className="paper-line short" />
              <div className="paper-bottom">
                <span>
                  <Check size={12} /> 保留每个知识的来源
                </span>
                <span>01 / 04</span>
              </div>
            </div>
            <div className="float-label">
              <Sparkles size={14} /> 让学习发生
            </div>
          </div>
        </section>
      )}
      <div className="stats-strip">
        <div>
          <span className="stat-icon">
            <BookOpen size={19} />
          </span>
          <strong>{completed.length.toString().padStart(2, '0')}</strong>
          <span>篇视频笔记</span>
        </div>
        <div>
          <span className="stat-icon">
            <Clock3 size={19} />
          </span>
          <strong>{totalMinutes.toString().padStart(2, '0')}</strong>
          <span>分钟学习素材</span>
        </div>
        <div>
          <span className="stat-icon">
            <FileText size={19} />
          </span>
          <strong>
            {completed
              .reduce((sum, job) => sum + job.section_count, 0)
              .toString()
              .padStart(2, '0')}
          </strong>
          <span>个内容章节</span>
        </div>
        <div className="stat-processing">
          <span className={'live-dot ' + (active.length ? 'on' : '')} />
          {active.length ? active.length + ' 个任务正在整理' : '准备好开始下一次学习'}
        </div>
      </div>
      <section className="library-section">
        <div className="section-heading">
          <div>
            <h2>
              {activeOnly ? '处理任务' : '我的笔记'}
              <span className="count-badge">{filtered.length}</span>
            </h2>
            <p>{activeOnly ? '关闭页面后，后台仍会继续处理。' : '每一次回看，都有新的收获。'}</p>
          </div>
          <div className="library-tools">
            <label className="search-box">
              <Search size={16} />
              <input
                aria-label="搜索笔记"
                placeholder="搜索笔记或作者"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <div className="view-switch">
              <button
                aria-label="网格视图"
                aria-pressed={view === 'grid'}
                className={view === 'grid' ? 'selected' : ''}
                onClick={() => setView('grid')}
              >
                <LayoutGrid size={16} />
              </button>
              <button
                aria-label="列表视图"
                aria-pressed={view === 'list'}
                className={view === 'list' ? 'selected' : ''}
                onClick={() => setView('list')}
              >
                <List size={18} />
              </button>
            </div>
          </div>
        </div>
        {!activeOnly && (
          <div className="filter-tabs">
            {[
              ['all', '全部笔记'],
              ['completed', '已完成'],
              ['running', '整理中'],
              ['failed', '需处理'],
            ].map(([value, label]) => (
              <button
                key={value}
                className={filter === value ? 'active' : ''}
                onClick={() => setFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>
        )}
        {error ? (
          <div className="empty-state">
            <p role="alert">暂时无法连接笔记库</p>
            <small>{error.message}</small>
            <button className="button secondary" onClick={() => refetch()}>
              重新连接
            </button>
          </div>
        ) : isPending ? (
          <div className="notes-grid">
            {[1, 2, 3].map((i) => (
              <div key={i} className="skeleton-card" />
            ))}
          </div>
        ) : filtered.length ? (
          view === 'grid' ? (
            <div className="notes-grid">
              {filtered.map((job) => (
                <JobCard key={job.id} job={job} />
              ))}
              {!activeOnly && !search && filter === 'all' && (
                <button className="new-note-card" onClick={onImport}>
                  <span>
                    <Plus size={24} strokeWidth={1.5} />
                  </span>
                  <strong>下一篇，想学什么？</strong>
                  <p>把值得记录的视频放进来</p>
                  <span className="text-link">
                    新建笔记 <ArrowUpRight size={14} />
                  </span>
                </button>
              )}
            </div>
          ) : (
            <div className="notes-list">
              {filtered.map((job) => (
                <Link key={job.id} to={'/notes/' + job.id}>
                  <span className="list-icon">
                    <CirclePlay size={22} />
                  </span>
                  <div>
                    <h3>{job.source_name}</h3>
                    <p>
                      {job.author || '视频笔记'} · {job.section_count} 章节
                    </p>
                  </div>
                  <span>{formatTime(job.duration_ms)}</span>
                  <ArrowUpRight size={18} />
                </Link>
              ))}
            </div>
          )
        ) : (
          <div className="empty-state">
            <BookOpen size={34} strokeWidth={1.2} />
            <h3>
              {search
                ? '没有找到这篇笔记'
                : activeOnly
                  ? '目前没有正在处理的任务'
                  : filter !== 'all'
                    ? '这个分类暂时没有笔记'
                    : '你的第一篇笔记，从这里开始'}
            </h3>
            <p>
              {search ? '试试其他标题或作者关键词。' : '导入一段视频，开始积累自己的学习资料。'}
            </p>
            <button className="button secondary" onClick={onImport}>
              <Plus size={16} />
              新建笔记
            </button>
          </div>
        )}
      </section>
      <footer className="page-footer">
        <span>KNOWDELTA · 知微</span>
        <span>把时间花在理解上。</span>
      </footer>
    </div>
  )
}
