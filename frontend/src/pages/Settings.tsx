import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Circle, Cpu, Eye, FileText, RefreshCw } from 'lucide-react'
import { getCapabilities } from '../api/client'

export default function Settings() {
  const { data, error, refetch, isFetching } = useQuery({
    queryKey: ['capabilities'],
    queryFn: getCapabilities,
  })
  const configExample = [
    'KNOWDELTA_LLM_BASE_URL=你的服务地址',
    'KNOWDELTA_LLM_MODEL=文字模型名称',
    'KNOWDELTA_LLM_API_KEY=你的密钥',
    'KNOWDELTA_VISION_MODEL=视觉模型名称',
  ].join('\n')
  return (
    <div className="settings-page">
      <div className="eyebrow">WORKSPACE SETTINGS</div>
      <h1>整理方式，按需选择。</h1>
      <p className="page-description">查看当前可用的能力，为不同内容选择合适的阅读方式。</p>
      <div className="settings-panel">
        <header>
          <h2>处理能力</h2>
          <button className="button secondary small" onClick={() => refetch()}>
            <RefreshCw size={14} className={isFetching ? 'spin' : ''} />
            刷新状态
          </button>
        </header>
        {error && (
          <p role="alert" className="error-message">
            {error.message}
          </p>
        )}
        {[
          {
            title: '本地语音转写',
            icon: Cpu,
            ready: data?.asr_available,
            description: '视频没有字幕时，在本地识别语音。',
          },
          {
            title: '文字整理模型',
            icon: FileText,
            ready: data?.text_model_ready,
            description: data?.text_model || '配置后可按主题整理章节、重点和例子。',
          },
          {
            title: '视觉理解模型',
            icon: Eye,
            ready: data?.vision_model_ready,
            description: data?.vision_model || '配置后可结合真实画面选择配图、生成图注。',
          },
        ].map((item) => (
          <div className="capability-row" key={item.title}>
            <span className="capability-icon">
              <item.icon size={21} />
            </span>
            <div>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
            </div>
            <span className={'capability-status ' + (item.ready ? 'ready' : '')}>
              {item.ready ? <CheckCircle2 size={16} /> : <Circle size={16} />}
              {!data ? (error ? '暂不可用' : '读取中…') : item.ready ? '已就绪' : '未配置'}
            </span>
          </div>
        ))}
      </div>
      <div className="settings-help">
        <h3>如何配置模型？</h3>
        <p>
          在后端的配置文件中设置模型服务，重启 API
          和处理进程后刷新此页面。密钥保留在后端，不会发送到浏览器。
        </p>
        <pre>{configExample}</pre>
        <p>
          尚未配置模型时，仍可使用「原文整理」。模型模式会将字幕，或字幕与候选截图，发送至指定的服务。
        </p>
      </div>
    </div>
  )
}
