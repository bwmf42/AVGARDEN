export async function loadSelections() {
    const response = await fetch('/api/weekly-selection', { cache: 'no-store' })
    if (!response.ok) throw new Error('浏览选择加载失败，请重试')
    return response.json()
}
export async function selectWeekly(id, action) {
    const response = await fetch('/api/weekly-selection', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, action })
    })
    if (!response.ok) throw new Error(response.status === 404 ? '该作品已不在每日推荐中，请刷新列表' : '保存失败，请重试')
    const result = await response.json()
    window.dispatchEvent(new CustomEvent('av-garden-selection', { detail: result }))
    return result
}
