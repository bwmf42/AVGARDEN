package main

import (
	"encoding/json"
	"encoding/xml"
	"fmt"
	"html"
	"io"
	"io/ioutil"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

// =============================================
// 环境变量配置（替代硬编码）
// =============================================
var (
	basePath             = getEnv("SAVE_PATH", "/data")
	serverPort           = getEnv("SERVER_PORT", ":31471")
	apiKey               = getEnv("API_KEY", "")
	dbPath               = getEnv("DB_PATH", "/db/downloaded.db")
	queuePath            = getEnv("QUEUE_PATH", "/db/download_queue.txt")
	queueAPI             = getEnv("QUEUE_API_URL", "http://127.0.0.1:31473")
	qbAPI                = getEnv("QBITTORRENT_URL", "http://127.0.0.1:8880")
	qbUser               = getEnv("QBITTORRENT_USERNAME", "admin")
	qbPass               = getEnv("QBITTORRENT_PASSWORD", "adminadmin")
	blockedActressesFile = getEnv("BLOCKED_ACTRESSES_FILE", "/db/blocked_actresses.txt")
	blockedGenresFile    = getEnv("BLOCKED_GENRES_FILE", "/db/blocked_genres.txt")
	favActressesFile     = getEnv("FAV_ACTRESSES_FILE", "/db/favorite_actresses.txt")
	blockedKeywordsFile  = getEnv("BLOCKED_KEYWORDS_FILE", "/db/blocked_keywords.txt")
	actressAgesFile      = getEnv("ACTRESS_AGES_FILE", "/db/actress_ages.json")
	weeklyWatchedFile    = getEnv("WEEKLY_WATCHED_FILE", "/db/weekly_watched.json")
	blockedActresses     map[string]bool
	// foldActressKey(name) -> exact blocked spelling (covers 繁简/空白/尾标点)
	blockedActressFolds map[string]string
	blockedGenres       map[string]bool
	blockedKeywords     map[string]bool
	favActresses        map[string]bool
	// fold key -> exact fav spelling
	favActressFolds map[string]string
	actressAges     map[string]int
	actressAgeLimit = 45
	blockedListsMtx sync.RWMutex
)

// foldActressKey normalizes a name for blacklist/favorite matching.
// Keeps exact display spelling in the primary map; this is only for lookup.
func foldActressKey(name string) string {
	s := strings.TrimSpace(name)
	if s == "" {
		return ""
	}
	// strip common trailing junk from bad scrapes: 川上ゆう（
	s = strings.Trim(s, " \t　（）()【】[]「」『』・·.,。．!！?？:：;；-_—–")
	// drop spaces / middle dots
	replacer := strings.NewReplacer(
		" ", "", "　", "", "・", "", "·", "", "．", "", ".", "",
		"　", "",
	)
	s = replacer.Replace(s)
	// minimal 繁→简 / 旧字体 so 千葉/千叶、優/优、島/岛 能对上
	var b strings.Builder
	b.Grow(len(s))
	for _, r := range s {
		switch r {
		case '優':
			r = '优'
		case '愛':
			r = '爱'
		case '澤':
			r = '泽'
		case '辺':
			r = '边'
		case '黒':
			r = '黑'
		case '桜':
			r = '樱'
		case '実':
			r = '实'
		case '広':
			r = '广'
		case '滝':
			r = '泷'
		case '児':
			r = '儿'
		case '亜':
			r = '亚'
		case '斎':
			r = '斋'
		case '満':
			r = '满'
		case '浜':
			r = '滨'
		case '戸':
			r = '户'
		case '瀬':
			r = '濑'
		case '亀':
			r = '龟'
		case '竜':
			r = '龙'
		case '嶋', '島':
			r = '岛'
		case '斉':
			r = '齐'
		case '緒':
			r = '绪'
		case '絵':
			r = '绘'
		case '華':
			r = '华'
		case '葉':
			r = '叶'
		case '薫':
			r = '薰'
		case '蘭':
			r = '兰'
		case '鷹':
			r = '鹰'
		case '畝':
			r = '亩'
		case '雫':
			// same in both
		}
		if r >= 'A' && r <= 'Z' {
			r = r + ('a' - 'A')
		}
		b.WriteRune(r)
	}
	return b.String()
}

func rebuildActressFoldMaps() {
	blockedActressFolds = make(map[string]string, len(blockedActresses))
	for name, on := range blockedActresses {
		if !on {
			continue
		}
		key := foldActressKey(name)
		if key == "" {
			continue
		}
		// first spelling wins (file order is rebuilt via load)
		if _, ok := blockedActressFolds[key]; !ok {
			blockedActressFolds[key] = name
		}
	}
	favActressFolds = make(map[string]string, len(favActresses))
	for name, on := range favActresses {
		if !on {
			continue
		}
		key := foldActressKey(name)
		if key == "" {
			continue
		}
		if _, ok := favActressFolds[key]; !ok {
			favActressFolds[key] = name
		}
	}
}

func isBlockedActressName(name string) bool {
	name = strings.TrimSpace(name)
	if name == "" {
		return false
	}
	// check name + known rename aliases (e.g. 河北彩花 / 河北彩伽)
	candidates := []string{name}
	// actressAliasGroup is in handlers.go same package
	for _, alt := range actressAliasGroup(name) {
		candidates = append(candidates, alt)
	}
	for _, c := range candidates {
		if blockedActresses[c] {
			return true
		}
		key := foldActressKey(c)
		if key != "" {
			if _, ok := blockedActressFolds[key]; ok {
				return true
			}
		}
	}
	return false
}

func isFavActressName(name string) bool {
	name = strings.TrimSpace(name)
	if name == "" {
		return false
	}
	if favActresses[name] {
		return true
	}
	key := foldActressKey(name)
	if key == "" {
		return false
	}
	_, ok := favActressFolds[key]
	return ok
}

func loadBlockedLists() {
	blockedListsMtx.Lock()
	defer blockedListsMtx.Unlock()
	blockedActresses = make(map[string]bool)
	blockedGenres = make(map[string]bool)
	// 1. 从环境变量加载
	for _, name := range strings.Split(os.Getenv("BLOCKED_ACTRESSES"), ",") {
		name = strings.TrimSpace(name)
		if name != "" {
			blockedActresses[name] = true
		}
	}
	for _, g := range strings.Split(os.Getenv("BLOCKED_GENRES"), ",") {
		g = strings.TrimSpace(g)
		if g != "" {
			blockedGenres[g] = true
		}
	}
	// 2. 从文件加载
	loadBlockedFromFile(blockedActressesFile, blockedActresses)
	loadBlockedFromFile(blockedGenresFile, blockedGenres)
	favActresses = make(map[string]bool)
	blockedKeywords = make(map[string]bool)
	loadBlockedFromFile(favActressesFile, favActresses)
	loadBlockedFromFile(blockedKeywordsFile, blockedKeywords)
	actressAges = make(map[string]int)
	loadActressAges()
	rebuildActressFoldMaps()
}

func loadActressAges() {
	actressAges = make(map[string]int)
	data, err := ioutil.ReadFile(actressAgesFile)
	if err != nil {
		return
	}
	var ages map[string]int
	if json.Unmarshal(data, &ages) == nil {
		actressAges = ages
	}
}

func hasOldActress(actresses []interface{}) bool {
	if len(actressAges) == 0 {
		return false
	}
	for _, a := range actresses {
		if name, ok := a.(string); ok {
			if year, exists := actressAges[name]; exists {
				if (time.Now().Year() - year) > actressAgeLimit {
					return true
				}
			}
		}
	}
	return false
}

func loadBlockedFromFile(path string, m map[string]bool) {
	data, err := ioutil.ReadFile(path)
	if err != nil {
		return
	}
	for _, line := range strings.Split(string(data), "\n") {
		val := strings.TrimSpace(line)
		if val != "" {
			m[val] = true
		}
	}
}

func orderedActiveValuesNewestFirst(path string, active map[string]bool) []string {
	data, err := ioutil.ReadFile(path)
	result := make([]string, 0, len(active))
	seen := make(map[string]bool)
	if err == nil {
		lines := strings.Split(string(data), "\n")
		for i := len(lines) - 1; i >= 0; i-- {
			val := strings.TrimSpace(lines[i])
			if val == "" || seen[val] || !active[val] {
				continue
			}
			seen[val] = true
			result = append(result, val)
		}
	}

	extras := make([]string, 0)
	for val, ok := range active {
		if ok && !seen[val] {
			extras = append(extras, val)
		}
	}
	sort.Strings(extras)
	return append(result, extras...)
}

func appendBlockedActress(name string) error {
	f, err := os.OpenFile(blockedActressesFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.WriteString(name + "\n")
	return err
}

// 前端静态文件目录
const frontendDir = "/app/frontend/dist"

// 全局缓存
var (
	videoListCache   []VideoItem
	cacheMutex       sync.RWMutex
	cacheRebuilding  sync.Mutex
	lastCacheRebuild time.Time
	logger           = log.New(os.Stdout, "[AV/GARDEN] ", log.LstdFlags|log.Lshortfile)

	weeklyTitleMutex sync.Mutex
	weeklyTitleCache map[string]string
	weeklyTitleMod   time.Time
)

// VideoItem 表示视频列表项
type VideoItem struct {
	ID        string   `json:"id"`
	Title     string   `json:"title"`
	Poster    string   `json:"poster"`
	Actresses []string `json:"actresses,omitempty"`
}

// VideoDetail 视频详细信息
type VideoDetail struct {
	ID          string   `json:"id"`
	Title       string   `json:"title"`
	ReleaseDate string   `json:"releaseDate"`
	Fanarts     []string `json:"fanarts"`
	VideoFile   string   `json:"videoFile,omitempty"`
	Actresses   []string `json:"actresses,omitempty"`
}

// NfoFile NFO文件结构
type NfoFile struct {
	XMLName     xml.Name `xml:"movie"`
	Title       string   `xml:"title"`
	ReleaseDate string   `xml:"releasedate"`
	Premiered   string   `xml:"premiered"`
	Actors      []struct {
		Name string `xml:"name"`
	} `xml:"actor"`
}

type MetadataTitleFile struct {
	Title         string `json:"title"`
	TitleZh       string `json:"titleZh"`
	TitleZhSnake  string `json:"title_zh"`
	TitleJp       string `json:"titleJp"`
	TitleJpSnake  string `json:"title_jp"`
	OriginalTitle string `json:"originaltitle"`
}

func hasPoster(base, dirName string) bool {
	return getPosterFile(base, dirName) != ""
}

func getPosterFile(base, dirName string) string {
	dirPath := filepath.Join(base, dirName)
	// 先试精确匹配
	exact := dirName + "-poster.jpg"
	if _, err := os.Stat(filepath.Join(dirPath, exact)); err == nil {
		return exact
	}
	// 再找任意 *-poster.jpg
	entries, err := ioutil.ReadDir(dirPath)
	if err != nil {
		return ""
	}
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), "-poster.jpg") {
			return e.Name()
		}
	}
	return ""
}

func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

func containsBlockedActress(actresses []string) bool {
	for _, actress := range actresses {
		if isBlockedActressName(actress) {
			return true
		}
	}
	return false
}

var avidPattern = regexp.MustCompile(`(?i)([A-Z]{2,}\d*)-(\d+)`)

func cleanVideoID(name string) string {
	name = strings.TrimSpace(name)
	matches := avidPattern.FindStringSubmatch(name)
	if len(matches) >= 3 {
		return strings.ToUpper(matches[1] + "-" + matches[2])
	}
	return strings.ToUpper(name)
}

func resolveVideoDir(videoID string) (string, string) {
	videoID = strings.TrimSpace(videoID)
	if videoID == "" {
		return "", ""
	}
	exact := filepath.Join(basePath, videoID)
	if info, err := os.Stat(exact); err == nil && info.IsDir() {
		return videoID, cleanVideoID(videoID)
	}

	target := cleanVideoID(videoID)
	entries, err := os.ReadDir(basePath)
	if err != nil {
		return videoID, target
	}
	for _, entry := range entries {
		if entry.IsDir() && cleanVideoID(entry.Name()) == target {
			return entry.Name(), target
		}
	}
	return videoID, target
}

func enableCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func main() {
	logger.Println("Starting AV/GARDEN server...")
	logger.Printf("basePath=%s port=%s db=%s queue=%s", basePath, serverPort, dbPath, queuePath)

	// 加载屏蔽演员列表
	loadBlockedLists()

	// 初始化缓存
	if err := buildVideoListCache(); err != nil {
		logger.Printf("Warning: initial cache build failed: %v", err)
	}
	go warmWeeklyCache()

	// 启动定时缓存更新
	go startCacheUpdater(10 * time.Minute)

	// 设置路由
	mux := http.NewServeMux()
	mux.HandleFunc("/api/videos", listVideosHandler)
	mux.HandleFunc("/api/videos/", videoDetailHandler)
	mux.HandleFunc("/api/cover/", coverHandler)
	mux.HandleFunc("/api/online-search/", onlineSearchHandler)
	mux.HandleFunc("/api/weekly-fanarts/", onlineSearchHandler)
	mux.HandleFunc("/api/addvideo/", addVideoHandler)
	mux.HandleFunc("/file/", imageHandler)
	mux.HandleFunc("/api/weekly", weeklyHandler)
	mux.HandleFunc("/api/weekly/by-genre/", byGenreHandler)
	mux.HandleFunc("/api/weekly-watched", weeklyWatchedHandler)
	mux.HandleFunc("/api/queue/", queueHandler)
	mux.HandleFunc("/api/failed-ack/", failedAckHandler)
	mux.HandleFunc("/api/failed-ack", failedAckHandler)
	mux.HandleFunc("/api/block-actress/", blockActressHandler)
	mux.HandleFunc("/api/block-by-code/", blockByCodeHandler)
	mux.HandleFunc("/api/block-genre/", blockGenreHandler)
	mux.HandleFunc("/api/video-status/", videoStatusHandler)
	mux.HandleFunc("/api/fav-actress/", favActressHandler)
	mux.HandleFunc("/api/block-keyword/", blockKeywordHandler)
	mux.HandleFunc("/api/logs", logsHandler)
	mux.HandleFunc("/api/queue-status", queueStatusHandler)
	mux.HandleFunc("/api/version", versionHandler)
	mux.HandleFunc("/api/weekly/scrape", weeklyScrapeHandler)

	// 前端静态文件 — 如果存在则 serve SPA (with Vue Router fallback)
	if _, err := os.Stat(frontendDir); err == nil {
		fs := http.FileServer(http.Dir(frontendDir))
		mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
			// Try to serve the requested file
			if r.URL.Path == "/" {
				w.Header().Set("Cache-Control", "no-cache")
				fs.ServeHTTP(w, r)
				return
			}
			path := filepath.Join(frontendDir, r.URL.Path)
			if _, err := os.Stat(path); err == nil {
				fs.ServeHTTP(w, r)
				return
			}
			// SPA fallback: serve index.html for all non-file routes
			w.Header().Set("Cache-Control", "no-cache")
			http.ServeFile(w, r, filepath.Join(frontendDir, "index.html"))
		})
		logger.Printf("Frontend static files served from %s (SPA mode)", frontendDir)
	} else {
		logger.Printf("Frontend dir not found (%s), API only mode", frontendDir)
		mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "text/plain")
			w.Write([]byte("AV/GARDEN Server API is running.\nFrontend not available — build the Vue project first."))
		})
	}

	// CORS 中间件
	handler := enableCORS(mux)

	port := strings.TrimPrefix(serverPort, ":")

	// 双栈监听（IPv4 + IPv6）
	listener4, err4 := net.Listen("tcp4", "0.0.0.0:"+port)
	listener6, err6 := net.Listen("tcp6", "[::]:"+port)

	if err4 != nil && err6 != nil {
		logger.Fatalf("Failed to listen on any interface: %v / %v", err4, err6)
	}

	if err4 == nil {
		go func() {
			logger.Printf("Serving on IPv4 :%s", port)
			logger.Fatal(http.Serve(listener4, handler))
		}()
	}
	if err6 == nil {
		logger.Printf("Serving on IPv6 :%s", port)
		logger.Fatal(http.Serve(listener6, handler))
	}

	select {}
}

// startCacheUpdater 定时更新缓存
func startCacheUpdater(interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for range ticker.C {
		logger.Println("Starting scheduled cache update...")
		if err := buildVideoListCache(); err != nil {
			logger.Printf("Cache update failed: %v", err)
		} else {
			logger.Println("Cache updated successfully")
		}
	}
}

// buildVideoListCache 构建视频列表缓存
func buildVideoListCache() error {
	cacheMutex.Lock()
	defer cacheMutex.Unlock()

	startTime := time.Now()
	logger.Println("Building video list cache...")

	files, err := os.ReadDir(basePath)
	if err != nil {
		logger.Printf("Error reading directory %s: %v", basePath, err)
		return fmt.Errorf("read directory failed: %w", err)
	}

	type dirEntryWithInfo struct {
		entry os.DirEntry
		info  os.FileInfo
	}

	var dirs []dirEntryWithInfo
	for _, file := range files {
		if !file.IsDir() {
			continue
		}
		info, err := file.Info()
		if err != nil {
			logger.Printf("Error getting info for %s: %v", file.Name(), err)
			continue
		}
		dirs = append(dirs, dirEntryWithInfo{entry: file, info: info})
	}

	sort.Slice(dirs, func(i, j int) bool {
		return dirs[i].info.ModTime().After(dirs[j].info.ModTime())
	})

	videoListCache = nil

	var count int
	for _, dir := range dirs {
		dirName := dir.entry.Name()
		videoID := cleanVideoID(dirName)
		posterFile := getPosterFile(basePath, dirName)
		if posterFile == "" {
			logger.Printf("Poster not found for %s", dirName)
			continue
		}

		title, _, actors, err := parseTitleDateActors(dirName)
		if err != nil {
			logger.Printf("Failed to parse NFO for %s: %v", dirName, err)
			title = videoID
		}

		videoListCache = append(videoListCache, VideoItem{
			ID:        videoID,
			Title:     title,
			Poster:    fmt.Sprintf("/file/%s/%s", videoID, posterFile),
			Actresses: actors,
		})
		count++
	}

	logger.Printf("Cache built successfully. Items: %d, Duration: %v",
		count, time.Since(startTime))
	return nil
}

// parseTitleAndDate 解析NFO文件获取标题和日期
func findFileInDir(base, dirName, suffix string) string {
	// 先试精确匹配
	exact := filepath.Join(base, dirName, dirName+suffix)
	if _, err := os.Stat(exact); err == nil {
		return exact
	}
	// 再找任意以 suffix 结尾的文件
	entries, err := ioutil.ReadDir(filepath.Join(base, dirName))
	if err != nil {
		return ""
	}
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), suffix) {
			return filepath.Join(base, dirName, e.Name())
		}
	}
	return ""
}

func parseTitleAndDate(videoID string) (title, releaseDate string, err error) {
	title, releaseDate, _, err = parseTitleDateActors(videoID)
	return title, releaseDate, err
}

// parseTitleDateActors: library NFO title + JP actress names (preferred spelling).
func parseTitleDateActors(videoID string) (title, releaseDate string, actresses []string, err error) {
	nfoPath := findFileInDir(basePath, videoID, ".nfo")
	if nfoPath != "" {
		file, err := os.Open(nfoPath)
		if err != nil {
			return "", "", nil, fmt.Errorf("open file failed: %w", err)
		}
		defer file.Close()

		decoder := xml.NewDecoder(file)
		decoder.CharsetReader = func(charset string, input io.Reader) (io.Reader, error) {
			return input, nil
		}

		var nfo NfoFile
		if err := decoder.Decode(&nfo); err != nil {
			return "", "", nil, fmt.Errorf("xml decode failed: %w", err)
		}

		date := nfo.ReleaseDate
		if date == "" {
			date = nfo.Premiered
		}
		seen := map[string]bool{}
		for _, a := range nfo.Actors {
			n := preferredActressSpelling(strings.TrimSpace(a.Name))
			if n == "" || seen[n] {
				continue
			}
			seen[n] = true
			actresses = append(actresses, n)
		}
		title = nfo.Title
		if title == "" {
			if fallback := fallbackTitleForVideo(videoID); fallback != "" {
				title = fallback
			} else {
				title = cleanVideoID(videoID)
			}
		}
		return title, date, actresses, nil
	}

	if fallback := fallbackTitleForVideo(videoID); fallback != "" {
		return fallback, "", nil, nil
	}
	return "", "", nil, fmt.Errorf("no title metadata found")
}

func fallbackTitleForVideo(videoID string) string {
	if title := weeklyTitleForVideo(videoID); title != "" {
		return title
	}
	if title := jsonTitleForVideo(videoID); title != "" {
		return title
	}
	if title := htmlTitleForVideo(videoID); title != "" {
		return title
	}
	return ""
}

func weeklyTitleForVideo(videoID string) string {
	weeklyTitleMutex.Lock()
	defer weeklyTitleMutex.Unlock()

	weeklyPath := filepath.Join(basePath, "__weekly__", "weekly.json")
	info, err := os.Stat(weeklyPath)
	if err != nil {
		return ""
	}

	if weeklyTitleCache == nil || !info.ModTime().Equal(weeklyTitleMod) {
		data, err := ioutil.ReadFile(weeklyPath)
		if err != nil {
			return ""
		}
		var items []map[string]interface{}
		if err := json.Unmarshal(data, &items); err != nil {
			return ""
		}

		next := make(map[string]string, len(items))
		for _, item := range items {
			id, _ := item["id"].(string)
			id = cleanVideoID(id)
			if id == "" {
				continue
			}
			for _, key := range []string{"titleZh", "title", "titleJp"} {
				if title, ok := item[key].(string); ok {
					if clean := cleanTitleCandidate(title, id); clean != "" {
						next[id] = clean
						break
					}
				}
			}
		}

		weeklyTitleCache = next
		weeklyTitleMod = info.ModTime()
	}

	return weeklyTitleCache[cleanVideoID(videoID)]
}

func jsonTitleForVideo(videoID string) string {
	for _, filename := range []string{"download_info.json", "metadata.json"} {
		path := filepath.Join(basePath, videoID, filename)
		data, err := ioutil.ReadFile(path)
		if err != nil {
			continue
		}
		var item MetadataTitleFile
		if err := json.Unmarshal(data, &item); err != nil {
			continue
		}
		for _, title := range []string{item.TitleZh, item.TitleZhSnake, item.Title, item.TitleJp, item.TitleJpSnake, item.OriginalTitle} {
			if clean := cleanTitleCandidate(title, videoID); clean != "" {
				return clean
			}
		}
	}
	return ""
}

func htmlTitleForVideo(videoID string) string {
	htmlPath := findFileInDir(basePath, videoID, ".html")
	if htmlPath == "" {
		return ""
	}
	data, err := ioutil.ReadFile(htmlPath)
	if err != nil {
		return ""
	}
	if len(data) > 1024*1024 {
		data = data[:1024*1024]
	}
	content := string(data)
	patterns := []*regexp.Regexp{
		regexp.MustCompile(`(?is)<meta\s+(?:property|name)=["']og:title["'][^>]*content=["']([^"']+)["']`),
		regexp.MustCompile(`(?is)<meta\s+[^>]*content=["']([^"']+)["'][^>]*(?:property|name)=["']og:title["']`),
		regexp.MustCompile(`(?is)<title>(.*?)</title>`),
	}
	for _, pattern := range patterns {
		if match := pattern.FindStringSubmatch(content); len(match) > 1 {
			if clean := cleanTitleCandidate(match[1], videoID); clean != "" {
				return clean
			}
		}
	}
	return ""
}

func cleanTitleCandidate(title, videoID string) string {
	title = html.UnescapeString(title)
	title = regexp.MustCompile(`(?is)<[^>]+>`).ReplaceAllString(title, "")
	title = strings.TrimSpace(title)
	title = strings.Join(strings.Fields(title), " ")
	for _, suffix := range []string{" - JavBus", " - MissAV", " | MissAV", " - Jable.TV", " - Jable"} {
		title = strings.TrimSuffix(title, suffix)
	}
	if title == "" {
		return ""
	}
	lower := strings.ToLower(title)
	if strings.Contains(lower, "an error occurred") || strings.Contains(lower, `"success":false`) {
		return ""
	}
	if strings.EqualFold(title, cleanVideoID(videoID)) {
		return ""
	}
	return title
}

// listVideosHandler 获取视频列表（触发异步缓存刷新）
