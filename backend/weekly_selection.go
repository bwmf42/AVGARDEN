package main

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"syscall"
	"time"
)

// Uses the existing watched file and flock shared with Worker maintenance.
// Legacy intent fields remain readable, but new choices are no longer offered.
func weeklySelectionHandler(w http.ResponseWriter, r *http.Request) {
	weeklyWatchedMtx.Lock()
	defer weeklyWatchedMtx.Unlock()
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	if r.Method == http.MethodGet {
		json.NewEncoder(w).Encode(loadWeeklyWatchedStoreRecords())
		return
	}
	if r.Method != http.MethodPost {
		httpError(w, "Method not allowed", 405)
		return
	}
	var request struct {
		ID     string `json:"id"`
		Action string `json:"action"`
	}
	if json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096)).Decode(&request) != nil {
		httpError(w, "Invalid payload", 400)
		return
	}
	request.ID = strings.ToUpper(strings.TrimSpace(request.ID))
	if !regexp.MustCompile(`^[A-Z0-9][A-Z0-9_-]{1,79}$`).MatchString(request.ID) {
		httpError(w, "Invalid ID", 400)
		return
	}
	if request.Action != "view" {
		httpError(w, "Invalid action", 400)
		return
	}
	// Same lock order as retention; an expired item cannot be bookmarked mid-delete.
	for _, path := range []string{filepath.Join(basePath, "__weekly__", "weekly.json"), weeklyWatchedFile} {
		if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			httpError(w, "Storage unavailable", 500)
			return
		}
		f, err := os.OpenFile(path+".lock", os.O_CREATE|os.O_RDWR, 0600)
		if err != nil {
			httpError(w, "Storage unavailable", 500)
			return
		}
		defer f.Close()
		if syscall.Flock(int(f.Fd()), syscall.LOCK_EX) != nil {
			httpError(w, "Storage lock failed", 500)
			return
		}
		defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	}
	ids := currentWeeklyIDSet()
	if !ids[request.ID] {
		httpError(w, "Item no longer in daily recommendations", 404)
		return
	}
	// Refuse to overwrite a corrupt state file.
	if data, err := os.ReadFile(weeklyWatchedFile); err == nil && !json.Valid(data) {
		httpError(w, "Invalid stored state", 500)
		return
	} else if err != nil && !os.IsNotExist(err) {
		httpError(w, "State unavailable", 500)
		return
	}
	records := loadWeeklyWatchedStoreRecords()
	item, exists := records[request.ID]
	if !exists {
		item = WeeklyWatchedRecord{ID: request.ID, WatchedAt: time.Now().Format(time.RFC3339), Reason: "viewed"}
	}
	// Reopening a detail never resets its retention clock or rewrites legacy fields.
	if !exists || records[request.ID] != item {
		records[request.ID] = item
		if err := writeWeeklySelection(records); err != nil {
			httpError(w, "Failed to save selection", 500)
			return
		}
	}
	json.NewEncoder(w).Encode(item)
}

func writeWeeklySelection(records map[string]WeeklyWatchedRecord) error {
	store := WeeklyWatchedStore{Items: make([]WeeklyWatchedRecord, 0, len(records))}
	for _, item := range records {
		store.Items = append(store.Items, item)
	}
	sort.Slice(store.Items, func(i, j int) bool { return store.Items[i].ID < store.Items[j].ID })
	data, err := json.MarshalIndent(store, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(weeklyWatchedFile), ".weekly-selection-*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	defer f.Close()
	if err := f.Chmod(0600); err != nil {
		return err
	}
	if _, err = f.Write(data); err != nil {
		return err
	}
	if err = f.Sync(); err != nil {
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	return os.Rename(f.Name(), weeklyWatchedFile)
}
