package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestSaveWeeklyWatchedPreservesAutomaticBlockedRecord(t *testing.T) {
	dir := t.TempDir()
	oldPath := weeklyWatchedFile
	oldBase := basePath
	weeklyWatchedFile = filepath.Join(dir, "weekly_watched.json")
	basePath = dir
	if err := os.MkdirAll(filepath.Join(dir, "__weekly__"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "__weekly__", "weekly.json"), []byte(`[{"id":"ABF-001"},{"id":"ABF-002"}]`), 0600); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		weeklyWatchedFile = oldPath
		basePath = oldBase
	})

	initial := WeeklyWatchedStore{Items: []WeeklyWatchedRecord{{
		ID: "ABF-001", WatchedAt: "2026-07-01T12:00:00+08:00", Reason: "blocked_genre",
	}}}
	data, _ := json.Marshal(initial)
	if err := os.WriteFile(weeklyWatchedFile, data, 0600); err != nil {
		t.Fatal(err)
	}
	if err := saveWeeklyWatchedIDs([]string{"ABF-002"}); err != nil {
		t.Fatal(err)
	}

	stored := loadWeeklyWatchedStoreRecords()
	if stored["ABF-001"].Reason != "blocked_genre" {
		t.Fatalf("blocked record was lost: %#v", stored)
	}
	if stored["ABF-002"].Reason != "manual" {
		t.Fatalf("manual record missing: %#v", stored)
	}
	info, err := os.Stat(weeklyWatchedFile)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("mode = %o, want 600", info.Mode().Perm())
	}
	if matches, _ := filepath.Glob(filepath.Join(dir, ".weekly-watched-*.tmp")); len(matches) != 0 {
		t.Fatalf("temporary files left behind: %v", matches)
	}
}

func TestSaveWeeklyWatchedDoesNotRestoreIDMissingFromWeekly(t *testing.T) {
	dir := t.TempDir()
	oldPath := weeklyWatchedFile
	oldBase := basePath
	weeklyWatchedFile = filepath.Join(dir, "weekly_watched.json")
	basePath = dir
	if err := os.MkdirAll(filepath.Join(dir, "__weekly__"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "__weekly__", "weekly.json"), []byte(`[{"id":"KEEP-001"}]`), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(weeklyWatchedFile, []byte(`{"items":[]}`), 0600); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		weeklyWatchedFile = oldPath
		basePath = oldBase
	})

	if err := saveWeeklyWatchedIDs([]string{"KEEP-001", "EXPIRED-001"}); err != nil {
		t.Fatal(err)
	}
	stored := loadWeeklyWatchedStoreRecords()
	if _, ok := stored["EXPIRED-001"]; ok {
		t.Fatalf("expired ID was restored: %#v", stored)
	}
	if _, ok := stored["KEEP-001"]; !ok {
		t.Fatalf("current Weekly ID missing: %#v", stored)
	}
}
