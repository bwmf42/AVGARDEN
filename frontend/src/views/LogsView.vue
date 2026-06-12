<template>
    <div class="container">
        <div class="header">
            <h1 class="page-title">系统日志</h1>
            <button class="btn-refresh" @click="fetchLogs" :disabled="loading">
                {{ loading ? '刷新中...' : '刷新' }}
            </button>
        </div>

        <div v-if="loading && lines.length === 0" class="loading">加载中...</div>

        <div v-else-if="lines.length === 0" class="empty">暂无日志</div>

        <div v-else class="log-list">
            <div v-for="(line, i) in lines" :key="i" class="log-line" :class="sourceClass(line)">
                <span class="log-time">{{ line.slice(0, 19) }}</span>
                <span class="log-source">{{ extractSource(line) }}</span>
                <span class="log-msg">{{ extractMsg(line) }}</span>
            </div>
        </div>
    </div>
</template>

<script>
export default {
    name: 'LogsView',
    data() {
        return {
            lines: [],
            loading: true
        }
    },
    async created() {
        await this.fetchLogs()
    },
    methods: {
        async fetchLogs() {
            this.loading = true
            try {
                const resp = await fetch('/api/logs')
                if (resp.ok) {
                    const data = await resp.json()
                    this.lines = data.lines || []
                }
            } catch (e) {
                console.error('Logs fetch error:', e)
            }
            this.loading = false
        },
        extractSource(line) {
            const bracket = line.match(/\[(\w+)\]/)
            if (bracket) return bracket[1]
            const level = line.match(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+\|\s+([A-Z]+)\s+\|/)
            return level ? level[1] : 'LOG'
        },
        extractMsg(line) {
            const parts = line.split(' | ')
            if (parts.length >= 3) {
                return parts.slice(2).join(' | ')
            }
            const idx = line.indexOf('] ')
            return idx > 0 ? line.slice(idx + 2) : line
        },
        sourceClass(line) {
            if (line.includes('[DailyUpdater]')) return 'source-updater'
            if (line.includes('[ReplaceCN]')) return 'source-replace'
            if (line.includes('[Worker]')) return 'source-worker'
            if (line.includes(' | ERROR |')) return 'source-error'
            if (line.includes(' | WARNING |')) return 'source-warning'
            if (line.includes(' | INFO |')) return 'source-info'
            return ''
        }
    }
}
</script>

<style scoped>
.container {
  max-width: 940px;
  margin: 0 auto;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.page-title {
  color: var(--text-color);
  font-size: 24px;
  font-weight: 800;
  margin: 0;
  position: relative;
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

.btn-refresh {
  padding: 8px 15px;
  border: 1px solid var(--rose-line);
  background: var(--surface);
  color: var(--secondary-color);
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 800;
  transition: all 0.18s ease;
}

.btn-refresh:hover:not(:disabled) {
  background: var(--primary-color);
  border-color: var(--primary-color);
  color: white;
}

.btn-refresh:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.loading,
.empty {
  text-align: center;
  color: var(--muted-color);
  padding: 40px;
  font-size: 15px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
}

.log-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  background: var(--surface);
  border: 1px solid var(--line);
  border-top: 3px solid var(--primary-color);
  border-radius: 8px;
  padding: 8px;
  font-family: 'SF Mono', Monaco, Menlo, monospace;
  font-size: 12px;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: var(--shadow-soft);
}

.log-line {
  display: grid;
  grid-template-columns: 150px 104px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  padding: 7px 8px;
  border-radius: 6px;
  line-height: 1.45;
  border-bottom: 1px solid #f3e8ee;
}

.log-line:last-child {
  border-bottom: 0;
}

.log-line:hover {
  background: var(--surface-2);
}

.log-time {
  color: var(--muted-color);
  white-space: nowrap;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.log-source {
  display: inline-flex;
  justify-content: center;
  color: var(--secondary-color);
  background: #fff4f8;
  border: 1px solid var(--rose-line);
  border-radius: 999px;
  font-weight: 800;
  white-space: nowrap;
  padding: 2px 8px;
  min-width: 80px;
}

.log-msg {
  color: var(--text-color);
  word-break: break-all;
}

.source-updater .log-source {
  color: var(--info-color);
  border-color: #cfe7ff;
  background: #f3f9ff;
}

.source-replace .log-source {
  color: var(--success-color);
  border-color: #bfe8ca;
  background: #f4fbf5;
}

.source-worker .log-source {
  color: var(--warning-color);
  border-color: #ffe0ad;
  background: #fff9ed;
}

.source-error .log-source {
  color: var(--danger-color);
  border-color: #f4b8c4;
  background: #fff3f5;
}

.source-warning .log-source {
  color: var(--warning-color);
  border-color: #ffe0ad;
  background: #fff9ed;
}

.source-info .log-source {
  color: var(--info-color);
  border-color: #cfe7ff;
  background: #f3f9ff;
}

@media (max-width: 720px) {
  .log-line {
    grid-template-columns: 1fr;
    gap: 4px;
  }

  .log-source {
    justify-self: start;
  }
}
</style>
