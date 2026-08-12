export function scrapeStatusMessage(status) {
  if (!status || typeof status !== 'object') return '正在读取刮削状态...'
  if (status.running) {
    const label = status.phase_label || '刮削中'
    const progress = status.progress || {}
    const current = Number(progress.current || 0)
    const total = Number(progress.total || 0)
    const code = String(progress.code || '').trim()
    const parts = [label]
    if (total > 0) parts.push(`${Math.min(current, total)}/${total}`)
    if (code) parts.push(code)
    return parts.join(' · ')
  }
  if (status.last_error) return `上次未完成：${status.last_error}`
  if (status.last_summary) return `上次完成：${status.last_summary}`
  return '当前空闲'
}
