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
                                            <button class="block-yes" @click.stop="doBlock(a)">确认</button>
                                            <button class="block-no" @click.stop="blockingName = null">取消</button>
                                        </template>
                                        <button v-else class="block-btn" @click.stop="blockingName = a" title="屏蔽此女优">屏蔽</button>
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
                                            <button class="block-yes" @click.stop="doBlockGenre(g)">确认</button>
                                            <button class="block-no" @click.stop="blockingGenre = null">取消</button>
                                        </template>
                                        <button v-else class="block-btn" :class="{ visible: hoverGenre === g }" @mouseenter.stop="showGenreActions(g)" @mouseleave.stop="hideGenreActions(g)" @click.stop="blockingGenre = g" title="屏蔽此标签">屏蔽</button>
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
                                    :disabled="queueState === 'adding'">
                                    {{ queueState === 'error' ? '添加失败，重试' : '加入下载队列' }}
                                </button>
                                <button v-if="queueState === 'adding'" class="btn-download" disabled>添加中...</button>
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
                    <div v-if="showLightbox" class="lightbox" @click="handleLightboxClick">
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
            keyNavPressed: null
        }
    },
    computed: {
        fanartList() {
            return this.video?.fanarts || []
        },
        mediaKey() {
            return normalizeVideoID(this.video?.id || this.id)
        },
        queueStateLabel() {
            if (this.queueState === 'downloading') return `下载中 ${this.queueProgress}%`
            if (this.queueState === 'queued') return '等待中'
            if (this.queueState === 'failed') return '下载失败'
            if (this.queueState === 'adding') return '添加中'
            if (this.queueState === 'success') return '已加入队列'
            return '未在队列中'
        }
    },
    async created() {
        window.addEventListener('av-garden-status', this.handleGlobalStatus)
        window.dispatchEvent(new CustomEvent('av-garden-refresh-status'))
        window.addEventListener('keydown', this.handlePageKeydown, true)
        window.addEventListener('keyup', this.handlePageKeyup, true)
        this.unlockPageScroll()
        this.loadWatched()
        this.syncWatched().then(() => {
            if (weeklyDetailCache.items) this.rebuildBrowseList(this.id)
        })
        await this.loadRoute(this.id)
    },
    async beforeRouteUpdate(to, from, next) {
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
    },
    beforeRouteLeave(to, from, next) {
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

                this.trackView(targetId)
                this.markWatched(targetId)

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
                if (this.setVideoFromCurrentList(targetId)) {
                    this.syncQueueState(window.avGardenQueueStatus || [], targetId)
                    return true
                }

                const all = await this.getWeeklyItems()
                if (token !== this.routeLoadToken) return false
                this.rebuildBrowseList(targetId, all)
                if (token !== this.routeLoadToken) return false
                this.syncQueueState(window.avGardenQueueStatus || [], targetId)
                this.detailMissing = !this.video
                return true
            } catch (e) {
                if (token !== this.routeLoadToken) return false
                console.error(e)
                this.detailMissing = true
                return false
            }
        },
        async getWeeklyItems() {
            const now = Date.now()
            if (weeklyDetailCache.items && now - weeklyDetailCache.fetchedAt < WEEKLY_CACHE_MS) {
                return weeklyDetailCache.items
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
        rebuildBrowseList(targetId, weeklyItems = weeklyDetailCache.items || []) {
            const normalizedTarget = normalizeVideoID(targetId)
            const canonicalTarget = canonicalVideoID(targetId)
            const allById = new Map(weeklyItems.map(v => [normalizeVideoID(v.id), v]))
            const undownloaded = weeklyItems.filter(v => !v.downloaded)
            const tab = this.$route.query.tab || 'unwatched'
            const savedIds = this.readBrowseState(tab, canonicalTarget)

            if (savedIds) {
                this.allVideos = savedIds.map(id => allById.get(normalizeVideoID(id))).filter(Boolean)
            } else if (tab === 'watched') {
                this.allVideos = undownloaded.filter(v => this.isWatched(v.id))
            } else {
                this.allVideos = undownloaded.filter(v => !this.isWatched(v.id))
            }

            if (!this.allVideos.some(v => normalizeVideoID(v.id) === canonicalTarget)) {
                const current = allById.get(normalizedTarget) || allById.get(canonicalTarget)
                if (current) this.allVideos = [current, ...this.allVideos]
            }

            this.saveBrowseState(tab, this.allVideos)
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
            this.$router.push('/weekly')
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
                query: { tab: this.$route.query.tab || 'unwatched' }
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
                    return
                }
                if (this.queueState !== 'adding' && this.queueState !== 'error') {
                    this.queueState = 'idle'
                    this.queueProgress = 0
                }
                return
            }
            this.queueProgress = current.progress || 0
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
            this.blockingName = null
            try {
                const resp = await fetch('/api/block-actress/' + encodeURIComponent(name), {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${import.meta.env.VITE_API_KEY || ''}` }
                })
                if (resp.ok) this.goNextAfterBlock()
            } catch (e) {}
        },
        goNextAfterBlock() {
            if (this.currentIndex < this.allVideos.length - 1) {
                const next = this.allVideos[this.currentIndex + 1]
                this.$router.replace({ name: 'weekly-detail', params: { id: next.id } })
            } else if (this.currentIndex > 0) {
                const prev = this.allVideos[this.currentIndex - 1]
                this.$router.replace({ name: 'weekly-detail', params: { id: prev.id } })
            } else {
                this.$router.replace('/weekly')
            }
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
            this.blockingGenre = null
            try {
                const resp = await fetch('/api/block-genre/' + encodeURIComponent(name), {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${import.meta.env.VITE_API_KEY || ''}` }
                })
                if (resp.ok) this.goNextAfterBlock()
            } catch (e) {}
        },
        async addToQueue() {
            const targetId = normalizeVideoID(this.video?.id || this.id)
            this.queueState = 'adding'
            this.queueSubmittedAt = Date.now()
            this.queueSubmittedId = targetId
            try {
                const resp = await fetch('/api/queue/', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({code: targetId})
                })
                if (resp.ok) {
                    this.queueState = 'queued'
                    this.showToast(targetId + ' 已加入下载队列', 'info')
                    window.dispatchEvent(new CustomEvent('av-garden-refresh-status'))
                } else {
                    this.queueState = 'error'
                    this.queueSubmittedAt = 0
                    this.queueSubmittedId = ''
                    this.showToast(targetId + ' 加入下载队列失败，请重试', 'warn')
                }
            } catch (e) {
                this.queueState = 'error'
                this.queueSubmittedAt = 0
                this.queueSubmittedId = ''
                this.showToast(targetId + ' 加入下载队列失败，请重试', 'warn')
            }
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
        },
        handleLightboxClick(e) {
            // Click on left half for previous, right half for next.
            const rect = e.currentTarget.getBoundingClientRect()
            const x = e.clientX - rect.left
            if (x < rect.width / 2) {
                this.prevImage()
            } else {
                this.nextImage()
            }
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
