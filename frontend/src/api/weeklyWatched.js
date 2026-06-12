const STORAGE_KEY = 'weekly_watched'
const ORDER_KEY = 'weekly_watched_order'
const SESSION_KEY = 'weekly_viewed_session'
const MIGRATED_KEY = 'weekly_watched_server_migrated_v1'
const WATCHED_API = '/api/weekly-watched'

export function normalizeWatchedIDs(ids) {
    const seen = new Set()
    const result = []

    for (const raw of ids || []) {
        const id = String(raw || '').trim().toUpperCase()
        if (!id || seen.has(id)) continue
        seen.add(id)
        result.push(id)
    }

    return result.sort()
}

function normalizeWatchedOrder(ids) {
    const seen = new Set()
    const result = []

    for (const raw of ids || []) {
        const id = String(raw || '').trim().toUpperCase()
        if (!id || seen.has(id)) continue
        seen.add(id)
        result.push(id)
    }

    return result
}

export function readLocalWatchedIDs() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY)
        const ids = raw ? JSON.parse(raw) : []
        return Array.isArray(ids) ? normalizeWatchedIDs(ids) : []
    } catch (e) {
        return []
    }
}

export function writeLocalWatchedIDs(ids) {
    const normalized = normalizeWatchedIDs(ids)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized))
    return normalized
}

export function readWatchedOrderIDs() {
    try {
        const raw = localStorage.getItem(ORDER_KEY)
        const ids = raw ? JSON.parse(raw) : []
        return Array.isArray(ids) ? normalizeWatchedOrder(ids) : []
    } catch (e) {
        return []
    }
}

export function writeWatchedOrderIDs(ids, watchedIDs = null) {
    const watchedSet = watchedIDs ? new Set(normalizeWatchedIDs(watchedIDs)) : null
    const normalized = normalizeWatchedOrder(ids)
        .filter(id => !watchedSet || watchedSet.has(id))
    localStorage.setItem(ORDER_KEY, JSON.stringify(normalized))
    return normalized
}

export function recordWatchedOrderID(id, watchedIDs = null) {
    const normalized = normalizeWatchedOrder([id])
    if (normalized.length === 0) return readWatchedOrderIDs()

    const target = normalized[0]
    const order = readWatchedOrderIDs().filter(item => item !== target)
    return writeWatchedOrderIDs([...order, target], watchedIDs)
}

export function reconcileWatchedOrderIDs(watchedIDs) {
    const watched = normalizeWatchedIDs(watchedIDs)
    const watchedSet = new Set(watched)
    const order = readWatchedOrderIDs().filter(id => watchedSet.has(id))
    const orderedSet = new Set(order)
    const missing = watched.filter(id => !orderedSet.has(id))
    return writeWatchedOrderIDs([...order, ...missing], watched)
}

function readSessionViewedIDs() {
    try {
        const raw = sessionStorage.getItem(SESSION_KEY)
        const ids = raw ? JSON.parse(raw) : []
        return Array.isArray(ids) ? normalizeWatchedIDs(ids) : []
    } catch (e) {
        return []
    }
}

function clearSessionViewedIDs() {
    try {
        sessionStorage.removeItem(SESSION_KEY)
    } catch (e) {}
}

function sameIDs(a, b) {
    const left = normalizeWatchedIDs(a)
    const right = normalizeWatchedIDs(b)
    return left.length === right.length && left.every((id, index) => id === right[index])
}

async function fetchServerWatchedIDs() {
    const resp = await fetch(WATCHED_API)
    if (!resp.ok) throw new Error('Failed to load watched list')

    const data = await resp.json()
    if (Array.isArray(data)) return normalizeWatchedIDs(data)
    if (Array.isArray(data?.ids)) return normalizeWatchedIDs(data.ids)
    return []
}

async function putServerWatchedIDs(ids) {
    const normalized = normalizeWatchedIDs(ids)
    const resp = await fetch(WATCHED_API, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: normalized })
    })

    if (!resp.ok) throw new Error('Failed to save watched list')
    return normalized
}

export async function syncWatchedIDs() {
    const localIDs = readLocalWatchedIDs()
    const sessionIDs = readSessionViewedIDs()

    let serverIDs
    try {
        serverIDs = await fetchServerWatchedIDs()
    } catch (e) {
        return {
            ids: writeLocalWatchedIDs([...localIDs, ...sessionIDs]),
            serverSynced: false
        }
    }

    const shouldMigrateLocal = localStorage.getItem(MIGRATED_KEY) !== 'true' && localIDs.length > 0
    const mergedIDs = normalizeWatchedIDs([
        ...serverIDs,
        ...(shouldMigrateLocal ? localIDs : []),
        ...sessionIDs
    ])

    writeLocalWatchedIDs(mergedIDs)

    try {
        if (shouldMigrateLocal || sessionIDs.length > 0 || !sameIDs(serverIDs, mergedIDs)) {
            await putServerWatchedIDs(mergedIDs)
        }
        localStorage.setItem(MIGRATED_KEY, 'true')
        if (sessionIDs.length > 0) clearSessionViewedIDs()
        return { ids: mergedIDs, serverSynced: true }
    } catch (e) {
        return { ids: mergedIDs, serverSynced: false }
    }
}

export async function saveWatchedIDs(ids) {
    const normalized = writeLocalWatchedIDs(ids)

    try {
        await putServerWatchedIDs(normalized)
        localStorage.setItem(MIGRATED_KEY, 'true')
        return { ids: normalized, serverSynced: true }
    } catch (e) {
        return { ids: normalized, serverSynced: false }
    }
}
