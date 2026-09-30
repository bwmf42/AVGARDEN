export const selectionTabs = [
    ['unwatched', '未浏览'], ['watched', '浏览过'], ['want', '想看'],
    ['dismissed', '不感兴趣'], ['all', '全部']
]
const nameKey = value => String(value || '').normalize('NFKC').replace(/\s/g, '').toLowerCase()
export function durationMinutes(raw) {
    if (raw == null || raw === '') return null
    const text = String(raw).trim()
    if (/^\d+(\.\d+)?$/.test(text)) return Number(text) > 0 ? Number(text) : null
    const clock = text.match(/^(\d+):(\d{2})(?::(\d{2}))?$/)
    if (clock) return clock[3] == null ? Number(clock[1]) + Number(clock[2])/60 : Number(clock[1])*60 + Number(clock[2]) + Number(clock[3])/60
    const hours = text.match(/(\d+)\s*(?:小时|時間|hours?|h)/i)
    const mins = text.match(/(\d+)\s*(?:分钟|分鐘|分|minutes?|mins?|m)/i)
    return hours || mins ? Number(hours?.[1] || 0)*60 + Number(mins?.[1] || 0) : null
}
export function releaseDay(raw) {
    const match = String(raw || '').match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/)
    if (!match) return ''
    const date = `${match[1]}-${match[2].padStart(2,'0')}-${match[3].padStart(2,'0')}`
    const parsed = new Date(`${date}T00:00:00Z`)
    return !isNaN(parsed) && parsed.toISOString().slice(0,10) === date ? date : ''
}
export function filterWeekly(items, query = {}, selections = {}, favorites = []) {
    const include = String(query.include || '').split(',').filter(Boolean)
    const exclude = String(query.exclude || '').split(',').filter(Boolean)
    const fav = new Set(favorites.map(nameKey))
    const tab = query.tab || 'unwatched'
    const result = items.filter(item => {
        const state = selections[String(item.id).toUpperCase()]
        const interest = state?.interest || ''
        if (tab === 'want' && interest !== 'want') return false
        if (tab === 'dismissed' && interest !== 'dismissed') return false
        if (tab === 'unwatched' && (state || interest)) return false
        if (tab === 'watched' && (!state || interest === 'dismissed')) return false
        if (tab === 'all' && interest === 'dismissed') return false
        if (query.chinese === 'yes' && !item.hasChinese) return false
        if (query.chinese === 'unknown' && item.hasChinese) return false
        const actors = item.actresses || []
        if (query.actor && !actors.some(a => nameKey(a) === nameKey(query.actor))) return false
        if (query.fav === '1' && !actors.some(a => fav.has(nameKey(a)))) return false
        const genres = item.genres || []
        if (!include.every(g => genres.includes(g)) || exclude.some(g => genres.includes(g))) return false
        const minutes = durationMinutes(item.duration)
        if (query.duration === 'unknown' && minutes != null) return false
        if (query.duration === 'short' && (minutes == null || minutes > 90)) return false
        if (query.duration === 'medium' && (minutes == null || minutes <= 90 || minutes > 150)) return false
        if (query.duration === 'long' && (minutes == null || minutes <= 150)) return false
        const day = releaseDay(item.releaseDate)
        if (query.dateUnknown === '1' && day) return false
        if (query.from && (!day || day < query.from)) return false
        if (query.to && (!day || day > query.to)) return false
        if (query.availability === 'local' && !item.downloaded) return false
        if (query.availability === 'pending' && item.downloaded) return false
        if (query.availability === 'queued' && !item.queueStatus) return false
        return true
    })
    if (tab === 'watched' || tab === 'want' || tab === 'dismissed') {
        result.sort((a,b) => String(selections[b.id]?.watched_at || '').localeCompare(String(selections[a.id]?.watched_at || '')))
    }
    return result
}
export const BROWSE_KEY = 'weekly_selection_browse_v1'
export function saveBrowseContext(items, query, scroll = 0) {
    try { sessionStorage.setItem(BROWSE_KEY, JSON.stringify({ ids: items.map(v => v.id), query, scroll })) } catch {}
}
export function readBrowseContext() {
    try { return JSON.parse(sessionStorage.getItem(BROWSE_KEY) || 'null') } catch { return null }
}
