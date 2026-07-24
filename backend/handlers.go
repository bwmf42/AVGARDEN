package main

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"io/ioutil"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

func listVideosHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// 异步刷新缓存（30s 防抖）
	go func() {
		if cacheRebuilding.TryLock() {
			defer cacheRebuilding.Unlock()
			if time.Since(lastCacheRebuild) > 30*time.Second {
				lastCacheRebuild = time.Now()
				buildVideoListCache()
			}
		}
	}()

	cacheMutex.RLock()
	defer cacheMutex.RUnlock()

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	if err := json.NewEncoder(w).Encode(videoListCache); err != nil {
		logger.Printf("Error encoding video list: %v", err)
		httpError(w, "Internal server error", http.StatusInternalServerError)
	}
}

// videoDetailHandler 获取视频详情
func videoDetailHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	requestedID := strings.TrimPrefix(r.URL.Path, "/api/videos/")
	videoID, cleanID := resolveVideoDir(requestedID)
	if videoID == "" {
		httpError(w, "Invalid video ID", http.StatusBadRequest)
		return
	}

	detail := VideoDetail{ID: cleanID}
	startTime := time.Now()

	title, date, err := parseTitleAndDate(videoID)
	if err != nil {
		logger.Printf("NFO parse for %s failed: %v", videoID, err)
		detail.Title = cleanID
		detail.ReleaseDate = "Unknown"
	} else {
		detail.Title = title
		detail.ReleaseDate = date
	}

	fanartDir := filepath.Join(basePath, videoID)
	if files, err := ioutil.ReadDir(fanartDir); err == nil {
		type fanartFile struct {
			path   string
			num    int
			hasNum bool
		}

		var fanarts []fanartFile

		for _, file := range files {
			name := file.Name()
			if !file.IsDir() && strings.Contains(name, "-fanart") &&
				strings.HasSuffix(name, ".jpg") {

				parts := strings.Split(name, "-fanart")
				if len(parts) < 2 {
					continue
				}

				numPart := strings.TrimSuffix(parts[1], ".jpg")
				numPart = strings.TrimPrefix(numPart, "-")

				var num int
				var hasNum bool

				if n, err := strconv.Atoi(numPart); err == nil {
					num = n
					hasNum = true
				} else {
					num = 0
					hasNum = false
				}

				fanarts = append(fanarts, fanartFile{
					path:   fmt.Sprintf("/file/%s/%s", videoID, name),
					num:    num,
					hasNum: hasNum,
				})
			}
		}

		sort.Slice(fanarts, func(i, j int) bool {
			if fanarts[i].hasNum && fanarts[j].hasNum {
				return fanarts[i].num < fanarts[j].num
			}
			if fanarts[i].hasNum && !fanarts[j].hasNum {
				return true
			}
			if !fanarts[i].hasNum && fanarts[j].hasNum {
				return false
			}
			return fanarts[i].path < fanarts[j].path
		})

		for _, f := range fanarts {
			detail.Fanarts = append(detail.Fanarts, f.path)
		}
	} else {
		logger.Printf("Error reading fanart dir for %s: %v", videoID, err)
	}

	mp4Path := findFileInDir(basePath, videoID, ".mp4")
	if mp4Path != "" && !strings.HasPrefix(filepath.Base(mp4Path), "._") {
		detail.VideoFile = fmt.Sprintf("/file/%s/%s", videoID, filepath.Base(mp4Path))
	}

	logger.Printf("Processed detail request for %s in %v", videoID, time.Since(startTime))

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	if err := json.NewEncoder(w).Encode(detail); err != nil {
		logger.Printf("Error encoding detail for %s: %v", videoID, err)
		httpError(w, "Internal server error", http.StatusInternalServerError)
	}
}

// imageHandler 处理图片/视频文件请求
func imageHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	pathParts := strings.Split(strings.TrimPrefix(r.URL.Path, "/file/"), "/")
	if len(pathParts) < 2 {
		httpError(w, "Invalid image path", http.StatusBadRequest)
		return
	}

	videoID, _ := resolveVideoDir(pathParts[0])
	filename := strings.Join(pathParts[1:], "/")
	imagePath := filepath.Join(basePath, videoID, filename)

	// Require path to be inside basePath (prefix alone is wrong: /data vs /data-evil).
	if !isPathInsideBase(imagePath, basePath) {
		httpError(w, "Invalid path", http.StatusBadRequest)
		return
	}

	fileInfo, err := os.Stat(imagePath)
	if os.IsNotExist(err) {
		http.NotFound(w, r)
		return
	} else if err != nil {
		logger.Printf("Error accessing file %s: %v", imagePath, err)
		httpError(w, "Internal server error", http.StatusInternalServerError)
		return
	}

	switch filepath.Ext(filename) {
	case ".jpg", ".jpeg":
		w.Header().Set("Content-Type", "image/jpeg")
	case ".png":
		w.Header().Set("Content-Type", "image/png")
	case ".mp4":
		w.Header().Set("Content-Type", "video/mp4")
	}

	logger.Printf("Serving file %s (Size: %d)", imagePath, fileInfo.Size())
	http.ServeFile(w, r, imagePath)
}

type CoverLookupResult struct {
	ID     string `json:"id"`
	Title  string `json:"title,omitempty"`
	Cover  string `json:"cover"`
	Poster string `json:"poster,omitempty"`
	Source string `json:"source"`
}

// coverHandler returns the best known cover URL for a code without mutating weekly.json.
func coverHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	rawID, err := url.PathUnescape(strings.TrimPrefix(r.URL.Path, "/api/cover/"))
	if err != nil {
		httpError(w, "Invalid video ID", http.StatusBadRequest)
		return
	}

	candidates := coverIDCandidates(rawID)
	if len(candidates) == 0 {
		httpError(w, "Invalid video ID", http.StatusBadRequest)
		return
	}

	if result, ok := findCover(candidates); ok {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		if err := json.NewEncoder(w).Encode(result); err != nil {
			logger.Printf("Error encoding cover lookup for %s: %v", candidates[0], err)
			httpError(w, "Internal server error", http.StatusInternalServerError)
		}
		return
	}

	httpError(w, "Cover not found", http.StatusNotFound)
}

func coverIDCandidates(raw string) []string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}
	raw = strings.ToUpper(raw)

	candidates := make([]string, 0, 2)
	add := func(value string) {
		value = strings.TrimSpace(strings.ToUpper(value))
		if value == "" || strings.Contains(value, "/") || strings.Contains(value, "\\") || strings.Contains(value, "..") {
			return
		}
		for _, existing := range candidates {
			if existing == value {
				return
			}
		}
		candidates = append(candidates, value)
	}

	if normalized := normalizeUserVideoID(raw); normalized != "" {
		add(normalized)
		return candidates
	}
	if matches := avidPattern.FindStringSubmatch(raw); len(matches) >= 3 {
		add(matches[1] + "-" + matches[2])
	}
	return candidates
}

func findCover(candidates []string) (CoverLookupResult, bool) {
	if result, ok := findLocalMediaCover(candidates); ok {
		return result, true
	}
	if result, ok := findWeeklyJSONCover(candidates); ok {
		return result, true
	}
	if result, ok := findWeeklyFileCover(candidates); ok {
		return result, true
	}
	return CoverLookupResult{}, false
}

func findLocalMediaCover(candidates []string) (CoverLookupResult, bool) {
	for _, code := range candidates {
		videoID, cleanID := resolveVideoDir(code)
		if videoID == "" || videoID == "__weekly__" {
			continue
		}
		posterFile := getPosterFile(basePath, videoID)
		if posterFile == "" {
			continue
		}
		title, _, err := parseTitleAndDate(videoID)
		if err != nil || strings.TrimSpace(title) == "" {
			title = cleanID
		}
		poster := mediaFileURL(videoID, posterFile)
		return CoverLookupResult{
			ID:     cleanID,
			Title:  title,
			Cover:  poster,
			Poster: poster,
			Source: "media",
		}, true
	}
	return CoverLookupResult{}, false
}

func findWeeklyJSONCover(candidates []string) (CoverLookupResult, bool) {
	weeklyPath := filepath.Join(basePath, "__weekly__", "weekly.json")
	data, err := ioutil.ReadFile(weeklyPath)
	if err != nil {
		return CoverLookupResult{}, false
	}

	var items []map[string]interface{}
	if err := json.Unmarshal(data, &items); err != nil {
		return CoverLookupResult{}, false
	}

	candidateSet := make(map[string]bool, len(candidates)*2)
	for _, candidate := range candidates {
		candidateSet[candidate] = true
		candidateSet[comparableVideoID(candidate)] = true
	}

	for _, item := range items {
		itemID, _ := item["id"].(string)
		if itemID == "" {
			continue
		}
		itemID = strings.ToUpper(strings.TrimSpace(itemID))
		if !candidateSet[itemID] && !candidateSet[comparableVideoID(itemID)] {
			continue
		}

		cover, _ := item["cover"].(string)
		poster, _ := item["poster"].(string)
		if strings.TrimSpace(cover) == "" {
			cover = poster
		}
		if strings.TrimSpace(cover) == "" {
			continue
		}

		title, _ := item["title"].(string)
		return CoverLookupResult{
			ID:     itemID,
			Title:  title,
			Cover:  cover,
			Poster: poster,
			Source: "weekly-json",
		}, true
	}
	return CoverLookupResult{}, false
}

func findWeeklyFileCover(candidates []string) (CoverLookupResult, bool) {
	for _, code := range candidates {
		weeklyDir := filepath.Join(basePath, "__weekly__", code)
		if info, err := os.Stat(weeklyDir); err != nil || !info.IsDir() {
			continue
		}

		coverFile := firstExistingWeeklyImage(weeklyDir, code, "-cover.jpg")
		posterFile := firstExistingWeeklyImage(weeklyDir, code, "-poster.jpg")
		if coverFile == "" {
			coverFile = posterFile
		}
		if coverFile == "" {
			continue
		}

		return CoverLookupResult{
			ID:     code,
			Cover:  mediaFileURL(filepath.Join("__weekly__", code), coverFile),
			Poster: mediaFileURL(filepath.Join("__weekly__", code), posterFile),
			Source: "weekly-file",
		}, true
	}
	return CoverLookupResult{}, false
}

func firstExistingWeeklyImage(dir, code, suffix string) string {
	exact := code + suffix
	if _, err := os.Stat(filepath.Join(dir, exact)); err == nil {
		return exact
	}
	entries, err := ioutil.ReadDir(dir)
	if err != nil {
		return ""
	}
	for _, entry := range entries {
		if !entry.IsDir() && strings.HasSuffix(strings.ToLower(entry.Name()), suffix) {
			return entry.Name()
		}
	}
	return ""
}

func mediaFileURL(dirName, filename string) string {
	if filename == "" {
		return ""
	}
	parts := strings.Split(filepath.ToSlash(filepath.Join(dirName, filename)), "/")
	for i, part := range parts {
		parts[i] = url.PathEscape(part)
	}
	return "/file/" + strings.Join(parts, "/")
}

// addVideoHandler 添加视频到下载队列（不再直接调 Python）
// weeklyHandler 获取本周新片推荐（含下载状态）
func appendToQueue(id string) error {
	existing := make(map[string]bool)
	if data, err := ioutil.ReadFile(queuePath); err == nil {
		for _, line := range strings.Split(string(data), "\n") {
			line = strings.TrimSpace(line)
			if line != "" {
				existing[line] = true
			}
		}
	}
	if existing[id] {
		return nil
	}
	f, err := os.OpenFile(queuePath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.WriteString(id + "\n")
	return err
}

func checkStringExists(db *sql.DB, target string) (bool, error) {
	var exists bool
	query := "SELECT EXISTS(SELECT 1 FROM MissAV WHERE bvid = ? LIMIT 1)"
	err := db.QueryRow(query, target).Scan(&exists)
	if err != nil {
		return false, err
	}
	return exists, nil
}

// httpError 统一的HTTP错误响应
func httpError(w http.ResponseWriter, message string, code int) {
	logger.Printf("HTTP Error %d: %s", code, message)
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]string{"error": message})
}

// isPathInsideBase reports whether candidate resolves under baseDir.
// strings.HasPrefix alone is insufficient: "/data-evil" has prefix "/data".
func isPathInsideBase(candidate, baseDir string) bool {
	cleanPath := filepath.Clean(candidate)
	cleanBase := filepath.Clean(baseDir)
	if cleanPath == cleanBase {
		return true
	}
	sep := string(os.PathSeparator)
	return strings.HasPrefix(cleanPath, cleanBase+sep)
}

// addVideoHandler 添加视频到下载队列
func addVideoHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	// Empty API_KEY must never authorize (Bearer with empty token used to pass).
	if apiKey == "" {
		httpError(w, "Server misconfigured: API_KEY not set", http.StatusServiceUnavailable)
		return
	}
	authHeader := r.Header.Get("Authorization")
	if authHeader == "" || !strings.HasPrefix(authHeader, "Bearer ") || strings.TrimPrefix(authHeader, "Bearer ") != apiKey {
		httpError(w, "Unauthorized", http.StatusUnauthorized)
		return
	}
	videoID := strings.TrimPrefix(r.URL.Path, "/api/addvideo/")
	id := normalizeUserVideoID(videoID)
	if id == "" {
		httpError(w, "Invalid video ID", http.StatusBadRequest)
		return
	}
	db, err := sql.Open("sqlite3", dbPath)
	if err != nil {
		httpError(w, "Database error", http.StatusInternalServerError)
		return
	}
	defer db.Close()
	exists, err := checkStringExists(db, id)
	if err != nil {
		httpError(w, "Database error", http.StatusInternalServerError)
		return
	}
	if exists {
		w.Header().Set("Content-Type", "text/plain")
		w.Write([]byte(id + " already downloaded"))
		return
	}
	if err := appendToQueue(id); err != nil {
		httpError(w, "Failed to add to queue", http.StatusInternalServerError)
		return
	}
	logger.Printf("Added to queue: %s", id)
	w.Header().Set("Content-Type", "text/plain")
	w.Write([]byte("Added " + id + " to download queue"))
}

var (
	weeklyCache         []byte
	weeklyCacheMtx      sync.RWMutex
	weeklyCacheTime     time.Time
	weeklyCacheMod      time.Time // weekly.json 的修改时间
	weeklyCacheQueueSig string

	// mp4/poster 目录索引缓存，避免每条条目都扫磁盘
	mediaIndex     map[string]bool
	mediaIndexMtx  sync.RWMutex
	mediaIndexTime time.Time
	mediaIndexTTL  = 30 * time.Second
)

type WeeklyWatchedPayload struct {
	IDs []string `json:"ids"`
}

type WeeklyWatchedRecord struct {
	ID        string `json:"id"`
	WatchedAt string `json:"watched_at"`
}

type WeeklyWatchedStore struct {
	Items []WeeklyWatchedRecord `json:"items"`
}

var weeklyWatchedMtx sync.Mutex

type queueStatusItem struct {
	ID       string `json:"id"`
	Status   string `json:"status"`
	Progress int    `json:"progress"`
	Speed    int64  `json:"speed"`
}

type queueStatusResponse struct {
	Active []queueStatusItem `json:"active"`
	Failed []queueStatusItem `json:"failed"`
}

type queueAPIItem struct {
	Code        string  `json:"code"`
	Status      string  `json:"status"`
	Size        int64   `json:"size"`
	Speed       float64 `json:"speed"`
	ProgressPct int     `json:"progress_pct"`
}

type FailedAckStore struct {
	IDs []string `json:"ids"`
}

var failedAckMtx sync.Mutex

func normalizeWeeklyWatchedIDs(ids []string) []string {
	seen := make(map[string]bool)
	result := make([]string, 0, len(ids))
	for _, id := range ids {
		id = strings.ToUpper(strings.TrimSpace(id))
		if id == "" || seen[id] {
			continue
		}
		seen[id] = true
		result = append(result, id)
	}
	sort.Strings(result)
	return result
}

func parseWeeklyWatchedTime(raw string, fallback time.Time) time.Time {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return fallback
	}
	for _, layout := range []string{time.RFC3339, "2006-01-02 15:04:05", "2006-01-02"} {
		if t, err := time.ParseInLocation(layout, raw, time.Local); err == nil {
			return t
		}
	}
	return fallback
}

func loadWeeklyWatchedRecords() map[string]time.Time {
	data, err := ioutil.ReadFile(weeklyWatchedFile)
	if err != nil {
		return map[string]time.Time{}
	}

	now := time.Now()
	records := map[string]time.Time{}

	var ids []string
	if err := json.Unmarshal(data, &ids); err == nil {
		for _, id := range normalizeWeeklyWatchedIDs(ids) {
			records[id] = now
		}
		return records
	}

	var store WeeklyWatchedStore
	if err := json.Unmarshal(data, &store); err == nil {
		for _, item := range store.Items {
			id := strings.ToUpper(strings.TrimSpace(item.ID))
			if id == "" {
				continue
			}
			records[id] = parseWeeklyWatchedTime(item.WatchedAt, now)
		}
	}

	return records
}

func weeklyWatchedIDsFromRecords(records map[string]time.Time) []string {
	// 按 watched_at 降序排（最近看的排前面）
	type kv struct {
		id string
		ts time.Time
	}
	list := make([]kv, 0, len(records))
	for id, ts := range records {
		list = append(list, kv{id, ts})
	}
	sort.Slice(list, func(i, j int) bool {
		return list[i].ts.After(list[j].ts)
	})
	ids := make([]string, 0, len(list))
	for _, item := range list {
		ids = append(ids, item.id)
	}
	return ids
}

func loadWeeklyWatchedIDs() []string {
	return weeklyWatchedIDsFromRecords(loadWeeklyWatchedRecords())
}

func saveWeeklyWatchedIDs(ids []string) error {
	ids = normalizeWeeklyWatchedIDs(ids)
	existing := loadWeeklyWatchedRecords()
	now := time.Now()
	store := WeeklyWatchedStore{Items: make([]WeeklyWatchedRecord, 0, len(ids))}

	for _, id := range ids {
		watchedAt, ok := existing[id]
		if !ok {
			watchedAt = now
		}
		store.Items = append(store.Items, WeeklyWatchedRecord{
			ID:        id,
			WatchedAt: watchedAt.Format(time.RFC3339),
		})
	}

	if err := os.MkdirAll(filepath.Dir(weeklyWatchedFile), 0755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(store, "", "  ")
	if err != nil {
		return err
	}
	return ioutil.WriteFile(weeklyWatchedFile, data, 0644)
}

func weeklyWatchedHandler(w http.ResponseWriter, r *http.Request) {
	weeklyWatchedMtx.Lock()
	defer weeklyWatchedMtx.Unlock()

	if r.Method == http.MethodGet {
		ids := loadWeeklyWatchedIDs()
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(ids)
		return
	}

	if r.Method == http.MethodPut || r.Method == http.MethodPost {
		var payload WeeklyWatchedPayload
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			httpError(w, "Invalid payload", http.StatusBadRequest)
			return
		}
		ids := normalizeWeeklyWatchedIDs(payload.IDs)
		if err := saveWeeklyWatchedIDs(ids); err != nil {
			httpError(w, "Failed to save watched list", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(map[string]interface{}{"count": len(ids)})
		return
	}

	httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
}

func failedAckPath() string {
	return filepath.Join(filepath.Dir(queuePath), "failed_ack.json")
}

func loadFailedAckIDs() map[string]bool {
	data, err := ioutil.ReadFile(failedAckPath())
	if err != nil {
		return map[string]bool{}
	}
	var store FailedAckStore
	if err := json.Unmarshal(data, &store); err != nil {
		return map[string]bool{}
	}
	ids := normalizeWeeklyWatchedIDs(store.IDs)
	result := make(map[string]bool, len(ids))
	for _, id := range ids {
		result[id] = true
	}
	return result
}

func saveFailedAckIDs(ids map[string]bool) error {
	list := make([]string, 0, len(ids))
	for id, ok := range ids {
		if ok {
			list = append(list, id)
		}
	}
	list = normalizeWeeklyWatchedIDs(list)
	if err := os.MkdirAll(filepath.Dir(failedAckPath()), 0755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(FailedAckStore{IDs: list}, "", "  ")
	if err != nil {
		return err
	}
	return ioutil.WriteFile(failedAckPath(), data, 0644)
}

func failedAckHandler(w http.ResponseWriter, r *http.Request) {
	failedAckMtx.Lock()
	defer failedAckMtx.Unlock()

	ids := loadFailedAckIDs()
	code := strings.TrimPrefix(r.URL.Path, "/api/failed-ack/")
	code = strings.ToUpper(strings.TrimSpace(code))

	switch r.Method {
	case http.MethodGet:
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(FailedAckStore{IDs: normalizeWeeklyWatchedIDs(mapKeys(ids))})
	case http.MethodPost, http.MethodPut:
		if code == "" || code == "/api/failed-ack" {
			var payload FailedAckStore
			if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
				httpError(w, "Invalid payload", http.StatusBadRequest)
				return
			}
			for _, id := range normalizeWeeklyWatchedIDs(payload.IDs) {
				ids[id] = true
			}
		} else {
			ids[code] = true
		}
		if err := saveFailedAckIDs(ids); err != nil {
			httpError(w, "Failed to save failed ack", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(map[string]interface{}{"ids": normalizeWeeklyWatchedIDs(mapKeys(ids))})
	case http.MethodDelete:
		if code == "" || code == "/api/failed-ack" {
			ids = map[string]bool{}
		} else {
			delete(ids, code)
		}
		if err := saveFailedAckIDs(ids); err != nil {
			httpError(w, "Failed to save failed ack", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(map[string]interface{}{"ids": normalizeWeeklyWatchedIDs(mapKeys(ids))})
	default:
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
	}
}

func mapKeys(m map[string]bool) []string {
	keys := make([]string, 0, len(m))
	for k, ok := range m {
		if ok {
			keys = append(keys, k)
		}
	}
	return keys
}

// buildMediaIndex 扫描 basePath 下的目录，记录哪些番号有 .mp4
// 一次扫描代替每条条目单独 stat，大幅减少磁盘 IO
func buildMediaIndex() map[string]bool {
	index := make(map[string]bool)
	entries, err := ioutil.ReadDir(basePath)
	if err != nil {
		return index
	}
	for _, entry := range entries {
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), "__") || entry.Name() == "thumb" {
			continue
		}
		code := strings.ToUpper(entry.Name())
		subEntries, err := ioutil.ReadDir(filepath.Join(basePath, entry.Name()))
		if err != nil {
			continue
		}
		for _, f := range subEntries {
			name := f.Name()
			if strings.HasSuffix(name, ".mp4") && f.Size() > 10*1024*1024 {
				index[code] = true
				break
			}
		}
	}
	return index
}

// getMediaIndex 获取缓存的媒体索引，TTL 内复用
func getMediaIndex() map[string]bool {
	mediaIndexMtx.RLock()
	if mediaIndex != nil && time.Since(mediaIndexTime) < mediaIndexTTL {
		idx := mediaIndex
		mediaIndexMtx.RUnlock()
		return idx
	}
	mediaIndexMtx.RUnlock()

	mediaIndexMtx.Lock()
	defer mediaIndexMtx.Unlock()
	// double check
	if mediaIndex != nil && time.Since(mediaIndexTime) < mediaIndexTTL {
		return mediaIndex
	}
	mediaIndex = buildMediaIndex()
	mediaIndexTime = time.Now()
	return mediaIndex
}

func warmWeeklyCache() {
	start := time.Now()
	weeklyPath := filepath.Join(basePath, "__weekly__", "weekly.json")
	info, err := os.Stat(weeklyPath)
	if err != nil {
		logger.Printf("weekly cache warm skipped: %v", err)
		return
	}

	data, err := ioutil.ReadFile(weeklyPath)
	if err != nil {
		logger.Printf("weekly cache warm read failed: %v", err)
		return
	}

	loadBlockedLists()
	var items []map[string]interface{}
	if err := json.Unmarshal(data, &items); err != nil || items == nil {
		items = []map[string]interface{}{}
	}

	mp4Index := getMediaIndex()
	activeQueueIndex := getActiveQueueIndex()
	filtered := filterWeeklyItems(items, mp4Index, activeQueueIndex)
	cached, _ := json.Marshal(filtered)

	weeklyCacheMtx.Lock()
	weeklyCache = cached
	weeklyCacheTime = time.Now()
	weeklyCacheMod = info.ModTime()
	weeklyCacheQueueSig = activeQueueSignature(activeQueueIndex)
	weeklyCacheMtx.Unlock()
	logger.Printf("weekly cache warmed: %d items in %v", len(filtered), time.Since(start))
}

func filterWeeklyItems(items []map[string]interface{}, mp4Index map[string]bool, activeQueueIndex map[string]string) []map[string]interface{} {
	blockedListsMtx.RLock()
	defer blockedListsMtx.RUnlock()
	filtered := make([]map[string]interface{}, 0)
	for _, item := range items {
		// 过滤屏蔽演员
		actresses, ok := item["actresses"].([]interface{})
		if ok && len(blockedActresses) > 0 {
			blocked := false
			for _, a := range actresses {
				if name, ok := a.(string); ok && blockedActresses[name] {
					blocked = true
					break
				}
			}
			if blocked {
				continue
			}
		}

		// 检查是否有收藏女优（跳过标签屏蔽）
		hasFavActress := false
		if actresses, ok := item["actresses"].([]interface{}); ok && len(favActresses) > 0 {
			for _, a := range actresses {
				if name, ok := a.(string); ok && favActresses[name] {
					hasFavActress = true
					break
				}
			}
		}

		// 过滤屏蔽标签(genres)，收藏女优跳过
		if !hasFavActress {
			if genres, ok := item["genres"].([]interface{}); ok && len(blockedGenres) > 0 {
				skip := false
				for _, g := range genres {
					if s, ok := g.(string); ok && blockedGenres[s] {
						skip = true
						break
					}
				}
				if skip {
					continue
				}
			}
		}

		// 过滤超龄女优 (>45岁)
		if actresses, ok := item["actresses"].([]interface{}); ok {
			if hasOldActress(actresses) {
				continue
			}
		}

		// 过滤标题关键词
		if title, ok := item["title"].(string); ok && len(blockedKeywords) > 0 {
			skip := false
			for kw := range blockedKeywords {
				if strings.Contains(title, kw) {
					skip = true
					break
				}
			}
			if skip {
				continue
			}
		}

		// 同步 downloaded：用媒体索引缓存查 mp4，避免逐条扫磁盘
		if id, ok := item["id"].(string); ok {
			code := strings.ToUpper(id)
			if status, active := activeQueueIndex[comparableVideoID(code)]; active {
				item["downloaded"] = false
				item["queueStatus"] = status
			} else if mp4Index[code] {
				item["downloaded"] = true
				delete(item, "queueStatus")
			} else {
				item["downloaded"] = false
				delete(item, "queueStatus")
			}
		}

		filtered = append(filtered, item)
	}
	return filtered
}

func getActiveQueueIndex() map[string]string {
	index := map[string]string{}
	items, err := loadQueueAPIItems()
	if err != nil {
		return index
	}
	for _, item := range items {
		code := comparableVideoID(item.Code)
		status := strings.ToLower(strings.TrimSpace(item.Status))
		if code == "" || status == "" || status == "done" {
			continue
		}
		index[code] = status
	}
	return index
}

func activeQueueSignature(index map[string]string) string {
	if len(index) == 0 {
		return ""
	}
	parts := make([]string, 0, len(index))
	for code, status := range index {
		parts = append(parts, code+":"+status)
	}
	sort.Strings(parts)
	return strings.Join(parts, "|")
}

// weeklyHandler 读取 weekly.json 并返回 (过滤屏蔽演员 + 清理失效 downloaded)
func weeklyHandler(w http.ResponseWriter, r *http.Request) {
	loadBlockedLists()
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	weeklyPath := filepath.Join(basePath, "__weekly__", "weekly.json")
	activeQueueIndex := getActiveQueueIndex()
	activeQueueSig := activeQueueSignature(activeQueueIndex)

	// 检查缓存：文件未变且缓存不超过5分钟
	info, statErr := os.Stat(weeklyPath)
	if statErr == nil {
		weeklyCacheMtx.RLock()
		if info.ModTime().Equal(weeklyCacheMod) && activeQueueSig == weeklyCacheQueueSig && time.Since(weeklyCacheTime) < 5*time.Minute && len(weeklyCache) > 0 {
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			w.Write(weeklyCache)
			weeklyCacheMtx.RUnlock()
			return
		}
		weeklyCacheMtx.RUnlock()
	}

	data, err := ioutil.ReadFile(weeklyPath)
	if err != nil {
		httpError(w, "Weekly data not found", http.StatusNotFound)
		return
	}

	var items []map[string]interface{}
	if err := json.Unmarshal(data, &items); err != nil || items == nil {
		items = []map[string]interface{}{}
	}

	// 一次性构建 mp4 索引，避免逐条扫磁盘
	mp4Index := getMediaIndex()

	filtered := filterWeeklyItems(items, mp4Index, activeQueueIndex)

	cached, _ := json.Marshal(filtered)

	// 更新缓存
	if statErr == nil {
		weeklyCacheMtx.Lock()
		weeklyCache = cached
		weeklyCacheTime = time.Now()
		weeklyCacheMod = info.ModTime()
		weeklyCacheQueueSig = activeQueueSig
		weeklyCacheMtx.Unlock()
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Write(cached)
}

// queueHandler 代理到 Python queue_api (端口 31473)
func queueHandler(w http.ResponseWriter, r *http.Request) {
	targetURL := queueAPI + r.URL.Path
	if r.URL.RawQuery != "" {
		targetURL += "?" + r.URL.RawQuery
	}
	body, err := ioutil.ReadAll(r.Body)
	if err != nil {
		httpError(w, "Proxy read error", http.StatusBadRequest)
		return
	}
	if r.Method == http.MethodPost && strings.TrimRight(r.URL.Path, "/") == "/api/queue" {
		var payload struct {
			Code string `json:"code"`
		}
		if err := json.Unmarshal(body, &payload); err != nil {
			httpError(w, "Invalid JSON", http.StatusBadRequest)
			return
		}
		code := normalizeUserVideoID(payload.Code)
		if code == "" {
			httpError(w, "Invalid video ID", http.StatusBadRequest)
			return
		}
		body, _ = json.Marshal(map[string]string{"code": code})
		failedAckMtx.Lock()
		acked := loadFailedAckIDs()
		if acked[code] {
			delete(acked, code)
			saveFailedAckIDs(acked)
		}
		failedAckMtx.Unlock()
	}
	proxyReq, err := http.NewRequest(r.Method, targetURL, bytes.NewReader(body))
	if err != nil {
		httpError(w, "Proxy error", http.StatusInternalServerError)
		return
	}
	proxyReq.Header = r.Header.Clone()
	proxyReq.ContentLength = int64(len(body))
	resp, err := queueHTTPClient.Do(proxyReq)
	if err != nil {
		httpError(w, "Queue service unavailable", http.StatusServiceUnavailable)
		return
	}
	defer resp.Body.Close()
	for k, v := range resp.Header {
		for _, vv := range v {
			w.Header().Add(k, vv)
		}
	}
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body)
}

func onlineSearchHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodDelete {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	targetURL := strings.TrimRight(queueAPI, "/") + r.URL.Path
	if r.URL.RawQuery != "" {
		targetURL += "?" + r.URL.RawQuery
	}
	proxyReq, err := http.NewRequest(r.Method, targetURL, nil)
	if err != nil {
		httpError(w, "Proxy error", http.StatusInternalServerError)
		return
	}
	proxyReq.Header = r.Header.Clone()

	resp, err := onlineQueueHTTPClient.Do(proxyReq)
	if err != nil {
		httpError(w, "Queue service unavailable", http.StatusServiceUnavailable)
		return
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		httpError(w, "Proxy read error", http.StatusBadGateway)
		return
	}

	if strings.HasPrefix(r.URL.Path, "/api/online-search/") &&
		r.Method == http.MethodGet && resp.StatusCode >= 200 && resp.StatusCode < 300 {
		var item map[string]interface{}
		if err := json.Unmarshal(body, &item); err == nil {
			decorateOnlineSearchItem(item)
			if nextBody, err := json.Marshal(item); err == nil {
				body = nextBody
			}
		}
	}

	for k, v := range resp.Header {
		for _, vv := range v {
			w.Header().Add(k, vv)
		}
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(resp.StatusCode)
	w.Write(body)
}

func decorateOnlineSearchItem(item map[string]interface{}) {
	rawID, _ := item["id"].(string)
	if rawID == "" {
		return
	}
	if status, ok := activeQueueStatusForID(rawID); ok {
		item["downloaded"] = false
		item["queueStatus"] = status
		return
	}
	if localID, ok := findDownloadedLocalID(rawID); ok {
		item["downloaded"] = true
		item["localID"] = localID
		item["localUrl"] = "/video/" + url.PathEscape(localID)
		return
	}
	item["downloaded"] = false
}

func activeQueueStatusForID(rawID string) (string, bool) {
	candidates := coverIDCandidates(rawID)
	if len(candidates) == 0 {
		return "", false
	}
	items, err := loadQueueAPIItems()
	if err != nil {
		return "", false
	}
	for _, item := range items {
		status := strings.ToLower(strings.TrimSpace(item.Status))
		if status == "" || status == "done" {
			continue
		}
		for _, candidate := range candidates {
			if comparableVideoID(item.Code) == comparableVideoID(candidate) {
				return status, true
			}
		}
	}
	return "", false
}

func findDownloadedLocalID(rawID string) (string, bool) {
	for _, code := range coverIDCandidates(rawID) {
		videoDir, cleanID := resolveVideoDir(code)
		if videoDir == "" || strings.HasPrefix(videoDir, "__") {
			continue
		}
		if info, err := os.Stat(filepath.Join(basePath, videoDir)); err != nil || !info.IsDir() {
			continue
		}
		mp4Path := findFileInDir(basePath, videoDir, ".mp4")
		if info, err := os.Stat(mp4Path); err == nil && info.Size() > 10*1024*1024 {
			return cleanID, true
		}
	}
	return "", false
}

func invalidateWeeklyCache() {
	weeklyCacheMtx.Lock()
	weeklyCache = nil
	weeklyCacheTime = time.Time{}
	weeklyCacheMod = time.Time{}
	weeklyCacheQueueSig = ""
	weeklyCacheMtx.Unlock()
}

func blockListNameFromPath(path, prefix string) string {
	raw := strings.TrimPrefix(path, prefix)
	if raw == "" {
		return ""
	}
	name, err := url.PathUnescape(raw)
	if err != nil {
		return strings.TrimSpace(raw)
	}
	return strings.TrimSpace(name)
}

// blockActressHandler 添加演员到屏蔽列表
func blockActressHandler(w http.ResponseWriter, r *http.Request) {
	name := blockListNameFromPath(r.URL.Path, "/api/block-actress/")
	if r.Method == http.MethodGet {
		blockedListsMtx.RLock()
		keys := orderedActiveValuesNewestFirst(blockedActressesFile, blockedActresses)
		blockedListsMtx.RUnlock()
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(keys)
		return
	}
	if name == "" || r.Method != http.MethodPost {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if err := appendBlockedActress(name); err != nil {
		httpError(w, "Failed to block", http.StatusInternalServerError)
		return
	}
	blockedListsMtx.Lock()
	blockedActresses[name] = true
	blockedListsMtx.Unlock()
	invalidateWeeklyCache()
	logger.Printf("Blocked actress: %s", name)
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(map[string]string{"status": "blocked", "name": name})
}

// blockGenreHandler 添加标签到屏蔽列表
func blockGenreHandler(w http.ResponseWriter, r *http.Request) {
	name := blockListNameFromPath(r.URL.Path, "/api/block-genre/")
	if r.Method == http.MethodGet {
		blockedListsMtx.RLock()
		keys := make([]string, 0, len(blockedGenres))
		for k := range blockedGenres {
			if blockedGenres[k] {
				keys = append(keys, k)
			}
		}
		blockedListsMtx.RUnlock()
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(keys)
		return
	}
	if name == "" || r.Method != http.MethodPost {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	f, err := os.OpenFile(blockedGenresFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		httpError(w, "Failed to block", http.StatusInternalServerError)
		return
	}
	defer f.Close()
	f.WriteString(name + "\n")
	blockedListsMtx.Lock()
	blockedGenres[name] = true
	blockedListsMtx.Unlock()
	invalidateWeeklyCache()
	logger.Printf("Blocked genre: %s", name)
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(map[string]string{"status": "blocked", "name": name})
}

func getQBCookie() string {
	resp, err := qbHTTPClient.PostForm(qbAPI+"/api/v2/auth/login",
		url.Values{"username": {qbUser}, "password": {qbPass}})
	if err != nil {
		return ""
	}
	defer resp.Body.Close()
	for _, c := range resp.Cookies() {
		if c.Name == "SID" {
			return c.Value
		}
	}
	return ""
}

var (
	qbTorrentCache     []map[string]interface{}
	qbTorrentCacheMtx  sync.RWMutex
	qbTorrentCacheTime time.Time
)

var (
	qbHTTPClient          = &http.Client{Timeout: 30 * time.Second}
	queueHTTPClient       = &http.Client{Timeout: 15 * time.Second}
	onlineQueueHTTPClient = &http.Client{Timeout: 90 * time.Second}
)

type FailedQueueRecord struct {
	Code     string `json:"code"`
	FailedAt string `json:"failed_at"`
	Retries  int    `json:"retries,omitempty"`
}

func parseFailedTime(raw string, fallback time.Time) time.Time {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return fallback
	}
	for _, layout := range []string{time.RFC3339, "2006-01-02 15:04:05", "2006-01-02"} {
		if t, err := time.ParseInLocation(layout, raw, time.Local); err == nil {
			return t
		}
	}
	return fallback
}

func loadFailedRecords() map[string]time.Time {
	result := map[string]time.Time{}
	dir := filepath.Dir(queuePath)

	jsonPath := filepath.Join(dir, "failed_queue.json")
	if data, err := ioutil.ReadFile(jsonPath); err == nil {
		var records []FailedQueueRecord
		if json.Unmarshal(data, &records) == nil {
			for _, record := range records {
				code := strings.ToUpper(strings.TrimSpace(record.Code))
				if code == "" {
					continue
				}
				t := parseFailedTime(record.FailedAt, time.Time{})
				if prev, ok := result[code]; !ok || t.After(prev) {
					result[code] = t
				}
			}
		}
	}

	legacyPath := filepath.Join(dir, "failed_queue.txt")
	if data, err := ioutil.ReadFile(legacyPath); err == nil {
		failedAt := time.Time{}
		if info, err := os.Stat(legacyPath); err == nil {
			failedAt = info.ModTime()
		}
		for _, line := range strings.Split(string(data), "\n") {
			code := strings.ToUpper(strings.TrimSpace(line))
			if code == "" {
				continue
			}
			if _, exists := result[code]; !exists {
				result[code] = failedAt
			}
		}
	}

	return result
}

func recentFailedCodes(window time.Duration) map[string]bool {
	cutoff := time.Now().Add(-window)
	result := map[string]bool{}
	for code, failedAt := range loadFailedRecords() {
		if failedAt.IsZero() {
			continue
		}
		if failedAt.After(cutoff) {
			result[code] = true
		}
	}
	return result
}

func hasSeenQueueCode(seen map[string]bool, code string) bool {
	code = strings.ToUpper(strings.TrimSpace(code))
	if code == "" {
		return false
	}
	if seen[code] {
		return true
	}
	for active := range seen {
		if strings.HasSuffix(active, code) || strings.HasSuffix(code, active) {
			return true
		}
	}
	return false
}

func getQBTorrents() []map[string]interface{} {
	qbTorrentCacheMtx.RLock()
	if time.Since(qbTorrentCacheTime) < 10*time.Second && len(qbTorrentCache) > 0 {
		cached := qbTorrentCache
		qbTorrentCacheMtx.RUnlock()
		return cached
	}
	qbTorrentCacheMtx.RUnlock()

	sid := getQBCookie()
	if sid == "" {
		return nil
	}
	req, _ := http.NewRequest("GET", qbAPI+"/api/v2/torrents/info?category=AV_GARDEN", nil)
	req.AddCookie(&http.Cookie{Name: "SID", Value: sid})
	resp, err := qbHTTPClient.Do(req)
	if err != nil {
		// qB 不可用，返回过期缓存
		qbTorrentCacheMtx.RLock()
		cached := qbTorrentCache
		qbTorrentCacheMtx.RUnlock()
		return cached
	}
	defer resp.Body.Close()
	body, _ := ioutil.ReadAll(resp.Body)
	var torrents []map[string]interface{}
	json.Unmarshal(body, &torrents)

	qbTorrentCacheMtx.Lock()
	qbTorrentCache = torrents
	qbTorrentCacheTime = time.Now()
	qbTorrentCacheMtx.Unlock()
	return torrents
}

func videoStatusHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/api/video-status/")
	if id == "" {
		httpError(w, "Invalid id", http.StatusBadRequest)
		return
	}
	id = strings.ToUpper(id)
	status := "none"
	progress := 0

	// 1. qB 检查（用缓存）
	torrents := getQBTorrents()
	for _, t := range torrents {
		name := strings.ToUpper(strings.TrimSpace(fmt.Sprint(t["name"])))
		if strings.Contains(name, id) || id == name {
			state := fmt.Sprint(t["state"])
			if state == "downloading" || state == "stalledDL" || state == "forcedDL" || state == "metaDL" {
				status = "downloading"
			} else if state == "uploading" || state == "stalledUP" || state == "pausedUP" || state == "queuedUP" {
				status = "done"
			} else {
				status = "queued"
			}
			progress = int(t["progress"].(float64) * 100)
			break
		}
	}

	// 2. 磁盘检查
	if status == "none" {
		mp4Path := findFileInDir(basePath, id, ".mp4")
		if info, err := os.Stat(mp4Path); err == nil && info.Size() > 10*1024*1024 {
			status = "done"
		}
	}

	// 3. 队列文件检查
	if status == "none" {
		queueData, err := ioutil.ReadFile(queuePath)
		if err == nil {
			for _, line := range strings.Split(string(queueData), "\n") {
				if strings.EqualFold(strings.TrimSpace(line), id) {
					status = "queued"
					break
				}
			}
		}
	}

	// 4. 失败队列检查
	if status == "none" {
		if recentFailedCodes(7 * 24 * time.Hour)[id] {
			status = "failed"
		}
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status": status, "id": id, "progress": progress,
	})
}

func blockKeywordHandler(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimPrefix(r.URL.Path, "/api/block-keyword/")
	if r.Method == http.MethodGet {
		blockedListsMtx.RLock()
		keys := make([]string, 0, len(blockedKeywords))
		for k := range blockedKeywords {
			if blockedKeywords[k] {
				keys = append(keys, k)
			}
		}
		blockedListsMtx.RUnlock()
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(keys)
		return
	}
	if name == "" {
		httpError(w, "Invalid keyword", http.StatusBadRequest)
		return
	}
	if r.Method == http.MethodPost {
		blockedListsMtx.Lock()
		if blockedKeywords[name] {
			delete(blockedKeywords, name)
		} else {
			blockedKeywords[name] = true
			f, err := os.OpenFile(blockedKeywordsFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
			if err == nil {
				f.WriteString(name + "\n")
				f.Close()
			}
		}
		blocked := blockedKeywords[name]
		blockedListsMtx.Unlock()
		logger.Printf("Blocked keyword toggled: %s = %v", name, blocked)
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(map[string]interface{}{"keyword": name, "blocked": blocked})
		return
	}
	httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
}

func favActressHandler(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimPrefix(r.URL.Path, "/api/fav-actress/")
	if r.Method == http.MethodGet {
		blockedListsMtx.RLock()
		defer blockedListsMtx.RUnlock()
		if name == "" {
			keys := make([]string, 0, len(favActresses))
			for k := range favActresses {
				if favActresses[k] {
					keys = append(keys, k)
				}
			}
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			json.NewEncoder(w).Encode(keys)
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(map[string]bool{"favorited": favActresses[name]})
		return
	}
	if r.Method == http.MethodPost {
		blockedListsMtx.Lock()
		if favActresses[name] {
			favActresses[name] = false
			rewriteFavFile(favActresses)
		} else {
			favActresses[name] = true
			f, err := os.OpenFile(favActressesFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
			if err == nil {
				f.WriteString(name + "\n")
				f.Close()
			}
		}
		favorited := favActresses[name]
		blockedListsMtx.Unlock()
		logger.Printf("Favorite actress toggled: %s = %v", name, favorited)
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(map[string]interface{}{"name": name, "favorited": favorited})
		return
	}
	httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
}

func logsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	logDir := getEnv("LOG_DIR", "/logs")
	logFiles := discoverLogFiles(logDir)
	if len(logFiles) == 0 && logDir != "/logs" {
		logFiles = discoverLogFiles("/logs")
	}
	includeDebug := r.URL.Query().Get("debug") == "1"

	type logLine struct {
		text string
		ts   time.Time
		seq  int
	}

	lines := make([]logLine, 0)
	seq := 0
	for _, logFile := range logFiles {
		data, err := ioutil.ReadFile(logFile)
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(data), "\n") {
			line = strings.TrimRight(line, "\r")
			if strings.TrimSpace(line) == "" {
				continue
			}
			if !includeDebug && isDebugLogLine(line) {
				continue
			}
			lines = append(lines, logLine{
				text: line,
				ts:   parseLogLineTime(line),
				seq:  seq,
			})
			seq++
		}
	}

	sort.SliceStable(lines, func(i, j int) bool {
		if !lines[i].ts.Equal(lines[j].ts) {
			return lines[i].ts.After(lines[j].ts)
		}
		return lines[i].seq > lines[j].seq
	})

	if len(lines) > 500 {
		lines = lines[:500]
	}

	recent := make([]string, 0, len(lines))
	for _, line := range lines {
		recent = append(recent, line.text)
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(map[string]interface{}{"lines": recent})
}

func discoverLogFiles(logDir string) []string {
	entries, err := ioutil.ReadDir(logDir)
	if err != nil {
		return nil
	}

	type logFile struct {
		path    string
		modTime time.Time
	}

	files := make([]logFile, 0)
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".log") {
			continue
		}
		files = append(files, logFile{
			path:    filepath.Join(logDir, entry.Name()),
			modTime: entry.ModTime(),
		})
	}

	sort.Slice(files, func(i, j int) bool {
		if !files[i].modTime.Equal(files[j].modTime) {
			return files[i].modTime.Before(files[j].modTime)
		}
		return files[i].path < files[j].path
	})

	if len(files) > 14 {
		files = files[len(files)-14:]
	}

	paths := make([]string, 0, len(files))
	for _, file := range files {
		paths = append(paths, file.path)
	}
	return paths
}

func isDebugLogLine(line string) bool {
	return strings.Contains(line, " | DEBUG |") || strings.Contains(line, "[DEBUG]")
}

func parseLogLineTime(line string) time.Time {
	if len(line) < 19 {
		return time.Time{}
	}
	ts, err := time.ParseInLocation("2006-01-02 15:04:05", line[:19], time.Local)
	if err != nil {
		return time.Time{}
	}
	return ts
}

func versionHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	indexPath := filepath.Join(frontendDir, "index.html")
	data, err := ioutil.ReadFile(indexPath)
	if err != nil {
		httpError(w, "Frontend index not found", http.StatusNotFound)
		return
	}

	body := string(data)
	jsAsset := ""
	cssAsset := ""
	if m := regexp.MustCompile(`/assets/[^"]+\.js`).FindString(body); m != "" {
		jsAsset = m
	}
	if m := regexp.MustCompile(`/assets/[^"]+\.css`).FindString(body); m != "" {
		cssAsset = m
	}

	buildTime := ""
	if info, err := os.Stat(indexPath); err == nil {
		buildTime = info.ModTime().Format(time.RFC3339)
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"version":        appVersion(),
		"frontend_index": indexPath,
		"frontend_js":    jsAsset,
		"frontend_css":   cssAsset,
		"build_time":     buildTime,
		"server_time":    time.Now().Format(time.RFC3339),
	})
}

func appVersion() string {
	if version := strings.TrimSpace(os.Getenv("APP_VERSION")); version != "" {
		return version
	}
	for _, path := range []string{"/app/VERSION", "VERSION", "../VERSION"} {
		data, err := ioutil.ReadFile(path)
		if err == nil {
			if version := strings.TrimSpace(string(data)); version != "" {
				return version
			}
		}
	}
	return "dev"
}

func weeklyScrapeHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	resp, err := queueHTTPClient.Post(strings.TrimRight(queueAPI, "/")+"/api/weekly-scrape", "application/json", nil)
	if err != nil {
		logger.Printf("Manual weekly scrape request failed: %v", err)
		httpError(w, "Queue API unavailable", http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	body, readErr := io.ReadAll(resp.Body)
	if readErr != nil {
		httpError(w, "Failed to read Queue API response", http.StatusBadGateway)
		return
	}

	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		weeklyCacheMtx.Lock()
		weeklyCache = nil
		weeklyCacheTime = time.Time{}
		weeklyCacheMod = time.Time{}
		weeklyCacheMtx.Unlock()
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(resp.StatusCode)
	w.Write(body)
}

func loadQueueAPIItems() ([]queueAPIItem, error) {
	resp, err := queueHTTPClient.Get(queueAPI + "/api/queue")
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("queue API returned %d", resp.StatusCode)
	}
	var items []queueAPIItem
	if err := json.NewDecoder(resp.Body).Decode(&items); err != nil {
		return nil, err
	}
	return items, nil
}

func fallbackActiveQueueStatus() ([]queueStatusItem, map[string]bool) {
	result := []queueStatusItem{}
	seen := map[string]bool{}
	codeRe := regexp.MustCompile(`([A-Z0-9]+-\d+)`)

	for _, t := range getQBTorrents() {
		name := strings.TrimSpace(fmt.Sprint(t["name"]))
		state := fmt.Sprint(t["state"])
		progress := 0
		if p, ok := t["progress"].(float64); ok {
			progress = int(p * 100)
		}

		codeMatch := codeRe.FindString(strings.ToUpper(name))
		if codeMatch == "" {
			continue
		}
		seen[codeMatch] = true

		status := "downloading"
		if state == "uploading" || state == "stalledUP" || state == "pausedUP" || state == "queuedUP" {
			continue
		} else if state != "downloading" && state != "stalledDL" && state != "forcedDL" && state != "metaDL" {
			status = "queued"
		}

		speed := int64(0)
		if s, ok := t["dlspeed"].(float64); ok {
			speed = int64(s)
		}
		result = append(result, queueStatusItem{ID: codeMatch, Status: status, Progress: progress, Speed: speed})
	}

	if data, err := ioutil.ReadFile(queuePath); err == nil {
		for _, line := range strings.Split(string(data), "\n") {
			code := strings.ToUpper(strings.TrimSpace(line))
			if code == "" || seen[code] {
				continue
			}
			seen[code] = true
			result = append(result, queueStatusItem{ID: code, Status: "queued"})
		}
	}

	return result, seen
}

func queueStatusHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	result := queueStatusResponse{Active: []queueStatusItem{}, Failed: []queueStatusItem{}}
	seen := map[string]bool{}

	if queueItems, err := loadQueueAPIItems(); err == nil {
		for _, item := range queueItems {
			code := strings.ToUpper(strings.TrimSpace(item.Code))
			status := strings.ToLower(strings.TrimSpace(item.Status))
			if code == "" || status == "" || status == "done" || seen[code] {
				continue
			}
			seen[code] = true
			result.Active = append(result.Active, queueStatusItem{
				ID:       code,
				Status:   status,
				Progress: item.ProgressPct,
				Speed:    int64(item.Speed),
			})
		}
	} else {
		logger.Printf("queue-status: Queue API unavailable, using fallback: %v", err)
		result.Active, seen = fallbackActiveQueueStatus()
	}

	acked := loadFailedAckIDs()
	for code := range recentFailedCodes(7 * 24 * time.Hour) {
		if acked[code] {
			continue
		}
		mp4Path := findFileInDir(basePath, code, ".mp4")
		if info, err := os.Stat(mp4Path); err == nil && info.Size() > 10*1024*1024 {
			continue
		}
		if !hasSeenQueueCode(seen, code) {
			result.Failed = append(result.Failed, queueStatusItem{ID: code, Status: "failed"})
		}
	}
	sort.Slice(result.Failed, func(i, j int) bool {
		return result.Failed[i].ID < result.Failed[j].ID
	})

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(result)
}

func rewriteFavFile(m map[string]bool) {
	f, err := os.Create(favActressesFile)
	if err != nil {
		return
	}
	defer f.Close()
	for name, v := range m {
		if v {
			f.WriteString(name + "\n")
		}
	}
}
