import { ArrowUpRight, BookOpen, Clock3, FileText, Image, Loader2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Job } from '../api/client'
import { formatDate, formatTime, frameUrl, modeName, statusName } from '../api/client'

export default function JobCard({ job }: { job: Job }) {
  return (
    <Link to={'/notes/' + job.id} className="note-card">
      <div className={'note-cover ' + (job.cover_frame_id ? 'has-image' : '')}>
        {job.cover_frame_id ? (
          <img src={frameUrl(job.id, job.cover_frame_id)} alt="视频截图" loading="lazy" />
        ) : (
          <div className="cover-placeholder">
            <BookOpen size={44} strokeWidth={1} />
            <span>KNOWDELTA NOTES</span>
          </div>
        )}
        <span className="cover-source">{job.source_url ? 'bilibili' : '本地视频'}</span>
        {job.duration_ms > 0 && (
          <span className="cover-duration">{formatTime(job.duration_ms)}</span>
        )}
        <span className="cover-open">
          <ArrowUpRight size={19} />
        </span>
      </div>
      <div className="note-card-body">
        <div className="card-eyebrow">
          <span>{modeName(job.mode)}</span>
          <span className={'status-dot ' + job.status}>
            {job.status === 'running' && <Loader2 size={12} className="spin" />}
            {statusName(job.status)}
          </span>
        </div>
        <h3>{job.source_name}</h3>
        <p className="note-author">{job.author || (job.source_url ? 'B 站视频' : '本地视频')}</p>
        {job.status === 'running' || job.status === 'queued' ? (
          <div className="mini-progress">
            <span style={{ width: job.progress + '%' }} />
          </div>
        ) : (
          <div className="card-metadata">
            <span>
              <FileText size={13} />
              {job.section_count} 章节
            </span>
            <span>
              <Image size={13} />
              {job.image_count} 配图
            </span>
            <span className="card-date">
              <Clock3 size={13} />
              {formatDate(job.created_at)}
            </span>
          </div>
        )}
      </div>
    </Link>
  )
}
