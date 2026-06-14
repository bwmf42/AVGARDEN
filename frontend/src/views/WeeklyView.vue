<template>
    <div class="container">
        <div class="tabs">
            <span class="tab active">每日推荐 ({{ weeklyCount }})</span>
        </div>

        <div class="sub-tabs">
            <button :class="['sub-tab', { active: !showWatched }]" @click="setWatchedTab(false)">
                未看 ({{ unwatchedCount }})
            </button>
            <button :class="['sub-tab', { active: showWatched }]" @click="setWatchedTab(true)">
                已看 ({{ watchedInListCount }})
            </button>
        </div>

        <div v-if="loading" class="loading">加载中...</div>
        
        <div v-else class="video-grid">
            <template v-for="video in filteredVideos" :key="video.id">
                <div class="video-card" @click="openVideo(video)">
                    <div class="cover-container" :class="{ watched: isWatched(video.id) }">
                        <img class="cover" :src="video.cover || getDmmFallback(video)" :alt="video.title" loading="lazy">
                        <div v-if="isWatched(video.id)" class="watched-overlay">已看</div>
                        <div v-if="video.hasChinese" class="badge chinese">中文</div>
                        <button class="watch-toggle" @click.stop="toggleWatch(video.id)" :title="isWatched(video.id) ? '标记未看' : '标记已看'">
                            {{ isWatched(video.id) ? '已' : '看' }}
                        </button>
                    </div>
                    <div class="info">
                        <h3>{{ displayTitle(video) }}</h3>
                        <div v-if="video.actresses && video.actresses.length" class="actresses">
                            {{ video.actresses.slice(0, 2).join(' / ') }}
                        </div>
                    </div>
                </div>
            </template>
        </div>
    </div>
</template>

<script>
import {
    normalizeWatchedIDs,
    readWatchedOrderIDs,
    readLocalWatchedIDs,
    recordWatchedOrderID,
    saveWatchedIDs,
    syncWatchedIDs,
    writeWatchedOrderIDs
} from '../api/weeklyWatched'

function normalizeID(id) {
    return String(id || '').trim().toUpperCase()
}

export default {
    name: 'WeeklyView',
    data() {
        return {
            weeklyItems: [],
            loading: true,
            watchedSet: new Set(),
            watchedOrder: [],
            queueSet: new Set(),
            showWatched: false
        }
    },
    computed: {
        undownloadedVideos() {
            return this.weeklyItems.filter(v => !v.downloaded && !this.queueSet.has(v.id))
        },
        unwatchedVideos() {
            return this.undownloadedVideos.filter(v => !this.isWatched(v.id))
        },
        watchedInList() {
            const videos = this.undownloadedVideos.filter(v => this.isWatched(v.id))
            if (!this.watchedOrder.length) return videos

            const orderIndex = new Map(this.watchedOrder.map((id, index) => [id, index]))
            return [...videos].sort((a, b) => {
                const ai = orderIndex.get(normalizeID(a.id))
                const bi = orderIndex.get(normalizeID(b.id))
                const aKnown = ai !== undefined
                const bKnown = bi !== undefined

                if (aKnown && bKnown) return bi - ai
                if (aKnown) return -1
                if (bKnown) return 1
                return 0
            })
        },
        filteredVideos() {
            return this.showWatched ? this.watchedInList : this.unwatchedVideos
        },
        weeklyCount() { return this.undownloadedVideos.length },
        unwatchedCount() { return this.unwatchedVideos.length },
        watchedInListCount() { return this.watchedInList.length },
    },
    async created() {
        this.applyRouteTab()
        await this.syncWatched()
        await this.loadData()
    },
    async activated() {
        this.applyRouteTab()
        await this.syncWatched()
        await this.loadData()
    },
    watch: {
        '$route.query.tab'() {
            this.applyRouteTab()
        }
    },
    methods: {
        applyRouteTab() {
            this.showWatched = this.$route.query.tab === 'watched'
        },
        applyWatchedIDs(ids) {
            const normalized = normalizeWatchedIDs(ids)
            this.watchedSet = new Set(normalized)
            this.watchedOrder = writeWatchedOrderIDs(readWatchedOrderIDs(), normalized)
        },
        loadWatched() {
            this.applyWatchedIDs(readLocalWatchedIDs())
        },
        async syncWatched() {
            const result = await syncWatchedIDs()
            this.applyWatchedIDs(result.ids)
        },
        async saveWatched() {
            const result = await saveWatchedIDs([...this.watchedSet])
            this.applyWatchedIDs(result.ids)
        },
        isWatched(id) {
            return this.watchedSet.has(id)
        },
        async toggleWatch(id) {
            const nextSet = new Set(this.watchedSet)
            if (nextSet.has(id)) {
                nextSet.delete(id)
            } else {
                nextSet.add(id)
                this.watchedOrder = recordWatchedOrderID(id, [...nextSet])
            }
            if (!nextSet.has(id)) {
                this.watchedOrder = writeWatchedOrderIDs(this.watchedOrder, [...nextSet])
            }
            this.watchedSet = nextSet
            await this.saveWatched()
        },
        async loadData() {
            this.loading = true
            try {
                const [wResp, qResp] = await Promise.all([
                    fetch('/api/weekly'),
                    fetch('/api/queue/')
                ])
                if (wResp.ok) this.weeklyItems = await wResp.json()
                if (qResp.ok) {
                    const qItems = await qResp.json()
                    this.queueSet = new Set(qItems.map(i => i.code))
                }
            } catch (e) {
                console.error(e)
            }
            this.loading = false
        },
        displayTitle(video) {
            let t = video.titleZh || video.title
            // 如果标题以番号开头，不重复拼接
            const avid = video.id || ''
            if (avid && t.toUpperCase().startsWith(avid.toUpperCase())) {
                // 标题已含番号，直接截断
            } else {
                t = avid + ' ' + t
            }
            return t.length > 50 ? t.slice(0, 50) + '...' : t
        },
        getDmmFallback(video) {
            const c = (video.id || '').toLowerCase().replace('-', '')
            return c ? `https://pics.dmm.co.jp/mono/movie/adult/${c}/${c}pl.jpg` : ''
        },
        openVideo(video) {
            if (video.downloaded) {
                this.$router.push({ name: 'detail', params: { id: video.id } })
            } else {
                const tab = this.showWatched ? 'watched' : 'unwatched'
                this.$router.push({ name: 'weekly-detail', params: { id: video.id }, query: { tab } })
            }
        },
        async flushSessionViews() {
            await this.syncWatched()
        },
        setWatchedTab(val) {
            this.showWatched = val
            const tab = val ? 'watched' : undefined
            this.$router.replace({ name: 'weekly', query: tab ? { tab } : {} })
        },
        markWatched(id) {
            if (!this.watchedSet.has(id)) {
                this.watchedSet.add(id)
                this.watchedOrder = recordWatchedOrderID(id, [...this.watchedSet])
                this.saveWatched()
                this.watchedSet = new Set(this.watchedSet)
            }
        },
    }
}
</script>

<style scoped>
.container { padding: 0; }
.tabs { display: flex; gap: 10px; margin-bottom: 1rem; }
.tab { padding: 9px 14px; border: 1px solid var(--rose-line); background: var(--surface); color: var(--secondary-color); border-radius: 8px; cursor: default; font-size: 14px; font-weight: 800; text-decoration: none; display: inline-block; box-shadow: var(--shadow-soft); }
.tab.active { border-top: 3px solid var(--primary-color); padding-top: 7px; }
.sub-tabs { display: flex; gap: 8px; margin-bottom: 1rem; }
.sub-tab { padding: 7px 12px; border: 1px solid var(--line); background: var(--surface); color: var(--muted-color); border-radius: 999px; cursor: pointer; font-size: 12px; font-weight: 700; transition: all 0.18s ease; }
.sub-tab.active { background: var(--secondary-color); color: white; border-color: var(--secondary-color); }
.loading { text-align: center; color: var(--muted-color); padding: 40px; font-size: 15px; }
.video-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 18px; padding: 12px 0; }
.video-card { cursor: pointer; transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease; background: var(--surface); border-radius: 8px; overflow: hidden; border: 1px solid var(--line); box-shadow: var(--shadow-soft); position: relative; }
.video-card::before { content: ''; position: absolute; inset: 0 0 auto; height: 3px; background: var(--primary-color); z-index: 3; }
.video-card:hover { transform: translateY(-2px); border-color: var(--rose-line); box-shadow: var(--shadow-hover); }
.cover-container { position: relative; width: 100%; padding-top: 66.67%; overflow: hidden; background: #f7eef3; }
.cover-container.watched { opacity: 0.55; }
.cover { position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: contain; }

/* Badges */
.badge { position: absolute; padding: 4px 8px; border-radius: 999px; font-size: 11px; font-weight: 800; z-index: 2; }
.badge.downloaded { bottom: 8px; right: 8px; background: rgba(40, 122, 67, 0.9); color: white; }
.badge.undownloaded { bottom: 8px; right: 8px; background: rgba(186, 47, 93, 0.9); color: white; }
.badge.chinese { top: 8px; left: 8px; background: rgba(161, 92, 0, 0.9); color: white; }

/* Watched overlay */
.watched-overlay { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); padding: 6px 14px; border-radius: 999px; font-size: 13px; font-weight: 800; background: rgba(53,36,44,0.72); color: white; z-index: 3; pointer-events: none; letter-spacing: 0; }

/* Watch toggle button */
.watch-toggle { position: absolute; top: 8px; right: 8px; min-width: 28px; height: 28px; border-radius: 999px; border: 1px solid rgba(255,255,255,0.7); background: rgba(255,255,255,0.88); color: var(--secondary-color); font-size: 12px; font-weight: 800; cursor: pointer; z-index: 5; display: flex; align-items: center; justify-content: center; padding: 0 8px; line-height: 1; transition: all 0.18s ease; }
.watch-toggle:hover { background: white; transform: translateY(-1px); }

.info { padding: 12px; background: var(--surface); border-top: 1px solid var(--line); }
h3 { margin: 0; font-size: 14px; font-weight: 750; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; color: var(--text-color); line-height: 1.45; }
.actresses { font-size: 12px; color: var(--muted-color); margin-top: 6px; }
</style>
