import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import DetailView from '../views/DetailView.vue'
import WeeklyView from '../views/WeeklyView.vue'
import WeeklyDetailView from '../views/WeeklyDetailView.vue'
import DownloadView from '../views/DownloadView.vue'
import SettingsView from '../views/SettingsView.vue'
import LogsView from '../views/LogsView.vue'
import SearchView from '../views/SearchView.vue'

const routes = [
    {
        path: '/',
        name: 'home',
        component: HomeView
    },
    {
        path: '/weekly',
        name: 'weekly',
        component: WeeklyView
    },
    {
        path: '/weekly/downloaded',
        name: 'weekly-downloaded',
        component: WeeklyView
    },
    {
        path: '/weekly/:id',
        name: 'weekly-detail',
        component: WeeklyDetailView,
        props: true
    },
    {
        path: '/video/:id',
        name: 'detail',
        component: DetailView,
        props: true
    },
    {
        path: '/download',
        name: 'download',
        component: DownloadView
    },
    {
        path: '/search',
        name: 'search',
        component: SearchView
    },
    {
        path: '/settings',
        name: 'settings',
        component: SettingsView
    },
    {
        path: '/logs',
        name: 'logs',
        component: LogsView
    }
]

const router = createRouter({
    history: createWebHistory(),
    routes
})

export default router
