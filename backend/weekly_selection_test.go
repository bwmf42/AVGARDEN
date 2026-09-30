package main

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWeeklySelectionPreservesLegacyAndIntent(t *testing.T) {
	oldPath, oldBase := weeklyWatchedFile, basePath
	defer func() { weeklyWatchedFile, basePath = oldPath, oldBase }()
	basePath = t.TempDir()
	weeklyWatchedFile = filepath.Join(basePath, "weekly_watched.json")
	os.MkdirAll(filepath.Join(basePath, "__weekly__"), 0700)
	os.WriteFile(filepath.Join(basePath, "__weekly__", "weekly.json"), []byte(`[{"id":"ABF-001"},{"id":"ABF-002"}]`), 0600)
	os.WriteFile(weeklyWatchedFile, []byte(`{"items":[{"id":"ABF-001","watched_at":"2026-07-01T00:00:00Z","reason":"manual"}]}`), 0600)
	call := func(id, action string, want int) {
		t.Helper()
		w := httptest.NewRecorder()
		r := httptest.NewRequest("POST", "/api/weekly-selection", strings.NewReader(`{"id":"`+id+`","action":"`+action+`"}`))
		weeklySelectionHandler(w, r)
		if w.Code != want {
			t.Fatalf("%s: %d %s", action, w.Code, w.Body.String())
		}
	}
	call("ABF-001", "want", 200)
	call("ABF-001", "view", 200)
	call("ABF-002", "view", 200)
	records := loadWeeklyWatchedStoreRecords()
	if records["ABF-001"].Interest != "want" || records["ABF-001"].WatchedAt != "2026-07-01T00:00:00Z" {
		t.Fatal(records)
	}
	// Old clients submitting their entire browsed list cannot erase bookmarks.
	if err := saveWeeklyWatchedIDs([]string{"ABF-002"}); err != nil {
		t.Fatal(err)
	}
	if loadWeeklyWatchedStoreRecords()["ABF-001"].Interest != "want" {
		t.Fatal("bookmark erased")
	}
	call("ABF-001", "dismiss", 200)
	call("ABF-001", "view", 200)
	if loadWeeklyWatchedStoreRecords()["ABF-001"].Interest != "dismissed" {
		t.Fatal("view cleared dismissal")
	}
	call("ABF-001", "clear", 200)
	if loadWeeklyWatchedStoreRecords()["ABF-001"].Interest != "" {
		t.Fatal("restore failed")
	}
	call("ABF-999", "want", 404)
	call("../bad", "want", 400)
	call("ABF-001", "delete", 400)
	w := httptest.NewRecorder()
	weeklySelectionHandler(w, httptest.NewRequest("GET", "/api/weekly-selection", nil))
	var result map[string]WeeklyWatchedRecord
	if json.Unmarshal(w.Body.Bytes(), &result) != nil || len(result) != 2 {
		t.Fatal(w.Body.String())
	}
	os.WriteFile(weeklyWatchedFile, []byte(`{broken`), 0600)
	call("ABF-001", "want", 500)
}
