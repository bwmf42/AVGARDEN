export function filterBlockedVideos(items, { actresses = [], genres = [] } = {}) {
    return items.filter(item =>
        !item.actresses?.some(name => actresses.includes(name)) &&
        !item.genres?.some(name => genres.includes(name)))
}

// Keep the original browsing order when several blocked titles disappear together.
export function nextRemainingVideo(previous, currentId, remaining) {
    const ids = new Set(remaining.map(item => item.id))
    const index = previous.findIndex(item => item.id === currentId)
    for (let offset = 1; offset <= previous.length; offset++) {
        const item = previous[(index + offset) % previous.length]
        if (ids.has(item.id)) return remaining.find(candidate => candidate.id === item.id)
    }
    return remaining[0]
}
