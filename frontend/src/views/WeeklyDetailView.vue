<template>
    <div class="detail-wrapper">
        <!-- 左右翻页按钮 -->
        <button
            class="page-nav prev"
            :class="{ disabled: routeLoading || navInFlight || currentIndex <= 0 }"
            :disabled="routeLoading || navInFlight || currentIndex <= 0"
            @click="goPrev"
            aria-label="上一页"
        >
            <svg width="28" height="28" viewBox="0 0 24 24">
                <path fill="currentColor" d="M15.41 16.09l-4.58-4.59 4.58-4.59L14 5.5l-6 6 6 6z"/>
            </svg>
        </button>
        <button
            class="page-nav next"
            :class="{ disabled: routeLoading || navInFlight || currentIndex >= allVideos.length - 1 }"
            :disabled="routeLoading || navInFlight || currentIndex >= allVideos.length - 1"
            @click="goNext"
            aria-label="下一页"
        >
            <svg width="28" height="28" viewBox="0 0 24 24">
                <path fill="currentColor" d="M8.59 16.34l4.58-4.59-4.58-4.59L10 5.75l6 6-6 6z"/>
            </svg>
        </button>

        <div class="container" v-if="video">
            <div class="detail-container">
                <div class="detail-header">
                    <div class="header-top">
                        <button class="back-btn" @click="goBackToWeekly">返回</button>
                        <div class="pagination top-pagination" v-if="allVideos.length > 1">
                            <button class="page-btn" :disabled="routeLoading || navInFlight || currentIndex <= 0" @click="goPrev">上一页</button>
                            <span class="page-info">{{ currentIndex + 1 }} / {{ allVideos.length }}</span>
                            <button v-if="currentIndex < allVideos.length - 1" class="page-btn" :disabled="routeLoading || navInFlight" @click="goNext">下一页</button>
                            <span v-else class="page-end">最后一页</span>
                        </div>
                    </div>

                    <h1 class="title">{{ video.titleZh || video.title }}</h1>
                    <div class="title-meta">
                        <div class="code">{{ video.id }}</div>
                        <div v-if="markedVisible" class="marked-badge">已标记为已看</div>
                    </div>
                </div>

                <div class="detail-hero">
                    <div class="poster-section">
                        <img class="poster" :key="`poster-${mediaKey}`" :src="video.cover || video.poster" :alt="video.title">
                    </div>

                    <aside class="detail-side">
                        <div class="info-section">
                            <div v-if="video.actresses && video.actresses.length" class="section">
                                <h3>演员</h3>
                                <div class="tags">
                                    <span v-for="a in video.actresses" class="tag actress">
                                        {{ a }}
                                        <button class="fav-btn"
                                            :class="{ faved: favActresses[a] }"
                                            @click.stop="toggleFav(a)"
                                            :title="favActresses[a] ? '取消收藏' : '收藏此女优'">
                                            {{ favActresses[a] ? '已收' : '收藏' }}
                                        </button>
                                        <template v-if="blockingName === a">
                                            <span class="block-confirm">屏蔽?</span>
                                            <button class="block-yes" :disabled="blockInFlight" @click.stop="doBlock(a)">确认</button>
                                            <button class="block-no" :disabled="blockInFlight" @click.stop="blockingName = null">取消</button>
                                        </template>
                                        <button v-else class="block-btn" :disabled="blockInFlight" @click.stop="blockingName = a" title="屏蔽此女优">屏蔽</button>
                                    </span>
                                </div>
                            </div>

                            <div v-if="video.genres && video.genres.length" class="section">
                                <h3>标签</h3>
                                <div class="tags">
                                    <span v-for="g in video.genres" class="tag genre" @mouseenter="showGenreActions(g)" @mouseleave="hideGenreActions(g)">
                                        {{ g }}
                                        <template v-if="blockingGenre === g">
                                            <span class="block-confirm">屏蔽?</span>
                                            <button class="block-yes" :disabled="blockInFlight" @click.stop="doBlockGenre(g)">确认</button>
                                            <button class="block-no" :disabled="blockInFlight" @click.stop="blockingGenre = null">取消</button>
                                        </template>
                                        <button v-else class="block-btn" :class="{ visible: hoverGenre === g }" :disabled="blockInFlight" @mouseenter.stop="showGenreActions(g)" @mouseleave.stop="hideGenreActions(g)" @click.stop="blockingGenre = g" title="屏蔽此标签">屏蔽</button>
                                    </span>
                                </div>
                            </div>

                            <div class="info-grid">
                                <div v-if="video.releaseDate" class="info-item">
                                    <span class="label">发行</span>
                                    <span>{{ video.releaseDate }}</span>
                                </div>
                                <div v-if="video.duration" class="info-item">
                                    <span class="label">时长</span>
                                    <span>{{ video.duration }}</span>
                                </div>
                                <div class="info-item">
                                    <span class="label">字幕</span>
                                    <span>{{ video.hasChinese ? '有中文字幕' : '无' }}</span>
                                </div>
                                <div v-if="video.size" class="info-item">
                                    <span class="label">大小</span>
                                    <span>{{ video.size }}</span>
                                </div>
                            </div>

                            <div class="action-row">
                                <button v-if="!video.downloaded && (queueState === 'idle' || queueState === 'error')"
                                    class="btn-download"
                                    :class="{ error: queueState === 'error' }"
                                    @click="addToQueue"
                                    :disabled="queueBusy">
                                    {{ queueState === 'error' ? (queueErrorReason ? '加入失败，重试' : '添加失败，重试') : '加入下载队列' }}
                                </button>
                                <button v-if="queueState === 'adding'" class="btn-download" disabled>添加中...</button>
                                <button v-if="queueState === 'waiting_ready'" class="btn-download waiting" disabled>
                                    等待服务就绪…
                                </button>
                                <div v-if="queueState === 'success'" class="btn-download success">已加入队列</div>
                                <div v-if="queueState === 'queued'" class="btn-download queued">已加入队列</div>
                                <div v-if="queueState === 'downloading'" class="btn-download downloading">
                                    下载中 {{ queueProgress }}%
                                </div>
                                <a v-if="queueState === 'failed'" class="btn-download error"
                                    :href="'https://www.javbus.com/' + encodeURIComponent(this.id)" target="_blank">
                                    所有源均失败，去 JavBus
                                </a>
                                <a v-if="video.downloaded" class="btn-play" @click="$router.push({ name: 'detail', params: { id: video.id } })">
                                    播放 (AV/GARDEN)
                                </a>
                            </div>
                            <p v-if="queueHintText" class="queue-hint" :class="{ error: queueState === 'error' }">
                                {{ queueHintText }}
                            </p>
                        </div>
                    </aside>
                </div>

                <!-- Fanarts Gallery (AV/GARDEN style) -->
                <div v-if="fanartList.length" :key="`fanarts-${mediaKey}`" class="section preview-section">
                    <h3>预览图</h3>
                    <div class="fanarts-grid">
                        <div v-for="(img, i) in fanartList" :key="`${video.id}-${i}-${img}`" class="fanart-item" @click="openLightbox(i)">
                            <img :src="img" loading="lazy" class="fanart-img">
                        </div>
                    </div>
                    <!-- Lightbox (like AV/GARDEN DetailView) -->
                    <div v-if="showLightbox" class="lightbox" @click="closeLightbox">
                        <div class="lightbox-content" @click.stop>
                            <button class="lightbox-close" @click="closeLightbox">关闭</button>
                            <button class="lightbox-nav lightbox-prev" @click.stop="prevImage">上一张</button>
                            <img :key="`lightbox-${mediaKey}-${lightboxIndex}`" :src="fanartList[lightboxIndex]" class="lightbox-image" @click.stop>
                            <button class="lightbox-nav lightbox-next" @click.stop="nextImage">下一张</button>
                            <div class="lightbox-counter">{{ lightboxIndex + 1 }} / {{ fanartList.length }}</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <div class="container" v-else-if="detailMissing">
            <div class="detail-container empty-detail">
                <div class="detail-header">
                    <div class="header-top">
                        <button class="back-btn" @click="goBackToWeekly">返回</button>
                    </div>
                    <h1 class="title">{{ id }}</h1>
                    <div class="title-meta">
                        <div class="code">{{ id }}</div>
                        <div class="missing-badge">暂无刮削详情</div>
                    </div>
                </div>
                <div class="missing-content">
                    <p>这个番号还没有出现在每日推荐的刮削数据里，当前只能显示队列状态。</p>
                    <div class="missing-status">
                        <span class="label">队列状态</span>
                        <span>{{ queueStateLabel }}</span>
                    </div>
                    <div class="action-row">
                        <a class="btn-download error" :href="'https://www.javbus.com/' + encodeURIComponent(id)" target="_blank" rel="noreferrer">
                            去 JavBus
                        </a>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<script>
import {
    normalizeWatchedIDs,
    recordWatchedOrderID,
    readLocalWatchedIDs,
    readWatchedOrderIDs,
    saveWatchedIDs,
    syncWatchedIDs
} from '../api/weeklyWatched'

const BROWSE_STATE_KEY = 'weekly_detail_browse_state'
const QUEUE_FAILED_GRACE_MS = 120000
const WEEKLY_CACHE_MS = 5 * 60 * 1000
let weeklyDetailCache = { items: null, fetchedAt: 0, promise: null }

function normalizeVideoID(id) {
    return String(id || '').trim().toUpperCase()
}

function canonicalVideoID(id) {
    const normalized = normalizeVideoID(id)
    const sourcePrefixed = normalized.match(/^420([A-Z]+-\d+)$/)
    return sourcePrefixed ? sourcePrefixed[1] : normalized
}

function hasRemoteFanarts(video) {
    return Array.isArray(video?.fanarts) && video.fanarts.some(img => /^https?:\/\//i.test(String(img || '')))
}

export default {
    props: ['id'],
    data() {
        return {
            video: null,
            allVideos: [],
            currentIndex: -1,
            queueState: 'idle',
            queueProgress: 0,
            queueSubmittedAt: 0,
            queueSubmittedId: '',
            queueErrorReason: '',
            queueHint: '',
            queueAddToken: 0,
            blockInFlight: false,
            blockingName: null,
            blockingGenre: null,
            hoverGenre: null,
            genreHoverTimer: null,
            favActresses: {},
            showLightbox: false,
            lightboxIndex: 0,
            watchedSet: new Set(),
            markedVisible: false,
            detailMissing: false,
            routeLoadToken: 0,
            routeLoading: false,
            navInFlight: false,
            keyNavPressed: null,
            onlineDetailCode: ''
        }
    },
    computed: {
        isOnlineSource() {
            return this.$route.query.source === 'online'
        },
        isGenreBrowse() {
            return this.$route.query.from === 'genre' && !!String(this.$route.query.tag || '').trim()
        },
        genreBrowseTag() {
            return String(this.$route.query.tag || '').trim()
        },
        fanartList() {
            return this.video?.fanarts || []
        },
        mediaKey() {
            return normalizeVideoID(this.video?.id || this.id)
        },
        queueBusy() {
            return this.queueState === 'adding' || this.queueState === 'waiting_ready'
        },
        queueStateLabel() {
            if (this.queueState === 'downloading') return `下载中 ${this.queueProgress}%`
            if (this.queueState === 'queued') return '等待中'
            if (this.queueState === 'failed') return '下载失败'
            if (this.queueState === 'adding') return '添加中'
            if (this.queueState === 'waiting_ready') return '等待服务就绪后加入'
            if (this.queueState === 'success') return '已加入队列'
            if (this.queueState === 'error') {
                return this.queueErrorReason ? `加入失败：${this.queueErrorReason}` : '加入失败'
            }
            return '未在队列中'
        },
        queueHintText() {
            if (this.queueHint) return this.queueHint
            if (this.queueState === 'error' && this.queueErrorReason) {
                return this.queueErrorReason
            }
            if (this.queueState === 'waiting_ready') {
                return '服务暂不可用（可能在部署/重启），就绪后将自动加入队列'
            }
            return ''
        }
    },
    async created() {
        window.addEventListener('av-garden-status', this.handleGlobalStatus)
        window.dispatchEvent(new CustomEvent('av-garden-refresh-status'))
        window.addEventListener('keydown', this.handlePageKeydown, true)
        window.addEventListener('keyup', this.handlePageKeyup, true)
        this.unlockPageScroll()
        this.loadWatched()
        this.syncWatched().then(async () => {
            if (this.isGenreBrowse) {
                try {
                    const items = await this.getWeeklyItems()
                    this.rebuildBrowseList(this.id, items)
                } catch (e) {}
                return
            }
            if (weeklyDetailCache.items) this.rebuildBrowseList(this.id)
        })
        await this.loadRoute(this.id)
    },
    async beforeRouteUpdate(to, from, next) {
        if (from.query?.source === 'online' &&
            (to.query?.source !== 'online' || normalizeVideoID(to.params.id) !== normalizeVideoID(from.params.id))) {
            await this.cleanupOnlineDetail()
        }
        this.closeLightbox()
        this.unlockPageScroll()
        next()
        await this.loadRoute(to.params.id)
    },
    beforeUnmount() {
        window.removeEventListener('keydown', this.handlePageKeydown, true)
        window.removeEventListener('keyup', this.handlePageKeyup, true)
        window.removeEventListener('av-garden-status', this.handleGlobalStatus)
        this.unlockPageScroll()
        if (this.genreHoverTimer) clearTimeout(this.genreHoverTimer)
        if (this.isOnlineSource) this.cleanupOnlineDetail()
    },
    async beforeRouteLeave(to, from, next) {
        if (from.query?.source === 'online') {
            await this.cleanupOnlineDetail()
        }
        if (to.name !== 'weekly-detail') this.clearBrowseState()
        this.unlockPageScroll()
        next()
    },
    methods: {
        async loadRoute(targetId) {
            const token = ++this.routeLoadToken
            this.routeLoading = true
            try {
                const loaded = await this.loadDetail(targetId, token)
                if (!loaded || token !== this.routeLoadToken) return

                if (!this.isOnlineSource) {
                    this.trackView(targetId)
                    this.markWatched(targetId)
                }

                this.loadFavActresses()
                this.syncQueueState(window.avGardenQueueStatus || [], targetId)
            } finally {
                if (token === this.routeLoadToken) {
                    this.routeLoading = false
                    this.navInFlight = false
                }
            }
        },
        trackView(id) {
            try {
                const raw = sessionStorage.getItem('weekly_viewed_session') || '[]'
                const arr = JSON.parse(raw)
                if (!arr.includes(id)) {
                    arr.push(id)
                    sessionStorage.setItem('weekly_viewed_session', JSON.stringify(arr))
                }
            } catch(e) {}
        },
        async loadDetail(targetId, token = this.routeLoadToken) {
            const normalizedTarget = normalizeVideoID(targetId)
            const canonicalTarget = canonicalVideoID(targetId)
            this.detailMissing = false
            try {
                if (this.isOnlineSource) {
                    return await this.loadOnlineDetail(canonicalTarget || normalizedTarget, token)
                }

                if (this.setVideoFromCurrentList(targetId)) {
                    this.syncQueueState(window.avGardenQueueStatus || [], targetId)
                    this.ensureLocalFanarts(token)
                    return true
                }

                const all = await this.getWeeklyItems()
                if (token !== this.routeLoadToken) return false
                this.rebuildBrowseList(targetId, all)
                if (token !== this.routeLoadToken) return false
                this.syncQueueState(window.avGardenQueueStatus || [], targetId)
                this.detailMissing = !this.video
                this.ensureLocalFanarts(token)
                return true
            } catch (e) {
                if (token !== this.routeLoadToken) return false
                console.error(e)
                this.detailMissing = true
                return false
            }
        },
        async loadOnlineDetail(targetId, token = this.routeLoadToken) {
            const code = canonicalVideoID(targetId)
            const resp = await fetch('/api/online-search/' + encodeURIComponent(code))
            if (token !== this.routeLoadToken) return false
            if (!resp.ok) {
                this.video = null
                this.allVideos = []
                this.currentIndex = -1
                this.detailMissing = true
                return true
            }
            const item = await resp.json()
            if (token !== this.routeLoadToken) return false
            const video = { ...item, source: 'online' }
            this.onlineDetailCode = normalizeVideoID(video.id || code)
            this.allVideos = [video]
            this.currentIndex = 0
            this.video = video
            this.detailMissing = false
            this.clearBrowseState()
            this.resetMediaState()
            this.syncQueueState(window.avGardenQueueStatus || [], video.id)
            return true
        },
        async cleanupOnlineDetail() {
            const code = normalizeVideoID(this.onlineDetailCode || this.video?.id || this.id)
            if (!code) return
            this.onlineDetailCode = ''
            try {
                await fetch('/api/online-search/' + encodeURIComponent(code), {
                    method: 'DELETE',
                    keepalive: true
                })
            } catch(e) {}
        },
        browseStateKey(tab) {
            if (this.isGenreBrowse) {
                return `genre:${this.genreBrowseTag}:${tab || 'unwatched'}`
            }
            return tab || 'unwatched'
        },
        async getWeeklyItems(force = false) {
            if (this.isGenreBrowse) {
                const tag = this.genreBrowseTag
                const resp = await fetch('/api/weekly/by-genre/' + encodeURIComponent(tag))
                if (!resp.ok) return []
                const data = await resp.json().catch(() => [])
                return Array.isArray(data) ? data : []
            }
            const now = Date.now()
            if (
                !force &&
                weeklyDetailCache.items &&
                now - weeklyDetailCache.fetchedAt < WEEKLY_CACHE_MS
            ) {
                return weeklyDetailCache.items
            }
            if (force) {
                weeklyDetailCache = { items: null, fetchedAt: 0, promise: null }
            }
            if (!weeklyDetailCache.promise) {
                weeklyDetailCache.promise = fetch('/api/weekly')
                    .then(resp => resp.ok ? resp.json() : [])
                    .then(data => Array.isArray(data) ? data : [])
                    .then(items => {
                        weeklyDetailCache = { items, fetchedAt: Date.now(), promise: null }
                        return items
                    })
                    .catch(err => {
                        weeklyDetailCache.promise = null
                        throw err
                    })
            }
            return weeklyDetailCache.promise
        },
        // 与 WeeklyView 已看列表一致：watchedOrder 末尾 = 最近看过，列表降序 = 最近在最上
        sortWatchedByRecency(videos) {
            const order = readWatchedOrderIDs()
            if (!order.length) return videos
            const orderIndex = new Map(order.map((id, index) => [normalizeVideoID(id), index]))
            return [...videos].sort((a, b) => {
                const ai = orderIndex.get(normalizeVideoID(a.id))
                const bi = orderIndex.get(normalizeVideoID(b.id))
                const aKnown = ai !== undefined
                const bKnown = bi !== undefined
                if (aKnown && bKnown) return bi - ai
                if (aKnown) return -1
                if (bKnown) return 1
                return 0
            })
        },
        rebuildBrowseList(targetId, weeklyItems = weeklyDetailCache.items || []) {
            const normalizedTarget = normalizeVideoID(targetId)
            const canonicalTarget = canonicalVideoID(targetId)
            const allById = new Map(weeklyItems.map(v => [normalizeVideoID(v.id), v]))
            const undownloaded = weeklyItems.filter(v => !v.downloaded)
            const tab = this.$route.query.tab || 'unwatched'

            if (tab === 'watched') {
                // 已看：始终按最近观看排序，不用 session 旧顺序（否则点列表第一张会变成 124/N）
                this.allVideos = this.sortWatchedByRecency(
                    undownloaded.filter(v => this.isWatched(v.id))
                )
            } else {
                const savedIds = this.readBrowseState(this.browseStateKey(tab), canonicalTarget)
                if (savedIds) {
                    this.allVideos = savedIds.map(id => allById.get(normalizeVideoID(id))).filter(Boolean)
                } else {
                    this.allVideos = undownloaded.filter(v => !this.isWatched(v.id))
                }
            }

            if (!this.allVideos.some(v => normalizeVideoID(v.id) === canonicalTarget || normalizeVideoID(v.id) === normalizedTarget)) {
                const current = allById.get(normalizedTarget) || allById.get(canonicalTarget)
                if (current) this.allVideos = [current, ...this.allVideos]
            }

            // 已看：点进的那张固定为 1/N（列表本身已是最近观看在前）
            if (tab === 'watched') {
                const pivot = this.allVideos.findIndex(v => {
                    const id = normalizeVideoID(v.id)
                    return id === normalizedTarget || id === canonicalTarget
                })
                if (pivot > 0) {
                    this.allVideos = this.allVideos.slice(pivot).concat(this.allVideos.slice(0, pivot))
                }
            }

            this.saveBrowseState(this.browseStateKey(tab), this.allVideos)
            if (!this.setVideoFromCurrentList(targetId)) {
                this.currentIndex = -1
                this.video = null
            }
        },
        setVideoFromCurrentList(targetId) {
            const normalizedTarget = normalizeVideoID(targetId)
            const canonicalTarget = canonicalVideoID(targetId)
            const index = this.allVideos.findIndex(v => {
                const id = normalizeVideoID(v.id)
                return id === normalizedTarget || id === canonicalTarget
            })
            if (index < 0) return false
            const previousID = normalizeVideoID(this.video?.id)
            this.currentIndex = index
            this.video = this.allVideos[index]
            if (previousID && previousID !== normalizeVideoID(this.video?.id)) {
                this.resetMediaState()
                this.resetQueueState()
            }
            this.detailMissing = false
            return true
        },
        async ensureLocalFanarts(token = this.routeLoadToken) {
            if (this.isOnlineSource || !hasRemoteFanarts(this.video)) return
            const code = canonicalVideoID(this.video.id || this.id)
            const previous = this.video
            const pendingVideo = { ...previous, fanarts: [] }
            this.video = pendingVideo
            if (this.currentIndex >= 0) this.allVideos.splice(this.currentIndex, 1, pendingVideo)
            try {
                const resp = await fetch('/api/weekly-fanarts/' + encodeURIComponent(code))
                if (token !== this.routeLoadToken || !resp.ok) return
                const data = await resp.json()
                const fanarts = Array.isArray(data.fanarts) ? data.fanarts : []
                const nextVideo = { ...this.video, fanarts }
                this.video = nextVideo
                if (this.currentIndex >= 0) this.allVideos.splice(this.currentIndex, 1, nextVideo)
                if (weeklyDetailCache.items) {
                    weeklyDetailCache.items = weeklyDetailCache.items.map(item =>
                        normalizeVideoID(item.id) === normalizeVideoID(nextVideo.id) ? nextVideo : item
                    )
                }
            } catch(e) {}
        },
        resetMediaState() {
            this.closeLightbox()
            this.lightboxIndex = 0
            this.blockingName = null
            this.blockingGenre = null
            this.hoverGenre = null
            this.favActresses = {}
        },
        resetQueueState() {
            this.queueState = 'idle'
            this.queueProgress = 0
            this.queueSubmittedAt = 0
            this.queueSubmittedId = ''
            this.queueErrorReason = ''
            this.queueHint = ''
            this.queueAddToken++
        },
        loadWatched() {
            this.watchedSet = new Set(readLocalWatchedIDs())
        },
        async syncWatched() {
            const result = await syncWatchedIDs()
            this.watchedSet = new Set(result.ids)
        },
        async saveWatched() {
            const result = await saveWatchedIDs([...this.watchedSet])
            this.watchedSet = new Set(result.ids)
        },
        isWatched(id) {
            return this.watchedSet.has(id)
        },
        readBrowseState(tab, targetId) {
            try {
                const raw = sessionStorage.getItem(BROWSE_STATE_KEY)
                if (!raw) return null
                const state = JSON.parse(raw)
                if (state?.tab !== tab || !Array.isArray(state.ids)) return null
                if (!state.ids.map(normalizeVideoID).includes(normalizeVideoID(targetId))) return null
                return state.ids
            } catch(e) {
                return null
            }
        },
        saveBrowseState(tab, videos) {
            try {
                const ids = videos.map(v => v.id).filter(Boolean)
                sessionStorage.setItem(BROWSE_STATE_KEY, JSON.stringify({ tab, ids }))
            } catch(e) {}
        },
        clearBrowseState() {
            try {
                sessionStorage.removeItem(BROWSE_STATE_KEY)
            } catch(e) {}
        },
        goBackToWeekly() {
            this.clearBrowseState()
            if (this.isOnlineSource) {
                this.$router.push({ name: 'search' })
                return
            }
            if (this.isGenreBrowse) {
                const tab = this.$route.query.tab
                this.$router.push({
                    name: 'weekly-genre',
                    params: { tag: this.genreBrowseTag },
                    query: tab === 'watched' ? { tab: 'watched' } : {}
                })
                return
            }
            const tab = this.$route.query.tab
            this.$router.push({ name: 'weekly', query: tab === 'watched' ? { tab: 'watched' } : {} })
        },
        loadFavActresses() {
            if (!this.video?.actresses) return
            this.video.actresses.forEach(a => {
                fetch('/api/fav-actress/' + encodeURIComponent(a))
                    .then(r => r.json())
                    .then(d => { if (d.favorited) this.favActresses = { ...this.favActresses, [a]: true } })
                    .catch(() => {})
            })
        },
        async markWatched(id) {
            if (!id) return
            if (!this.watchedSet.has(id)) {
                const nextIDs = normalizeWatchedIDs([...this.watchedSet, id])
                this.watchedSet = new Set(nextIDs)
                recordWatchedOrderID(id, nextIDs)
                this.markedVisible = true
                setTimeout(() => { this.markedVisible = false }, 2000)
                try {
                    await this.saveWatched()
                } catch(e) {
                    console.error('[markWatched] FAILED:', e)
                }
            }
        },
        navigateRelative(delta) {
            if (this.routeLoading || this.navInFlight) return
            const targetIndex = this.currentIndex + delta
            if (targetIndex < 0 || targetIndex >= this.allVideos.length) return

            const target = this.allVideos[targetIndex]
            if (!target?.id) return

            this.navInFlight = true
            this.$router.push({
                name: 'weekly-detail',
                params: { id: target.id },
                query: { ...this.$route.query }
            }).catch(() => {
                this.navInFlight = false
            })
        },
        goPrev() {
            this.navigateRelative(-1)
        },
        goNext() {
            this.navigateRelative(1)
        },
        shouldHandlePageKey(e) {
            if (this.showLightbox || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return false
            if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return false
            const tag = e.target?.tagName
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target?.isContentEditable) return false
            return true
        },
        claimPageKey(e) {
            e.preventDefault()
            e.stopPropagation()
            if (typeof e.stopImmediatePropagation === 'function') e.stopImmediatePropagation()
        },
        handlePageKeydown(e) {
            if (!this.shouldHandlePageKey(e)) return
            this.claimPageKey(e)
            if (!e.repeat) this.keyNavPressed = e.key
        },
        handlePageKeyup(e) {
            if (!this.shouldHandlePageKey(e)) return
            this.claimPageKey(e)
            if (this.keyNavPressed !== e.key) return
            this.keyNavPressed = null
            if (e.key === 'ArrowLeft') this.goPrev()
            if (e.key === 'ArrowRight') this.goNext()
        },
        handleGlobalStatus(e) {
            this.syncQueueState(e.detail?.items || [])
        },
        showGenreActions(name) {
            if (this.genreHoverTimer) {
                clearTimeout(this.genreHoverTimer)
                this.genreHoverTimer = null
            }
            this.hoverGenre = name
        },
        hideGenreActions(name) {
            if (this.genreHoverTimer) clearTimeout(this.genreHoverTimer)
            this.genreHoverTimer = setTimeout(() => {
                if (this.hoverGenre === name) this.hoverGenre = null
                this.genreHoverTimer = null
            }, 450)
        },
        syncQueueState(items, targetId = this.id) {
            const normalizedTarget = normalizeVideoID(targetId)
            const canonicalTarget = canonicalVideoID(targetId)
            const submittedID = normalizeVideoID(this.queueSubmittedId)
            const submittedCanonical = canonicalVideoID(this.queueSubmittedId)
            const submittedMatchesTarget = submittedID &&
                (submittedID === normalizedTarget ||
                    submittedID === canonicalTarget ||
                    submittedCanonical === normalizedTarget ||
                    submittedCanonical === canonicalTarget)
            const current = items.find(item => {
                const itemID = normalizeVideoID(item.id)
                const itemCanonical = canonicalVideoID(item.id)
                return itemID === normalizedTarget ||
                    itemID === canonicalTarget ||
                    itemCanonical === normalizedTarget ||
                    itemCanonical === canonicalTarget
            })
            if (!current) {
                if (submittedMatchesTarget && this.queueSubmittedAt && Date.now() - this.queueSubmittedAt < QUEUE_FAILED_GRACE_MS) {
                    this.queueState = 'queued'
                    this.queueProgress = 0
                    this.queueErrorReason = ''
                    this.queueHint = ''
                    return
                }
                if (
                    this.queueState !== 'adding' &&
                    this.queueState !== 'waiting_ready' &&
                    this.queueState !== 'error'
                ) {
                    this.queueState = 'idle'
                    this.queueProgress = 0
                }
                return
            }
            this.queueProgress = current.progress || 0
            // Server already has this code — clear transient add errors
            if (this.queueState === 'error' || this.queueState === 'waiting_ready' || this.queueState === 'adding') {
                this.queueErrorReason = ''
                this.queueHint = ''
            }
            if (current.status === 'done') {
                this.queueState = 'success'
                this.queueSubmittedAt = 0
                this.queueSubmittedId = ''
            } else if (current.status === 'failed') {
                if (submittedMatchesTarget && this.queueSubmittedAt && Date.now() - this.queueSubmittedAt < QUEUE_FAILED_GRACE_MS) {
                    this.queueState = 'queued'
                    return
                }
                this.queueState = 'failed'
            } else {
                this.queueState = current.status
            }
        },
        async doBlock(name) {
            if (this.blockInFlight) return
            this.blockingName = null
            this.blockInFlight = true
            try {
                const resp = await fetch('/api/block-actress/' + encodeURIComponent(name), {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${import.meta.env.VITE_API_KEY || ''}` }
                })
                if (resp.ok) await this.afterBlockRefresh({ actress: name })
            } catch (e) {
            } finally {
                this.blockInFlight = false
            }
        },
        /**
         * After block: drop filtered titles, then rotate so "next" becomes page 1/N.
         * Avoids staying at high index (e.g. 12/N) and double-block on the next card.
         */
        async afterBlockRefresh({ genre, actress } = {}) {
            if (this.isOnlineSource) {
                this.$router.replace({ name: 'search' })
                return
            }
            const prevIndex = Math.max(this.currentIndex, 0)
            const prevId = normalizeVideoID(this.video?.id || this.id)

            // Optimistic: remove matching items from current browse list
            if (genre) {
                this.allVideos = this.allVideos.filter(
                    v => !(Array.isArray(v.genres) && v.genres.includes(genre))
                )
            }
            if (actress) {
                this.allVideos = this.allVideos.filter(
                    v => !(Array.isArray(v.actresses) && v.actresses.includes(actress))
                )
            }

            // Force server list (block handlers invalidate weekly cache)
            try {
                const items = await this.getWeeklyItems(true)
                this.clearBrowseState()
                const tab = this.$route.query.tab || 'unwatched'
                const undownloaded = (items || []).filter(v => !v.downloaded)
                if (tab === 'watched') {
                    this.allVideos = undownloaded.filter(v => this.isWatched(v.id))
                } else {
                    this.allVideos = undownloaded.filter(v => !this.isWatched(v.id))
                }
            } catch (e) {
                // keep optimistic list
            }

            window.dispatchEvent(new CustomEvent('av-garden-weekly-refresh'))

            if (!this.allVideos.length) {
                this.clearBrowseState()
                this.goBackToWeekly()
                return
            }

            // Pick the item that should become the new "page 1"
            const remaining = this.allVideos
            const prevPos = remaining.findIndex(v => normalizeVideoID(v.id) === prevId)
            let pivot = 0
            if (prevPos >= 0) {
                // Current still allowed (e.g. blocked a tag it doesn't have): stay, as 1/N
                // If user blocked something that removed others but not this, keep current as first.
                // Prefer advancing when the blocked key matches current (actress/genre on this card).
                const current = remaining[prevPos]
                const blockedSelf =
                    (actress && Array.isArray(current.actresses) && current.actresses.includes(actress)) ||
                    (genre && Array.isArray(current.genres) && current.genres.includes(genre))
                pivot = blockedSelf
                    ? (prevPos + 1) % remaining.length
                    : prevPos
            } else {
                // Current removed: item that slid into prevIndex is the old "next page"
                pivot = Math.min(prevIndex, remaining.length - 1)
            }

            // Rotate so pivot is index 0 → UI shows 1/N
            this.allVideos = remaining.slice(pivot).concat(remaining.slice(0, pivot))
            const tab = this.$route.query.tab || 'unwatched'
            this.saveBrowseState(this.browseStateKey(tab), this.allVideos)

            const first = this.allVideos[0]
            if (!first?.id) {
                this.goBackToWeekly()
                return
            }
            if (normalizeVideoID(first.id) === prevId) {
                this.setVideoFromCurrentList(first.id)
                return
            }
            this.$router.replace({
                name: 'weekly-detail',
                params: { id: first.id },
                query: { ...this.$route.query }
            })
        },
        goNextAfterBlock() {
            // legacy entry: treat as refresh without extra filter key
            this.afterBlockRefresh()
        },
        async toggleFav(name) {
            try {
                const resp = await fetch('/api/fav-actress/' + encodeURIComponent(name), {method:'POST'})
                if (resp.ok) {
                    const data = await resp.json()
                    this.favActresses = { ...this.favActresses, [name]: data.favorited }
                }
            } catch(e) {}
        },
        async doBlockGenre(name) {
            if (this.blockInFlight) return
            this.blockingGenre = null
            this.blockInFlight = true
            try {
                const resp = await fetch('/api/block-genre/' + encodeURIComponent(name), {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${import.meta.env.VITE_API_KEY || ''}` }
                })
                if (resp.ok) await this.afterBlockRefresh({ genre: name })
            } catch (e) {
            } finally {
                this.blockInFlight = false
            }
        },
        sleep(ms) {
            return new Promise(resolve => setTimeout(resolve, ms))
        },
        async parseQueueError(resp) {
            let body = {}
            try {
                body = await resp.json()
            } catch (e) {
                body = {}
            }
            const msg = String(body.message || body.error || '').trim()
            if (resp.status === 409) {
                if (/cancel/i.test(msg)) return '取消进行中，请稍后再试'
                return msg || '请求冲突，请稍后再试'
            }
            if (resp.status === 400) return msg || '番号无效'
            if (resp.status === 503 || /unavailable|重启/i.test(msg)) {
                return msg || '队列服务暂不可用（可能在部署/重启）'
            }
            if (resp.status === 502 || resp.status === 504) {
                return msg || '网关超时，服务可能在重启'
            }
            if (!resp.status) return '连接中断（服务可能在重启）'
            return msg || `加入失败（HTTP ${resp.status}）`
        },
        isRetryableQueueError(err) {
            if (!err) return false
            if (err.network) return true
            const s = err.status
            return s === 502 || s === 503 || s === 504
        },
        async isCodeInQueue(targetId) {
            try {
                const resp = await fetch('/api/queue/')
                if (!resp.ok) return false
                const items = await resp.json().catch(() => [])
                const list = Array.isArray(items) ? items : []
                const normalizedTarget = normalizeVideoID(targetId)
                const canonicalTarget = canonicalVideoID(targetId)
                return list.some(item => {
                    const id = normalizeVideoID(item.code || item.id)
                    const can = canonicalVideoID(item.code || item.id)
                    return id === normalizedTarget ||
                        id === canonicalTarget ||
                        can === normalizedTarget ||
                        can === canonicalTarget
                })
            } catch (e) {
                return false
            }
        },
        async waitForApiReady(token, maxMs = 90000) {
            const start = Date.now()
            let delay = 1000
            while (Date.now() - start < maxMs) {
                if (token !== this.queueAddToken) return false
                try {
                    const resp = await fetch('/api/version', { cache: 'no-store' })
                    if (resp.ok) {
                        // also poke queue list — empty body on half-up server still fails
                        const q = await fetch('/api/queue/', { cache: 'no-store' })
                        if (q.ok) return true
                    }
                } catch (e) {
                    // keep waiting
                }
                this.queueHint = '服务暂不可用（可能在部署/重启），等待恢复…'
                await this.sleep(delay)
                delay = Math.min(3000, delay + 500)
            }
            return false
        },
        async postToQueue(targetId) {
            try {
                const resp = await fetch('/api/queue/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code: targetId })
                })
                if (resp.ok) {
                    return { ok: true }
                }
                const reason = await this.parseQueueError(resp)
                return {
                    ok: false,
                    status: resp.status,
                    reason,
                    retryable: resp.status === 502 || resp.status === 503 || resp.status === 504
                }
            } catch (e) {
                return {
                    ok: false,
                    network: true,
                    status: 0,
                    reason: '连接中断（服务可能在重启）',
                    retryable: true
                }
            }
        },
        async addToQueue() {
            const targetId = normalizeVideoID(this.video?.id || this.id)
            if (!targetId || this.queueBusy) return

            const token = ++this.queueAddToken
            this.queueState = 'adding'
            this.queueErrorReason = ''
            this.queueHint = '正在加入下载队列…'
            this.queueSubmittedAt = Date.now()
            this.queueSubmittedId = targetId

            // Already in queue? (e.g. previous click succeeded but UI showed error)
            if (await this.isCodeInQueue(targetId)) {
                if (token !== this.queueAddToken) return
                this.queueState = 'queued'
                this.queueHint = ''
                this.queueErrorReason = ''
                this.showToast(targetId + ' 已在下载队列中', 'info')
                window.dispatchEvent(new CustomEvent('av-garden-refresh-status'))
                return
            }

            const maxPostAttempts = 4
            let lastReason = ''
            for (let attempt = 1; attempt <= maxPostAttempts; attempt++) {
                if (token !== this.queueAddToken) return

                if (attempt > 1) {
                    this.queueState = 'waiting_ready'
                    this.queueHint = `服务暂不可用，等待就绪后自动加入（${attempt}/${maxPostAttempts}）…`
                    this.showToast(targetId + ' 等待服务就绪后自动加入…', 'warn')
                    const ready = await this.waitForApiReady(token, 90000)
                    if (token !== this.queueAddToken) return
                    if (!ready) {
                        lastReason = '等待服务就绪超时'
                        break
                    }
                    // Reconcile after wait — may already be queued from half-success
                    if (await this.isCodeInQueue(targetId)) {
                        this.queueState = 'queued'
                        this.queueHint = ''
                        this.queueErrorReason = ''
                        this.showToast(targetId + ' 已在下载队列中', 'info')
                        window.dispatchEvent(new CustomEvent('av-garden-refresh-status'))
                        return
                    }
                    this.queueState = 'adding'
                    this.queueHint = '服务已恢复，正在加入队列…'
                }

                const result = await this.postToQueue(targetId)
                if (token !== this.queueAddToken) return

                if (result.ok) {
                    this.queueState = 'queued'
                    this.queueHint = ''
                    this.queueErrorReason = ''
                    this.showToast(targetId + ' 已加入下载队列', 'info')
                    window.dispatchEvent(new CustomEvent('av-garden-refresh-status'))
                    return
                }

                lastReason = result.reason || '加入失败'
                // Non-retryable (400/409 etc.)
                if (!result.retryable && !result.network) {
                    break
                }
                // Retryable: loop continues with wait_ready
                if (attempt < maxPostAttempts) {
                    this.queueState = 'waiting_ready'
                    this.queueHint = lastReason + '，将自动重试…'
                    await this.sleep(800 * attempt)
                }
            }

            // Final reconcile: request may have succeeded despite client error
            if (await this.isCodeInQueue(targetId)) {
                if (token !== this.queueAddToken) return
                this.queueState = 'queued'
                this.queueHint = ''
                this.queueErrorReason = ''
                this.showToast(targetId + ' 已在下载队列中', 'info')
                window.dispatchEvent(new CustomEvent('av-garden-refresh-status'))
                return
            }

            if (token !== this.queueAddToken) return
            this.queueState = 'error'
            this.queueErrorReason = lastReason || '加入失败'
            this.queueHint = this.queueErrorReason
            this.queueSubmittedAt = 0
            this.queueSubmittedId = ''
            this.showToast(targetId + ' 加入失败：' + this.queueErrorReason, 'warn')
        },
        showToast(msg, type) {
            window.dispatchEvent(new CustomEvent('av-garden-toast', { detail: { msg, type } }))
        },
        openLightbox(idx) {
            this.lightboxIndex = idx
            this.showLightbox = true
            document.body.style.overflow = 'hidden'
            document.addEventListener('keydown', this.handleKeydown)
        },
        closeLightbox() {
            this.showLightbox = false
            this.unlockPageScroll()
            document.removeEventListener('keydown', this.handleKeydown)
        },
        unlockPageScroll() {
            document.body.style.overflow = ''
            document.documentElement.style.overflow = ''
        },
        prevImage() {
            this.lightboxIndex = (this.lightboxIndex - 1 + this.fanartList.length) % this.fanartList.length
        },
        nextImage() {
            this.lightboxIndex = (this.lightboxIndex + 1) % this.fanartList.length
        },
        handleKeydown(e) {
            e.preventDefault()
            e.stopPropagation()
            if (e.key === 'Escape') this.closeLightbox()
            if (e.key === 'ArrowLeft') this.prevImage()
            if (e.key === 'ArrowRight') this.nextImage()
        }
    }
}
</script>

<style scoped>
.detail-wrapper {
  position: relative;
  max-width: 1200px;
  margin: 0 auto;
}

.page-nav {
  position: fixed;
  top: 50%;
  transform: translateY(-50%);
  z-index: 100;
  width: 48px;
  height: 48px;
  border-radius: 999px;
  border: 1px solid var(--rose-line);
  background: rgba(255, 255, 255, 0.92);
  color: var(--secondary-color);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-soft);
  transition: all 0.18s ease;
  backdrop-filter: blur(12px);
}

.page-nav:hover:not(.disabled) {
  background: var(--primary-color);
  color: #fff;
  border-color: var(--primary-color);
  box-shadow: var(--shadow-hover);
  transform: translateY(-50%) translateY(-1px);
}

.page-nav.disabled {
  opacity: 0.35;
  cursor: default;
}

.prev {
  left: -72px;
}

.next {
  right: -72px;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0;
}

.detail-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 22px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-top: 3px solid var(--primary-color);
  border-radius: 8px;
  box-shadow: var(--shadow-soft);
}

.detail-header {
  margin-bottom: 18px;
}

.header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.title {
  font-size: 24px;
  line-height: 1.35;
  margin: 0 0 8px;
  color: var(--text-color);
  font-weight: 800;
}

.title-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.back-btn,
.page-btn {
  padding: 8px 16px;
  border: 1px solid var(--rose-line);
  background: var(--surface);
  color: var(--secondary-color);
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 800;
  transition: all 0.18s ease;
}

.back-btn {
  flex: 0 0 auto;
}

.back-btn:hover,
.page-btn:hover:not(:disabled) {
  background: var(--primary-color);
  border-color: var(--primary-color);
  color: white;
}

.detail-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(292px, 340px);
  gap: 18px;
  align-items: start;
}

.poster-section {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: #f7eef3;
  min-height: 360px;
}

.poster {
  width: 100%;
  height: auto;
  max-height: 640px;
  object-fit: contain;
  object-position: center center;
  display: block;
  background: #f7eef3;
}

.detail-side {
  min-width: 0;
}

.action-row {
  display: flex;
  justify-content: flex-start;
  margin-top: 16px;
}

.btn-download,
.btn-play {
  display: block;
  text-align: center;
  padding: 12px 14px;
  border-radius: 8px;
  text-decoration: none;
  font-weight: 800;
  margin: 0;
  border: 1px solid var(--primary-color);
  font-size: 14px;
  width: 100%;
  line-height: 1.35;
  transition: all 0.18s ease;
}

.btn-download {
  background: var(--primary-color);
  color: white;
  cursor: pointer;
}

.btn-download:hover:not(:disabled) {
  background: var(--secondary-color);
  border-color: var(--secondary-color);
}

.btn-download:disabled {
  opacity: 0.62;
  cursor: not-allowed;
}

.btn-download.error {
  background: #fff5f4;
  border-color: #ffd0cc;
  color: var(--danger-color);
}

.btn-download.success,
.btn-play {
  background: #f4fbf5;
  border-color: #bfe8ca;
  color: var(--success-color);
  cursor: pointer;
}

.btn-download.queued {
  background: #fff9ed;
  border-color: #ffe0ad;
  color: var(--warning-color);
  cursor: default;
}

.btn-download.downloading {
  background: #f3f9ff;
  border-color: #cfe7ff;
  color: var(--info-color);
  cursor: default;
}

.btn-download.waiting {
  background: #fff9ed;
  border-color: #ffe0ad;
  color: var(--warning-color);
  cursor: wait;
}

.queue-hint {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.45;
  color: var(--muted-color);
  font-weight: 600;
}

.queue-hint.error {
  color: var(--danger-color);
}

.info-section {
  min-width: 0;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  margin: 0;
  box-shadow: var(--shadow-soft);
}

.code {
  display: inline-flex;
  padding: 5px 9px;
  border-radius: 999px;
  border: 1px solid var(--rose-line);
  background: var(--surface-2);
  color: var(--secondary-color);
  font-size: 13px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.marked-badge {
  display: inline-block;
  background: #f4fbf5;
  color: var(--success-color);
  border: 1px solid #bfe8ca;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 800;
  animation: fadeInOut 2s ease;
}

.missing-badge {
  display: inline-block;
  background: #fff9ed;
  color: var(--warning-color);
  border: 1px solid #ffe0ad;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 800;
}

.empty-detail {
  max-width: 720px;
}

.missing-content {
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-2);
}

.missing-content p {
  margin: 0 0 14px;
  color: var(--muted-color);
  font-size: 14px;
  line-height: 1.6;
}

.missing-status {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-color);
  font-size: 14px;
  font-weight: 800;
}

.missing-status .label {
  color: var(--muted-color);
  font-size: 12px;
  font-weight: 700;
}

@keyframes fadeInOut {
  0% { opacity: 0; }
  20% { opacity: 1; }
  80% { opacity: 1; }
  100% { opacity: 0; }
}

.section {
  margin: 18px 0;
}

.section:first-child {
  margin-top: 0;
}

.section:last-child {
  margin-bottom: 0;
}

.section h3 {
  font-size: 15px;
  color: var(--text-color);
  margin: 0 0 10px;
  font-weight: 800;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px 6px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid var(--line);
  position: relative;
}

.tag.actress {
  background: #fff4f8;
  border-color: var(--rose-line);
  color: var(--secondary-color);
}

.tag.genre {
  background: #f3f9ff;
  border-color: #cfe7ff;
  color: var(--info-color);
}

.tag.genre .block-btn,
.tag.genre .block-confirm,
.tag.genre .block-yes,
.tag.genre .block-no {
  position: absolute;
  top: -30px;
  z-index: 8;
  white-space: nowrap;
  box-shadow: var(--shadow-soft);
}

.tag.genre .block-btn {
  left: 50%;
  opacity: 0;
  pointer-events: none;
  transform: translateX(-50%) translateY(3px);
}

.tag.genre .block-btn.visible {
  opacity: 1;
  pointer-events: auto;
  transform: translateX(-50%) translateY(0);
}

.tag.genre .block-confirm {
  left: 0;
  padding: 4px 6px;
  border-radius: 6px;
  background: #fff5f4;
  border: 1px solid #ffd0cc;
}

.tag.genre .block-yes {
  left: 44px;
}

.tag.genre .block-no {
  left: 84px;
}

.fav-btn,
.block-btn,
.block-yes,
.block-no {
  border-radius: 6px;
  cursor: pointer;
  font-size: 11px;
  line-height: 1;
  padding: 4px 6px;
  font-weight: 800;
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease, opacity 0.18s ease, transform 0.18s ease;
}

.fav-btn {
  background: white;
  border: 1px solid var(--rose-line);
  color: var(--secondary-color);
}

.fav-btn.faved {
  background: var(--primary-color);
  border-color: var(--primary-color);
  color: white;
}

.block-btn,
.block-yes {
  background: #fff5f4;
  border: 1px solid #ffd0cc;
  color: var(--danger-color);
}

.block-btn:hover,
.block-yes:hover {
  background: var(--danger-color);
  border-color: var(--danger-color);
  color: white;
}

.block-confirm {
  font-size: 11px;
  color: var(--danger-color);
  font-weight: 800;
}

.block-no {
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--muted-color);
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
  margin: 16px 0;
}

.preview-section {
  margin: 18px 0 0;
}

.info-item {
  background: var(--surface-2);
  border: 1px solid var(--line);
  padding: 10px;
  border-radius: 8px;
}

.info-item .label {
  display: block;
  font-size: 11px;
  color: var(--muted-color);
  font-weight: 800;
  margin-bottom: 4px;
}

.info-item span:last-child {
  font-size: 14px;
  color: var(--text-color);
  font-weight: 700;
}

.fanarts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.fanart-item {
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
  aspect-ratio: 16/9;
  border: 1px solid var(--line);
  box-shadow: var(--shadow-soft);
}

.fanart-item:hover {
  transform: translateY(-2px);
  border-color: var(--rose-line);
  box-shadow: var(--shadow-hover);
}

.fanart-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.22s ease;
}

.fanart-item:hover .fanart-img {
  transform: scale(1.03);
}

.lightbox {
  position: fixed;
  inset: 0;
  background: rgba(53, 36, 44, 0.88);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(10px);
}

.lightbox-content {
  position: relative;
  max-width: 90vw;
  max-height: 90vh;
}

.lightbox-image {
  max-width: 90vw;
  max-height: 80vh;
  display: block;
  margin: 0 auto;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.24);
  box-shadow: 0 18px 42px rgba(53, 36, 44, 0.34);
  user-select: none;
  -webkit-user-select: none;
  pointer-events: none;
}

.lightbox-close,
.lightbox-nav,
.lightbox-counter {
  color: white;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.22);
  border-radius: 8px;
  font-size: 13px;
  font-weight: 800;
}

.lightbox-close {
  position: absolute;
  top: -42px;
  right: 0;
  cursor: pointer;
  padding: 7px 12px;
}

.lightbox-close:hover,
.lightbox-nav:hover {
  background: rgba(255, 255, 255, 0.32);
  border-color: rgba(255, 255, 255, 0.45);
}

.lightbox-nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 68px;
  height: 40px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.18s ease, border-color 0.18s ease;
}

.lightbox-prev {
  left: -82px;
}

.lightbox-next {
  right: -82px;
}

.lightbox-counter {
  position: absolute;
  bottom: -40px;
  left: 50%;
  transform: translateX(-50%);
  padding: 5px 14px;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  margin-top: 24px;
  padding: 12px 0;
}

.top-pagination {
  justify-content: flex-end;
  margin: 0;
  padding: 0;
  flex: 0 0 auto;
}

.page-info {
  font-size: 14px;
  color: var(--secondary-color);
  font-weight: 800;
  min-width: 80px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.page-btn:disabled {
  opacity: 0.35;
  cursor: default;
}

.page-end {
  padding: 8px 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--muted-color);
  background: var(--surface);
  font-size: 14px;
  font-weight: 800;
}

@media (max-width: 1400px) {
  .prev { left: 12px; }
  .next { right: 12px; }
}

@media (max-width: 900px) {
  .detail-hero {
    grid-template-columns: 1fr;
  }

  .poster {
    width: 100%;
    max-height: none;
  }
}

@media (max-width: 768px) {
  .detail-container {
    padding: 16px;
  }

  .header-top {
    align-items: flex-start;
    flex-direction: column;
  }

  .top-pagination {
    justify-content: flex-start;
    width: 100%;
  }

  .page-nav {
    width: 40px;
    height: 40px;
  }

  .prev { left: 8px; }
  .next { right: 8px; }

  .info-section {
    padding: 14px;
  }

  .lightbox-nav {
    top: auto;
    bottom: -52px;
  }

  .lightbox-prev {
    left: 0;
  }

  .lightbox-next {
    right: 0;
  }
}
</style>
