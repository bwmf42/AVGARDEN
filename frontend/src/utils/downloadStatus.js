export function isCloudTask(item) {
  return item?.target === '115' || item?.transport === '115'
}

export function downloadChannel(item) {
  if (isCloudTask(item)) return '115'
  if (item?.transport === 'online') return '在线流'
  if (item?.transport === 'qb') return 'qB'
  return '本地'
}

export function downloadStatusText(item) {
  if (item.status === 'failed') return '失败'
  if (item.status === 'submitted_to_115') return '已提交 115 云端'
  const channel = downloadChannel(item)
  if (item.status === 'queued') return `${channel} · ${isCloudTask(item) ? '等待提交' : '等待中'}`
  if (item.status === 'downloading') {
    if (isCloudTask(item)) return `115 · ${item.phase === 'resolving' ? '查找磁链' : '提交中'}`
    return `${channel} · ${item.transport ? '下载中' : '选源中'}`
  }
  return item.status === 'done' ? '完成' : item.status
}

export function failureReason(item, max = 24) {
  const full = String(item?.message ?? '').trim()
  if (!full) return { text: '', full: '' }
  const chars = Array.from(full)
  return { text: chars.length > max ? `${chars.slice(0, max).join('')}…` : full, full }
}
