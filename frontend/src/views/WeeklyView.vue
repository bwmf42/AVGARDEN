<template>
    <div class="container">
        <div class="weekly-hero">
            <div>
                <span>每日推荐</span>
                <h1>{{ query.actor ? query.actor + '的已收录作品' : '筛选每日推荐' }}</h1>
                <p>按字幕、演员、标签、时长和发行日期筛选已收录的作品。</p>
                <button v-if="query.actor" class="filter-button" @click="change('actor', '')">返回全部演员</button>
            </div>
            <div class="weekly-count">{{ filteredVideos.length }} / {{ weeklyItems.length }} 项</div>
        </div>
        <div class="sub-tabs" aria-label="浏览状态">
            <button v-for="[value, label] in tabs" :key="value" :class="['sub-tab', {active: activeTab === value}]" @click="change('tab', value)">{{ label }}</button>
        </div>
        <section class="weekly-filters" aria-label="推荐筛选">
            <label>字幕<select :value="query.chinese || ''" @change="change('chinese', $event.target.value)"><option value="">全部</option><option value="yes">有中文字幕</option><option value="unknown">未确认中文</option></select></label>
            <label>演员<select :value="query.actor || ''" @change="change('actor', $event.target.value)"><option value="">全部演员</option><option v-for="actor in actors" :key="actor">{{ actor }}</option></select></label>
            <label class="check"><input type="checkbox" :checked="query.fav === '1'" @change="change('fav', $event.target.checked ? '1' : '')">只看收藏演员</label>
            <label>时长<select :value="query.duration || ''" @change="change('duration', $event.target.value)"><option value="">全部</option><option value="short">90 分钟及以内</option><option value="medium">91–150 分钟</option><option value="long">超过 150 分钟</option><option value="unknown">时长未知</option></select></label>
            <label>作品状态<select :value="query.availability || ''" @change="change('availability', $event.target.value)"><option value="">全部已收录</option><option value="pending">未在本地</option><option value="local">已在本地</option><option value="queued">队列中</option></select></label>
            <label>发行起日<input type="date" :value="query.from || ''" @change="change('from', $event.target.value)"></label>
            <label>发行止日<input type="date" :value="query.to || ''" @change="change('to', $event.target.value)"></label>
            <label class="check"><input type="checkbox" :checked="query.dateUnknown === '1'" @change="unknownDate($event.target.checked)">发行日未知</label>
            <details class="genre-filters"><summary>标签组合与临时排除 <span v-if="query.include || query.exclude">（已筛选）</span></summary>
                <p>必须同时包含所有选中标签；任一排除标签命中即隐藏。</p>
                <div v-for="genre in genres" :key="genre" class="genre-choice"><span>{{ genre }}</span><button :class="{chosen: includes.includes(genre)}" :aria-pressed="includes.includes(genre)" @click="toggleGenre('include',genre)">包含</button><button :class="{chosen: excludes.includes(genre)}" :aria-pressed="excludes.includes(genre)" @click="toggleGenre('exclude',genre)">排除</button></div>
            </details>
            <button class="filter-button" @click="$router.replace({name:'weekly',query:{tab:query.tab || 'unwatched'}})">清除筛选</button>
        </section>
        <p v-if="error" role="alert" class="selection-error">{{ error }} <button @click="loadData">重试</button></p>
        <div v-if="loading" class="loading">加载中...</div>
        <div v-else-if="!filteredVideos.length" class="loading">没有符合条件的作品，可以调整筛选或切换浏览状态。</div>
        <div v-else class="video-grid">
            <div v-for="video in filteredVideos" :key="video.id" class="video-card" role="button" tabindex="0" @click="openVideo(video)" @keydown.enter="openVideo(video)">
                <div class="cover-container" :class="{watched: selections[video.id]}">
                    <img class="cover" :src="video.cover || video.poster" :alt="video.title" loading="lazy">
                    <div v-if="video.hasChinese" class="badge chinese">中文</div>
                </div>
                <div class="info"><h3>{{ displayTitle(video) }}</h3><div v-if="video.actresses?.length" class="actresses">{{ video.actresses.slice(0,2).join(' / ') }}</div><div class="selection-meta">{{ video.downloaded ? '已在本地' : video.queueStatus ? '队列中' : '已收录' }}</div></div>
            </div>
        </div>
    </div>
</template>
<script>
import { loadSelections } from '../api/weeklySelection'
import { displayTitle } from '../utils/displayTitle'
import { filterWeekly, selectionTabs, saveBrowseContext, readBrowseContext } from '../utils/weeklyFilters'
export default {
    name: 'WeeklyView',
    data: () => ({ weeklyItems: [], selections: {}, favorites: [], loading: true, error: '', tabs: selectionTabs, loaded: false }),
    computed: {
        query() { return this.$route.query },
        activeTab() { return ['unwatched', 'watched', 'all'].includes(this.query.tab) ? this.query.tab : 'unwatched' },
        actors() { return [...new Set([...this.weeklyItems.flatMap(v => v.actresses || []), ...(this.query.actor ? [this.query.actor] : [])])].sort() },
        genres() { return [...new Set(this.weeklyItems.flatMap(v => v.genres || []))].sort() },
        includes() { return String(this.query.include || '').split(',').filter(Boolean) },
        excludes() { return String(this.query.exclude || '').split(',').filter(Boolean) },
        filteredVideos() { return filterWeekly(this.weeklyItems, this.query, this.selections, this.favorites) }
    },
    async created() {
        window.addEventListener('av-garden-weekly-refresh', this.loadData)
        window.addEventListener('av-garden-selection', this.onSelection)
        await this.loadData()
    },
    async activated() { if (this.loaded) await this.loadData() },
    beforeUnmount() {
        window.removeEventListener('av-garden-weekly-refresh', this.loadData)
        window.removeEventListener('av-garden-selection', this.onSelection)
    },
    methods: {
        onSelection(event) { this.selections = {...this.selections, [event.detail.id]: event.detail} },
        async loadData() {
            this.error = ''
            try {
                const [items, states, favs] = await Promise.all([
                    fetch('/api/weekly').then(r => { if (!r.ok) throw Error('推荐列表加载失败'); return r.json() }),
                    loadSelections(),
                    fetch('/api/fav-actress/').then(r => { if (!r.ok) throw Error('收藏演员加载失败'); return r.json() })
                ])
                this.weeklyItems = items; this.selections = states; this.favorites = favs
                const context = readBrowseContext()
                await this.$nextTick()
                if (context && JSON.stringify(context.query) === JSON.stringify(this.query)) window.scrollTo(0, context.scroll || 0)
            } catch(e) { this.error = e.message }
            finally { this.loading = false; this.loaded = true }
        },
        change(key, value) {
            const query = {...this.query}
            if (value) query[key] = value; else delete query[key]
            if (key === 'from' || key === 'to') delete query.dateUnknown
            this.$router.replace({name:'weekly',query})
        },
        unknownDate(on) {
            const query = {...this.query}; delete query.from; delete query.to
            if (on) query.dateUnknown='1'; else delete query.dateUnknown
            this.$router.replace({name:'weekly',query})
        },
        toggleGenre(key, genre) {
            const values = new Set(key === 'include' ? this.includes : this.excludes)
            if (values.has(genre)) values.delete(genre); else values.add(genre)
            const other = key === 'include' ? 'exclude' : 'include'
            const query = {...this.query, [key]: [...values].join(','), [other]: String(this.query[other] || '').split(',').filter(g => g !== genre).join(',')}
            if (!query[key]) delete query[key]; if (!query[other]) delete query[other]
            this.$router.replace({name:'weekly',query})
        },
        displayTitle(video) { return displayTitle(video, {withCode:true,maxLen:50}) },
        openVideo(video) {
            saveBrowseContext(this.filteredVideos, {...this.query}, window.scrollY)
            this.$router.push({name:'weekly-detail',params:{id:video.id},query:{...this.query,browse:'selection'}})
        }
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

.weekly-hero span {
  color: var(--secondary-color);
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.08em;
}

.weekly-hero h1 {
  margin: 10px 0 10px;
  max-width: 540px;
  color: var(--text-color);
  font-size: clamp(32px, 4vw, 56px);
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

/* Badges */
.badge { position: absolute; padding: 4px 8px; border-radius: 999px; font-size: 11px; font-weight: 800; z-index: 2; }
.badge.downloaded { bottom: 8px; right: 8px; background: rgba(40, 122, 67, 0.9); color: white; }
.badge.undownloaded { bottom: 8px; right: 8px; background: rgba(186, 47, 93, 0.9); color: white; }
.badge.chinese { top: 8px; left: 8px; background: rgba(161, 92, 0, 0.9); color: white; }

/* Watch toggle button */
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
<style scoped>
.weekly-filters { display:flex; flex-wrap:wrap; align-items:end; gap:14px; padding:18px; margin-bottom:20px; background:var(--surface); border:1px solid var(--rose-line); border-radius:8px }
.weekly-filters label { display:flex; flex-direction:column; gap:6px; font-size:13px; color:var(--muted-color) }
.weekly-filters select,.weekly-filters input[type=date] { min-height:40px; max-width:220px; padding:8px; background:white; color:var(--text-color); border:1px solid var(--rose-line); border-radius:6px; font:inherit }
.weekly-filters .check { flex-direction:row; align-items:center; min-height:40px }
.genre-filters { flex-basis:100%; font-size:13px }
.genre-filters summary { cursor:pointer; padding:8px 0; color:var(--secondary-color) }
.genre-choice { display:inline-flex; align-items:center; gap:6px; margin:4px 10px 4px 0; padding:6px; border:1px solid var(--rose-line); border-radius:6px }
.genre-choice button,.filter-button { cursor:pointer; border:1px solid var(--rose-line); border-radius:6px; background:white; color:var(--secondary-color); padding:8px 10px }
.genre-choice .chosen { background:var(--secondary-color); color:white }
.selection-error { color:var(--error-color,#a22); padding:12px }
.selection-meta { color:var(--muted-color); font-size:12px; margin-top:5px }
@media(max-width:640px) { .weekly-filters {padding:12px;gap:10px} .weekly-filters label { flex:1 1 130px } .weekly-filters select,.weekly-filters input[type=date] {max-width:100%;width:100%;box-sizing:border-box} .sub-tabs {flex-wrap:wrap} }
</style>
