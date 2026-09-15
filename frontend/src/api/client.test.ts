import { describe, expect, it } from 'vitest'
import { errorMessage, formatTime, isActive, modeName } from './client'
import type { Job } from './client'

describe('API presentation boundary', () => {
  it('renders validation errors without exposing server objects', () => {
    expect(errorMessage({ detail: [{ msg: 'invalid' }] })).toBe('请检查输入的地址和选项后重试。')
    expect(errorMessage({ detail: '模型未配置' })).toBe('模型未配置')
  })
  it('supports timestamps beyond one hour', () => {
    expect(formatTime(3_665_000)).toBe('61:05')
  })
  it('polls only jobs which are still active', () => {
    expect(isActive({ status: 'running' } as Job)).toBe(true)
    expect(isActive({ status: 'completed' } as Job)).toBe(false)
    expect(modeName('vision')).toBe('图文精读')
  })
})
