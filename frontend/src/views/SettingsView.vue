<template>
    <div class="container">
        <h1 class="page-title">设置</h1>

        <div class="tabs">
            <button v-for="t in tabs" :key="t.key" :class="['tab', { active: activeTab === t.key }]" @click="activeTab = t.key">
                {{ t.label }}
            </button>
        </div>

        <div class="section scrape-section">
            <div class="scrape-copy">
                <h2>周推荐刮削</h2>
                <p>{{ scrapeMessage }}</p>
            </div>
            <button class="scrape-btn" :disabled="scrapeRunning" @click="runWeeklyScrape">
                {{ scrapeRunning ? '刮削中...' : '手动刮削' }}
            </button>
        </div>

        <div class="section block-code-section">
            <h2>115 云下载</h2>
            <p class="hint">
                配置 Cookie 并<strong>测试连接通过</strong>后，详情页「加入 115」才可用（与「加入 qB」并列）。
                磁链提交到 115「云下载」（原离线下载）；网盘路径需与极空间「115生活」自动备份的源文件夹一致（如 /艾薇）。
                本地落盘由极空间备份完成，AVGARDEN 不显示本机进度。
            </p>
            <label class="field-label">
                <input type="checkbox" v-model="p115.enabled" />
                启用「加入 115」按钮
            </label>
            <div class="add-row">
                <input
                    v-model="p115.save_path"
                    class="add-input"
                    placeholder="网盘保存路径，如 /艾薇"
                />
            </div>
            <div class="add-row">
                <textarea
                    v-model="p115.cookies"
                    class="add-input p115-cookie-area"
                    autocomplete="off"
                    rows="4"
                    :placeholder="p115.has_cookies
                        ? '已保存 Cookie（留空则不修改）。可重新粘贴：整段 cookie 头，或开发者工具 Cookies 整表'
                        : '粘贴即可：① 请求头 cookie 一行  ② 或 Application→Cookies 整表（自动提取 UID/CID/SEID/KID）'"
                />
            </div>
            <p class="hint">支持整表粘贴，服务端会自动识别 UID/CID/SEID/KID 等，忽略 acw_tc。</p>
            <div class="add-row p115-actions">
                <button class="add-btn" :disabled="p115Busy" @click="saveP115">
                    {{ p115Busy ? '保存中…' : '保存 115 配置' }}
                </button>
                <button class="scrape-btn" :disabled="p115Busy" @click="testP115">
                    测试连接
                </button>
            </div>
            <p v-if="p115Msg" class="block-code-msg" :class="{ err: p115Err }">{{ p115Msg }}</p>
            <p v-if="p115.has_cookies" class="hint">
                Cookie：{{ p115.cookies_hint || '已配置' }}
                · 测试：{{ p115.verified ? '已通过' : '未通过（请点测试连接）' }}
                · 按钮：{{ p115.available ? '可用' : '不可用' }}
            </p>
        </div>

        <div class="section block-code-section">
            <h2>按番号屏蔽女优</h2>
            <p class="hint">输入番号，查询并选择要屏蔽的女优。</p>
            <div class="add-row">
                <input
                    v-model="blockCode"
                    class="add-input"
                    placeholder="输入番号，如 SNOS-233"
                    :disabled="blockCodeBusy"
                    @input="resetBlockLookup"
                    @keyup.enter="lookupBlockCode"
                />
                <button class="add-btn" :disabled="blockCodeBusy || !blockCode.trim()" @click="lookupBlockCode">
                    {{ blockCodeBusy ? '查询中…' : '查询女优' }}
                </button>
            </div>
            <p v-if="blockCodeMsg" class="block-code-msg" :class="{ err: blockCodeErr }">{{ blockCodeMsg }}</p>
            <div v-if="blockCandidates.length" class="candidate-list">
                <label
                    v-for="name in blockCandidates"
                    :key="name"
                    class="candidate-item"
                >
                    <input type="checkbox" :value="name" v-model="blockSelected" :disabled="blockCodeBusy" />
                    <span>{{ name }}</span>
                </label>
            </div>
            <button
                v-if="blockCandidates.length"
                class="scrape-btn block-selected-btn"
                :disabled="blockCodeBusy || blockSelected.length === 0"
                @click="submitBlockSelected"
            >
                屏蔽所选（{{ blockSelected.length }}）
            </button>
        </div>

        <div class="section">
            <div class="add-row">
                <input v-model="newItem" :placeholder="'添加' + currentTab.label" class="add-input"
                    @keyup.enter="addItem" />
                <button class="add-btn" @click="addItem">添加</button>
            </div>

            <div class="list">
                <div v-for="item in currentList" :key="item" class="list-item">
                    <span
                        :class="{ 'item-link': activeTab === 'genres' }"
                        :title="activeTab === 'genres' ? '浏览该标签作品' : undefined"
                        @click="activeTab === 'genres' && browseGenre(item)"
                    >{{ item }}</span>
                    <button class="del-btn" @click="removeItem(item)">移除</button>
                </div>
                <div v-if="currentList.length === 0" class="empty">暂无</div>
            </div>
        </div>
    </div>
</template>

<script>
const ENDPOINTS = {
    actresses: '/api/block-actress/',
    genres: '/api/block-genre/',
    favs: '/api/fav-actress/',
    keywords: '/api/block-keyword/',
}

export default {
    name: 'SettingsView',
    data() {
        return {
            activeTab: 'actresses',
            newItem: '',
            actresses: [],
            genres: [],
            favs: [],
            keywords: [],
            scrapeRunning: false,
            scrapeMessage: '手动更新每日推荐，适合错过当天自动刮削时使用。',
            blockCode: '',
            blockCodeBusy: false,
            blockCodeMsg: '',
            blockCodeErr: false,
            blockCandidates: [],
            blockSelected: [],
            blockSource: '',
            blockResolvedCode: '',
            p115: {
                enabled: false,
                save_path: '/艾薇',
                cookies: '',
                has_cookies: false,
                cookies_hint: '',
                verified: false,
                available: false,
            },
            p115Busy: false,
            p115Msg: '',
            p115Err: false,
        }
    },
    computed: {
        tabs() {
            return [
                { key: 'actresses', label: '屏蔽女优' },
                { key: 'genres', label: '屏蔽标签' },
                { key: 'favs', label: '收藏女优' },
                { key: 'keywords', label: '标题关键词' },
            ]
        },
        currentTab() { return this.tabs.find(t => t.key === this.activeTab) || this.tabs[0] },
        currentList() { return this[this.activeTab] || [] },
    },
    async created() {
        await this.loadAll()
        await this.loadP115()
    },
    methods: {
        async loadAll() {
            await this.loadList('actresses')
            await this.loadList('genres')
            await this.loadList('favs')
            await this.loadList('keywords')
        },
        applyP115Config(d) {
            if (!d || typeof d !== 'object') return
            this.p115.enabled = !!d.enabled
            this.p115.save_path = d.save_path || '/艾薇'
            this.p115.has_cookies = !!d.has_cookies
            this.p115.cookies_hint = d.cookies_hint || ''
            this.p115.verified = !!d.verified
            this.p115.available = !!d.available
        },
        async loadP115() {
            try {
                const r = await fetch('/api/p115/config')
                if (!r.ok) return
                this.applyP115Config(await r.json())
            } catch (e) { /* ignore */ }
        },
        async saveP115(opts = {}) {
            const silent = !!opts.silent
            this.p115Busy = true
            if (!silent) {
                this.p115Msg = ''
                this.p115Err = false
            }
            try {
                const body = {
                    enabled: this.p115.enabled,
                    save_path: this.p115.save_path,
                }
                if (this.p115.cookies && this.p115.cookies.trim()) {
                    body.cookies = this.p115.cookies.trim()
                }
                const r = await fetch('/api/p115/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                })
                const d = await r.json().catch(() => ({}))
                if (!r.ok) {
                    this.p115Err = true
                    this.p115Msg = d.error || '保存失败'
                    return false
                }
                this.applyP115Config(d)
                this.p115.cookies = ''
                if (!silent) {
                    if (!d.has_cookies) {
                        this.p115Msg = '已保存路径；请粘贴 Cookie 后点「测试连接」'
                    } else if (!d.enabled) {
                        this.p115Msg = '已保存（未启用按钮）。启用后请点「测试连接」'
                    } else {
                        this.p115Msg = '已保存。请点「测试连接」——通过后详情页才可用「加入 115」'
                    }
                }
                return true
            } catch (e) {
                this.p115Err = true
                this.p115Msg = '保存请求失败'
                return false
            } finally {
                this.p115Busy = false
            }
        },
        async testP115() {
            this.p115Busy = true
            this.p115Msg = ''
            this.p115Err = false
            try {
                // save first if user typed cookies / changed path
                const saved = await this.saveP115({ silent: true })
                if (!saved) return
                this.p115Busy = true
                const r = await fetch('/api/p115/test', { method: 'POST' })
                const d = await r.json().catch(() => ({}))
                this.applyP115Config(d)
                this.p115Err = !d.ok
                if (d.ok) {
                    this.p115Msg = d.enabled
                        ? (d.message || '测试通过') + ' — 详情页「加入 115」已可用'
                        : (d.message || '测试通过') + ' — 请勾选启用后才显示按钮'
                } else {
                    this.p115Msg = d.message || '测试失败'
                }
            } catch (e) {
                this.p115Err = true
                this.p115Msg = '测试请求失败'
            } finally {
                this.p115Busy = false
            }
        },
        async loadList(key) {
            try {
                const r = await fetch(ENDPOINTS[key])
                if (r.ok) {
                    this[key] = await r.json()
                }
            } catch (e) { }
        },
        async addItem() {
            const v = this.newItem.trim()
            if (!v) return
            const url = ENDPOINTS[this.activeTab]
            try {
                await fetch(url + encodeURIComponent(v), { method: 'POST' })
                if (this.activeTab === 'actresses') {
                    const idx = this.actresses.indexOf(v)
                    if (idx >= 0) this.actresses.splice(idx, 1)
                    this.actresses.unshift(v)
                } else if (!this.currentList.includes(v)) {
                    this.currentList.push(v)
                }
                this.newItem = ''
            } catch (e) { }
        },
        async removeItem(item) {
            const url = ENDPOINTS[this.activeTab]
            try {
                await fetch(url + encodeURIComponent(item), { method: 'POST' })
                const idx = this.currentList.indexOf(item)
                if (idx >= 0) this.currentList.splice(idx, 1)
            } catch (e) { }
        },
        async runWeeklyScrape() {
            if (this.scrapeRunning) return
            this.scrapeRunning = true
            this.scrapeMessage = '正在抓取并更新周推荐，完成前不要重复点击。'
            try {
                const resp = await fetch('/api/weekly/scrape', { method: 'POST' })
                const data = await resp.json().catch(() => ({}))
                if (!resp.ok) {
                    this.scrapeMessage = data.message || '刮削失败，请稍后重试。'
                    return
                }
                this.scrapeMessage = data.message || '周推荐刮削完成。'
            } catch (e) {
                this.scrapeMessage = '刮削请求失败，请检查服务状态。'
            } finally {
                this.scrapeRunning = false
            }
        },
        browseGenre(tag) {
            const name = String(tag || '').trim()
            if (!name) return
            this.$router.push({ name: 'weekly-genre', params: { tag: name } })
        },
        resetBlockLookup() {
            if (this.blockCodeBusy) return
            this.blockCodeMsg = ''
            this.blockCodeErr = false
            this.blockCandidates = []
            this.blockSelected = []
            this.blockSource = ''
            this.blockResolvedCode = ''
        },
        async lookupBlockCode() {
            const code = String(this.blockCode || '').trim()
            if (!code || this.blockCodeBusy) return
            this.blockCodeBusy = true
            this.blockCodeMsg = ''
            this.blockCodeErr = false
            this.blockCandidates = []
            this.blockSelected = []
            this.blockSource = ''
            this.blockResolvedCode = ''
            try {
                const resp = await fetch('/api/block-by-code/' + encodeURIComponent(code))
                const data = await resp.json().catch(() => ({}))
                if (!resp.ok) {
                    this.blockCodeErr = true
                    this.blockCodeMsg = data.message || data.error || '未找到女优'
                    return
                }
                const list = Array.isArray(data.actresses) ? data.actresses.filter(Boolean) : []
                this.blockCandidates = list
                this.blockSource = data.source || ''
                this.blockResolvedCode = data.code || code
                this.blockCodeMsg = data.message || `找到 ${list.length} 人`
                // 单人默认勾选；多人默认不勾，避免误伤
                this.blockSelected = list.length === 1 ? [...list] : []
            } catch (e) {
                this.blockCodeErr = true
                this.blockCodeMsg = '查询失败，请检查服务状态'
            } finally {
                this.blockCodeBusy = false
            }
        },
        async submitBlockSelected() {
            const code = String(this.blockResolvedCode || '').trim()
            const names = (this.blockSelected || []).filter(Boolean)
            if (!code || !names.length || this.blockCodeBusy) return
            this.blockCodeBusy = true
            this.blockCodeErr = false
            try {
                const resp = await fetch('/api/block-by-code/' + encodeURIComponent(code), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ actresses: names }),
                })
                const data = await resp.json().catch(() => ({}))
                if (!resp.ok) {
                    this.blockCodeErr = true
                    this.blockCodeMsg = data.error || data.message || '屏蔽失败'
                    return
                }
                this.blockCodeMsg = data.message || '已屏蔽'
                // refresh list: newest first for blocked
                for (const n of (data.blocked || names).slice().reverse()) {
                    const idx = this.actresses.indexOf(n)
                    if (idx >= 0) this.actresses.splice(idx, 1)
                    this.actresses.unshift(n)
                }
                const handled = new Set([...(data.blocked || []), ...(data.already || [])])
                this.blockCandidates = this.blockCandidates.filter(name => !handled.has(name))
                this.blockSelected = []
                await this.loadList('actresses')
            } catch (e) {
                this.blockCodeErr = true
                this.blockCodeMsg = '屏蔽请求失败'
            } finally {
                this.blockCodeBusy = false
            }
        },
    }
}
</script>

<style scoped>
.container {
  max-width: 660px;
  margin: 0 auto;
}

.page-title {
  color: var(--text-color);
  font-size: 24px;
  font-weight: 800;
  margin: 0 0 1.25rem;
  position: relative;
  display: inline-block;
}

.page-title::after {
  content: '';
  position: absolute;
  left: 0;
  bottom: -8px;
  width: 42px;
  height: 2px;
  background: var(--primary-color);
}

.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}

.tab {
  padding: 8px 13px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--muted-color);
  border-radius: 999px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 800;
  transition: all 0.18s ease;
}

.tab:hover {
  border-color: var(--rose-line);
  color: var(--secondary-color);
}

.tab.active {
  background: var(--secondary-color);
  border-color: var(--secondary-color);
  color: white;
}

.section {
  background: var(--surface);
  border: 1px solid var(--line);
  border-top: 3px solid var(--primary-color);
  border-radius: 8px;
  padding: 18px;
  box-shadow: var(--shadow-soft);
}

.scrape-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.scrape-copy {
  min-width: 0;
}

.scrape-copy h2 {
  margin: 0 0 6px;
  color: var(--text-color);
  font-size: 16px;
  font-weight: 800;
}

.scrape-copy p {
  margin: 0;
  color: var(--muted-color);
  font-size: 13px;
  line-height: 1.5;
}

.add-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}

.p115-cookie-area {
  min-height: 88px;
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.4;
  padding: 10px 12px;
}

.add-input {
  flex: 1;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--rose-line);
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  background: var(--surface);
  color: var(--text-color);
}

.add-input:focus {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(232, 77, 122, 0.12);
}

.add-btn {
  padding: 10px 18px;
  background: var(--primary-color);
  color: white;
  border: 1px solid var(--primary-color);
  border-radius: 8px;
  cursor: pointer;
  font-weight: 800;
  transition: all 0.18s ease;
}

.add-btn:hover {
  background: var(--secondary-color);
  border-color: var(--secondary-color);
}

.scrape-btn {
  flex: 0 0 auto;
  padding: 10px 18px;
  background: var(--primary-color);
  color: white;
  border: 1px solid var(--primary-color);
  border-radius: 8px;
  cursor: pointer;
  font-weight: 800;
  transition: all 0.18s ease;
}

.scrape-btn:hover:not(:disabled) {
  background: var(--secondary-color);
  border-color: var(--secondary-color);
}

.scrape-btn:disabled {
  cursor: wait;
  opacity: 0.68;
}

.block-code-section h2 {
  margin: 0 0 6px;
  color: var(--text-color);
  font-size: 16px;
  font-weight: 800;
}

.block-code-section .hint {
  margin: 0 0 12px;
  color: var(--muted-color);
  font-size: 13px;
  line-height: 1.5;
}

.block-code-msg {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--secondary-color);
  font-weight: 700;
}

.block-code-msg.err {
  color: #c0392b;
}

.candidate-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.candidate-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 11px;
  background: var(--surface-2);
  border: 1px solid var(--rose-line);
  border-radius: 8px;
  font-size: 13px;
  color: var(--secondary-color);
  font-weight: 700;
  cursor: pointer;
}

.block-selected-btn {
  margin-top: 4px;
}

.field-label {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 700;
  color: var(--secondary-color);
  cursor: pointer;
}

.p115-actions {
  flex-wrap: wrap;
}

.list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.list-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 9px 7px 11px;
  background: var(--surface-2);
  border: 1px solid var(--rose-line);
  border-radius: 8px;
  font-size: 13px;
  color: var(--secondary-color);
  font-weight: 700;
}

.item-link {
  cursor: pointer;
  text-decoration: underline;
  text-decoration-color: transparent;
  transition: color 0.15s ease, text-decoration-color 0.15s ease;
}

.item-link:hover {
  color: var(--primary-color);
  text-decoration-color: var(--primary-color);
}

.del-btn {
  background: #fff5f4;
  border: 1px solid #ffd0cc;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: var(--danger-color);
  padding: 3px 6px;
  font-weight: 800;
}

.del-btn:hover {
  background: var(--danger-color);
  color: white;
  border-color: var(--danger-color);
}

.empty {
  color: var(--muted-color);
  font-size: 14px;
}

@media (max-width: 520px) {
  .scrape-section {
    align-items: stretch;
    flex-direction: column;
  }

  .add-row {
    flex-direction: column;
  }
}
</style>
