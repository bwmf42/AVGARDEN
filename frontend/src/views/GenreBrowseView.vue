<template>
    <div class="container">
        <div class="weekly-hero">
            <div>
                <button class="back-link" @click="goBack">← 设置</button>
                <span>屏蔽标签</span>
                <h1>{{ tag || '标签' }}</h1>
                <p>浏览带有该标签的作品（不经过屏蔽过滤）。列表与未看/已看页签设计一致。</p>
            </div>
            <div class="weekly-count">{{ weeklyCount }} 项</div>
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
        <div v-else-if="!filteredVideos.length" class="loading">该标签下暂无作品</div>

        <div v-else class="video-grid">
            <template v-for="video in filteredVideos" :key="video.id">
                <div class="video-card" @click="openVideo(video)">
                    <div class="cover-container" :class="{ watched: isWatched(video.id) }">
                        <img class="cover" :src="video.cover || video.poster || getDmmFallback(video)" :alt="video.title" loading="lazy">
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
    recordWatchedOrderID,
    saveWatchedIDs,
    syncWatchedIDs,
    writeWatchedOrderIDs
} from '../api/weeklyWatched'
import { displayTitle as formatDisplayTitle } from '../utils/displayTitle'

function normalizeID(id) {
    return String(id || '').trim().toUpperCase()
}

export default {
    name: 'GenreBrowseView',
    data() {
        return {
            weeklyItems: [],
            loading: true,
            watchedSet: new Set(),
            watchedOrder: [],
            queueSet: new Set(),
            showWatched: false,
            loadedTag: ''
        }
    },
    computed: {
        tag() {
            return String(this.$route.params.tag || '').trim()
        },
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
        if (this.loadedTag !== this.tag || this.weeklyItems.length === 0) {
            await this.syncWatched()
            await this.loadData()
        } else {
            this.syncWatched().then(result => {
                this.applyWatchedIDs(result.ids)
            })
        }
    },
    watch: {
        '$route.query.tab'() {
            this.applyRouteTab()
        },
        '$route.params.tag'() {
            this.loadData()
        }
    },
    methods: {
        goBack() {
            this.$router.push({ name: 'settings' })
        },
        applyRouteTab() {
            this.showWatched = this.$route.query.tab === 'watched'
        },
        applyWatchedIDs(ids) {
            const normalized = normalizeWatchedIDs(ids)
            this.watchedSet = new Set(normalized)
            const serverOrder = [...normalized].reverse()
            const existingOrder = readWatchedOrderIDs()
            const existingSet = new Set(existingOrder)
            const newIds = serverOrder.filter(id => !existingSet.has(id))
            this.watchedOrder = writeWatchedOrderIDs([...newIds, ...existingOrder], normalized)
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
            const tag = this.tag
            if (!tag) {
                this.weeklyItems = []
                this.loading = false
                return
            }
            this.loading = true
            try {
                const [wResp, qResp] = await Promise.all([
                    fetch('/api/weekly/by-genre/' + encodeURIComponent(tag)),
                    fetch('/api/queue/')
                ])
                if (wResp.ok) {
                    const weeklyItems = await wResp.json().catch(() => [])
                    this.weeklyItems = Array.isArray(weeklyItems) ? weeklyItems : []
                } else {
                    this.weeklyItems = []
                }
                if (qResp.ok) {
                    const qItems = await qResp.json().catch(() => [])
                    this.queueSet = new Set((Array.isArray(qItems) ? qItems : []).map(i => i.code))
                }
                this.loadedTag = tag
            } catch (e) {
                console.error(e)
                this.weeklyItems = []
            }
            this.loading = false
        },
        displayTitle(video) {
            return formatDisplayTitle(video, { withCode: true, maxLen: 50 })
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
                this.$router.push({
                    name: 'weekly-detail',
                    params: { id: video.id },
                    query: { tab, from: 'genre', tag: this.tag }
                })
            }
        },
        setWatchedTab(val) {
            this.showWatched = val
            const query = { ...(val ? { tab: 'watched' } : {}) }
            this.$router.replace({ name: 'weekly-genre', params: { tag: this.tag }, query })
        },
    }
}
</script>

<style scoped>
.container { padding: 0; }

.weekly-hero {
  min-height: 210px;
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
  padding: 26px;
  border: 1px solid var(--rose-line);
  border-radius: 8px;
  background:
    linear-gradient(110deg, rgba(255,255,255,0.96) 0 45%, rgba(255,242,247,0.88) 45% 100%),
    repeating-linear-gradient(90deg, rgba(186,47,93,0.08) 0 1px, transparent 1px 22px);
  box-shadow: var(--shadow-soft);
}

.back-link {
  display: inline-block;
  margin: 0 0 10px;
  padding: 0;
  border: none;
  background: none;
  color: var(--secondary-color);
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
}

.back-link:hover {
  color: var(--primary-color);
}

.weekly-hero span {
  display: block;
  color: var(--secondary-color);
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.08em;
}

.weekly-hero h1 {
  margin: 10px 0 10px;
  max-width: 540px;
  color: var(--text-color);
  font-size: clamp(28px, 4vw, 48px);
  line-height: 1.03;
  font-weight: 900;
  text-wrap: balance;
}

.weekly-hero p {
  max-width: 500px;
  margin: 0;
  color: var(--muted-color);
  font-size: 14px;
  line-height: 1.7;
}

.weekly-count {
  flex: 0 0 auto;
  padding: 9px 12px;
  border: 1px solid var(--rose-line);
  border-radius: 999px;
  background: var(--surface);
  color: var(--secondary-color);
  font-size: 13px;
  font-weight: 900;
}

.sub-tabs { display: flex; gap: 8px; margin-bottom: 1rem; }
.sub-tab { padding: 7px 12px; border: 1px solid var(--line); background: var(--surface); color: var(--muted-color); border-radius: 999px; cursor: pointer; font-size: 12px; font-weight: 700; transition: all 0.18s ease; }
.sub-tab.active { background: var(--secondary-color); color: white; border-color: var(--secondary-color); }
.loading { text-align: center; color: var(--muted-color); padding: 40px; font-size: 15px; }
.video-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(166px, 1fr)); gap: 18px; padding: 12px 0; }
.video-card { cursor: pointer; transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease; background: var(--surface); border-radius: 8px; overflow: hidden; border: 1px solid var(--line); box-shadow: var(--shadow-soft); position: relative; }
.video-card::before { content: ''; position: absolute; inset: 0 0 auto; height: 3px; background: var(--primary-color); z-index: 3; }
.video-card:hover { transform: translateY(-2px); border-color: var(--rose-line); box-shadow: var(--shadow-hover); }
.cover-container { position: relative; width: 100%; aspect-ratio: 3 / 4.2; overflow: hidden; background: #f7eef3; }
.cover-container.watched { opacity: 0.55; }
.cover { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: right center; }
.badge { position: absolute; padding: 4px 8px; border-radius: 999px; font-size: 11px; font-weight: 800; z-index: 2; }
.badge.chinese { top: 8px; left: 8px; background: rgba(161, 92, 0, 0.9); color: white; }
.watched-overlay { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); padding: 6px 14px; border-radius: 999px; font-size: 13px; font-weight: 800; background: rgba(53,36,44,0.72); color: white; z-index: 3; pointer-events: none; letter-spacing: 0; }
.watch-toggle { position: absolute; top: 8px; right: 8px; min-width: 28px; height: 28px; border-radius: 999px; border: 1px solid rgba(255,255,255,0.7); background: rgba(255,255,255,0.88); color: var(--secondary-color); font-size: 12px; font-weight: 800; cursor: pointer; z-index: 5; display: flex; align-items: center; justify-content: center; padding: 0 8px; line-height: 1; transition: all 0.18s ease; }
.watch-toggle:hover { background: white; transform: translateY(-1px); }
.info { min-height: 94px; padding: 12px; background: var(--surface); border-top: 1px solid var(--line); }
h3 { margin: 0; font-size: 14px; font-weight: 750; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; color: var(--text-color); line-height: 1.45; }
.actresses { font-size: 12px; color: var(--muted-color); margin-top: 6px; }

@media (max-width: 640px) {
  .weekly-hero {
    min-height: 0;
    align-items: start;
    flex-direction: column;
    padding: 20px;
  }
}
</style>
