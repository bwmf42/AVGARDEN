<template>
  <div id="app">
    <header class="app-header">
      <div class="header-container">
        <div class="nav-left">
          <router-link to="/" class="logo">
            <h1>AV/GARDEN</h1>
          </router-link>
          <router-link to="/weekly" class="nav-link">每日推荐</router-link>
          <router-link to="/download" class="nav-link">下载管理</router-link>
          <router-link to="/settings" class="nav-link">设置</router-link>
          <router-link to="/logs" class="nav-link">日志</router-link>
        </div>
        
        <div class="search-box">
          <input 
            v-model="inputContent" 
            type="text" 
            placeholder="输入视频内容" 
            class="search-input"
            @keyup.enter="handleSearch"
          >
          <button 
            class="search-button ghost"
            @click="handleSearch"
          >
            搜索
          </button>
          <button 
            class="search-button"
            @click="handleAddVideo"
            :disabled="isAdding"
          >
            {{ isAdding ? '添加中...' : '添加' }}
          </button>
        </div>
      </div>
    </header>

    <!-- 全局状态栏 -->
    <div v-if="statusBar.visible" class="status-bar">
      <span v-for="item in statusBar.items" :key="item.id" class="status-item" :class="item.status">
        <span class="status-dot"></span>
        <button type="button" class="status-code" @click="openStatusDetail(item)">
          {{ statusDisplayID(item.id) }}
        </button>
        <template v-if="item.status === 'queued'">等待中</template>
        <template v-if="item.status === 'downloading'">
          {{ item.progress }}%
          <span v-if="item.speed > 0"> {{ formatSpeed(item.speed) }}</span>
        </template>
        <template v-if="item.status === 'failed'">下载失败</template>
        <a
          v-if="item.status === 'failed'"
          class="status-javbus"
          :href="javbusURL(item.id)"
          target="_blank"
          rel="noreferrer"
          @click.stop
        >
          JavBus
        </a>
        <button
          v-if="item.status === 'failed'"
          type="button"
          class="status-dismiss"
          :aria-label="`忽略 ${item.id} 下载失败提示`"
          title="忽略此失败提示"
          @click.stop="dismissFailedStatus(item)"
        >
          关闭
        </button>
      </span>
    </div>

    <main class="app-main">
      <router-view v-slot="{ Component }">
        <keep-alive :include="['HomeView', 'WeeklyView']">
          <component :is="Component" :key="$route.fullPath" />
        </keep-alive>
      </router-view>
    </main>

    <footer class="app-footer">
      <p>© 2026 AV/GARDEN</p>
    </footer>

    <!-- 全局 Toast -->
    <div v-if="toast.visible" class="global-toast" :class="toast.type">
        {{ toast.msg }}
    </div>
  </div>
</template>

<script>
function normalizeStatusID(id) {
  return String(id || '').trim().toUpperCase()
}

function normalizeVideoCode(id) {
  const normalized = normalizeStatusID(id)
  const sourcePrefixed = normalized.match(/^420([A-Z]+-\d+)$/)
  return sourcePrefixed ? sourcePrefixed[1] : normalized
}

function normalizeInputID(value) {
  return normalizeStatusID(value)
}

export default {
  name: 'App',
  data() {
    return {
      inputContent: '',
      isAdding: false,
      toast: { visible: false, msg: '', type: 'info' },
      statusBar: { visible: false, items: [] },
      statusTimer: null
    }
  },
  mounted() {
    window.addEventListener('av-garden-toast', this.onToast)
    window.addEventListener('av-garden-refresh-status', this.fetchStatus)
    this.fetchStatus()
    this.statusTimer = setInterval(() => this.fetchStatus(), 60000)
  },
  beforeUnmount() {
    window.removeEventListener('av-garden-toast', this.onToast)
    window.removeEventListener('av-garden-refresh-status', this.fetchStatus)
    if (this.statusTimer) clearInterval(this.statusTimer)
  },
  methods: {
    onToast(e) {
      this.toast = { visible: true, msg: e.detail.msg, type: e.detail.type || 'info' }
      setTimeout(() => { this.toast.visible = false }, 4000)
    },
    async handleAddVideo() {
      const code = normalizeInputID(this.inputContent)
      if (!code) {
        this.showToast('请输入番号', 'warn')
        return
      }
      if (!/^([A-Z0-9]+)-\d+$/.test(code)) {
        this.showToast('格式错误，请输入 ABC-123 这样的番号', 'warn')
        return
      }
      this.isAdding = true
      try {
        const resp = await fetch('/api/queue/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code })
        })
        if (!resp.ok) {
          this.showToast(`${code} 添加失败，请重试`, 'warn')
          return
        }
        this.inputContent = ''
        this.showToast(`${code} 已加入下载队列`, 'info')
        this.fetchStatus()
      } catch (e) {
        this.showToast(`${code} 添加失败，请重试`, 'warn')
      } finally {
        this.isAdding = false
      }
    },
    handleSearch() {
      const q = this.inputContent.trim()
      if (!q) {
        this.showToast('请输入搜索内容', 'warn')
        return
      }
      this.$router.push({ name: 'search', query: { q } })
    },
    showToast(msg, type = 'info') {
      window.dispatchEvent(new CustomEvent('av-garden-toast', { detail: { msg, type } }))
    },
    async fetchStatus() {
      try {
        const resp = await fetch('/api/queue-status')
        if (!resp.ok) return
        const data = await resp.json()
        const items = [...data.active, ...data.failed].filter(item => item.status !== 'done')
        window.avGardenQueueStatus = items
        window.dispatchEvent(new CustomEvent('av-garden-status', { detail: { items } }))
        this.applyVisibleStatusItems(items)
      } catch(e) {}
    },
    applyVisibleStatusItems(items) {
      this.statusBar.items = items
      this.statusBar.visible = items.length > 0
    },
    async dismissFailedStatus(item) {
      const id = normalizeStatusID(item.id)
      if (!id || item.status !== 'failed') return
      this.applyVisibleStatusItems((window.avGardenQueueStatus || []).filter(status => normalizeStatusID(status.id) !== id))
      try {
        await fetch(`/api/failed-ack/${encodeURIComponent(id)}`, { method: 'POST' })
        await this.fetchStatus()
      } catch (e) {}
    },
    openStatusDetail(item) {
      const id = normalizeVideoCode(item.id)
      if (!id) return
      this.$router.push({ name: 'weekly-detail', params: { id }, query: { tab: 'unwatched' } })
    },
    javbusURL(id) {
      return `https://www.javbus.com/${encodeURIComponent(normalizeVideoCode(id))}`
    },
    statusDisplayID(id) {
      return normalizeVideoCode(id)
    },
    formatSpeed(bps) {
      if (!bps || bps === 0) return ''
      if (bps < 1024*1024) return (bps/1024).toFixed(0) + 'KB/s'
      return (bps/1024/1024).toFixed(1) + 'MB/s'
    }
  }
}
</script>

<style>
/* 全局基础样式 */
:root {
  --app-bg: #fff7fa;
  --surface: #ffffff;
  --surface-2: #fffbfd;
  --line: #eadde3;
  --rose-line: #f3c6d4;
  --primary-color: #e84d7a;
  --secondary-color: #ba2f5d;
  --accent-color: #f9dbe5;
  --text-color: #35242c;
  --muted-color: #80636f;
  --success-color: #287a43;
  --warning-color: #a15c00;
  --danger-color: #b42318;
  --info-color: #2563eb;
  --shadow-soft: 0 8px 24px rgba(186, 47, 93, 0.08);
  --shadow-hover: 0 14px 32px rgba(186, 47, 93, 0.12);
}

body {
  margin: 0;
  padding: 0;
  font-family: Inter, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
  color: var(--text-color);
  background:
    linear-gradient(rgba(232, 77, 122, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(232, 77, 122, 0.045) 1px, transparent 1px),
    var(--app-bg);
  background-size: 32px 32px;
  letter-spacing: 0;
}

#app {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

/* 导航栏样式 */
.app-header {
  background: rgba(255, 255, 255, 0.92);
  color: var(--text-color);
  padding: 0;
  border-bottom: 1px solid var(--rose-line);
  position: sticky;
  top: 0;
  z-index: 50;
  backdrop-filter: blur(14px);
}

.header-container {
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0.9rem 2rem;
  width: 100%;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-shrink: 0;
}

.logo {
  color: var(--secondary-color);
  text-decoration: none;
  flex-shrink: 0;
}

.logo h1 {
  font-size: 1.1rem;
  font-weight: 800;
  margin: 0;
  white-space: nowrap;
  letter-spacing: 0.12em;
}

.nav-link {
  color: var(--muted-color);
  text-decoration: none;
  font-size: 14px;
  padding: 7px 12px;
  border-radius: 999px;
  transition: all 0.18s ease;
  white-space: nowrap;
  border: 1px solid transparent;
}

.nav-link:hover,
.nav-link.router-link-active {
  background: var(--surface-2);
  color: var(--secondary-color);
  border-color: var(--rose-line);
}

/* 搜索框样式 */
.search-box {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.search-input {
  padding: 8px 12px;
  border: 1px solid var(--rose-line);
  border-radius: 8px;
  outline: none;
  font-size: 14px;
  width: 180px;
  height: 36px;
  transition: all 0.18s ease;
  background-color: var(--surface);
  color: var(--text-color);
}

.search-input::placeholder {
  color: #bfa5af;
}

.search-input:focus {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(232, 77, 122, 0.12);
}

.search-button {
  background-color: var(--primary-color);
  color: white;
  border: 1px solid var(--primary-color);
  padding: 8px 16px;
  border-radius: 8px;
  height: 36px;
  cursor: pointer;
  font-weight: 700;
  transition: all 0.18s ease;
  white-space: nowrap;
}

.search-button:hover {
  background-color: var(--secondary-color);
  border-color: var(--secondary-color);
}

.search-button.ghost {
  background: var(--surface);
  color: var(--secondary-color);
  border-color: var(--rose-line);
}

.search-button.ghost:hover {
  background: var(--surface-2);
  color: var(--primary-color);
  border-color: var(--primary-color);
}

/* 主内容区 */
.app-main {
  flex: 1;
  padding: 1.6rem 2rem 2rem;
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
}

/* 底部样式 */
.app-footer {
  text-align: center;
  padding: 1rem;
  border-top: 1px solid var(--rose-line);
  color: var(--muted-color);
  font-size: 0.82rem;
  background: rgba(255, 255, 255, 0.82);
}

/* 响应式调整 */
@media (max-width: 768px) {
  .header-container {
    padding: 0.8rem 1rem;
    flex-wrap: wrap;
    gap: 0.7rem;
    align-items: flex-start;
  }

  .nav-left {
    width: 100%;
    min-width: 0;
    gap: 8px;
    flex-shrink: 1;
    overflow-x: auto;
    padding-bottom: 2px;
    -webkit-overflow-scrolling: touch;
  }
  
  .logo h1 {
    font-size: 1rem;
  }
  
  .nav-link {
    font-size: 12px;
    padding: 4px 10px;
  }
  
  .search-box {
    width: 100%;
    min-width: 0;
    gap: 8px;
  }
  
  .search-input {
    flex: 1;
    min-width: 0;
    width: auto;
    font-size: 13px;
  }
  
  .search-button {
    padding: 8px 12px;
    font-size: 13px;
  }
  
  .app-main {
    padding: 1rem;
  }
}

@media (max-width: 480px) {
  .header-container {
    padding: 0.8rem;
  }
  
  .nav-link {
    font-size: 11px;
    padding: 4px 8px;
  }
  
  .search-button {
    padding: 6px 10px;
  }
}

* {
  box-sizing: border-box;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.global-toast {
  position: fixed;
  top: 20px;
  right: 20px;
  padding: 12px 18px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  z-index: 9999;
  animation: toastIn 0.24s ease;
  border: 1px solid var(--rose-line);
  background: var(--surface);
  color: var(--text-color);
  box-shadow: var(--shadow-hover);
}
.global-toast.info { border-color: #bfd7ff; color: var(--info-color); }
.global-toast.warn { border-color: #ffe0ad; color: var(--warning-color); }
@keyframes toastIn { from { transform: translateX(100px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

/* 状态栏 */
.status-bar {
  background: rgba(255, 251, 253, 0.96);
  color: var(--text-color);
  padding: 7px 20px;
  display: flex; gap: 12px; flex-wrap: wrap; align-items: center;
  font-size: 12px; font-family: 'SF Mono', Monaco, monospace;
  border-bottom: 1px solid var(--rose-line);
  box-shadow: 0 2px 10px rgba(186, 47, 93, 0.05);
}
.status-item {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 999px;
  background: white;
  border: 1px solid var(--rose-line);
  box-shadow: 0 2px 8px rgba(186, 47, 93, 0.06);
}
.status-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.status-code {
  appearance: none;
  border: 0;
  background: transparent;
  color: inherit;
  padding: 0;
  font: inherit;
  font-weight: 800;
  cursor: pointer;
}
.status-code:hover {
  text-decoration: underline;
}
.status-javbus {
  color: inherit;
  text-decoration: none;
  border: 1px solid currentColor;
  border-radius: 999px;
  padding: 1px 7px;
  font-size: 11px;
  font-weight: 800;
  background: rgba(255,255,255,0.76);
}
.status-javbus:hover {
  background: white;
}
.status-item.downloading .status-dot { background: var(--info-color); animation: pulse 1s infinite; }
.status-item.failed .status-dot { background: var(--danger-color); }
.status-item.queued .status-dot { background: var(--warning-color); }
.status-item.failed {
  color: var(--danger-color);
  border-color: #ffd0cc;
  background: #fff5f4;
}
.status-item.downloading {
  color: var(--info-color);
  border-color: #cfe7ff;
  background: #f3f9ff;
}
.status-item.queued {
  color: var(--warning-color);
  border-color: #ffe0ad;
  background: #fff9ed;
}
.status-dismiss {
  height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  border: 1px solid currentColor;
  background: rgba(255,255,255,0.76);
  color: inherit;
  font: inherit;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
}
.status-dismiss:hover {
  background: white;
}
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
</style>
