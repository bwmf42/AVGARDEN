package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestValidTranslatedTitleRejectsTruncatedResults(t *testing.T) {
	source := "SAN-478Z とても長い日本語の作品タイトルで翻訳結果に十分な本文が必要です"
	for _, translated := range []string{"", "SAN-478Z", "让", "GOJI-106: 「请把我当", "I cannot assist with this request, as it involves sexual content with a minor."} {
		if validTranslatedTitle(translated, source, "SAN-478Z") {
			t.Fatalf("translated title %q should be rejected", translated)
		}
	}
}

func TestValidTranslatedTitleKeepsNormalShortTitles(t *testing.T) {
	for _, tc := range []struct {
		translated string
		source     string
		code       string
	}{
		{"标题", "Title", "KEEP-001"},
		{"人妻交换", "夫婦交換", "KEEP-002"},
		{"HUNTC-499：无意中让男人勃起的女人随心所欲手交", "HUNTC-499 無自覚に男を勃起させる女の気まぐれ手コキ", "HUNTC-499"},
	} {
		if !validTranslatedTitle(tc.translated, tc.source, tc.code) {
			t.Fatalf("translated title %q should be accepted", tc.translated)
		}
	}
}

func TestFilterWeeklyItemsClearsInvalidTranslatedTitle(t *testing.T) {
	configureBlockedListTestFiles(t)
	items := []map[string]interface{}{
		{"id": "SAN-478Z", "title": "SAN-478Z 長い日本語タイトル", "titleZh": "让"},
		{"id": "KEEP-001", "title": "Title", "titleZh": "标题"},
	}

	filtered := filterWeeklyItems(items, map[string]bool{}, map[string]string{})
	if got := filtered[0]["titleZh"]; got != "" {
		t.Fatalf("invalid titleZh = %#v, want empty string", got)
	}
	if got := filtered[1]["titleZh"]; got != "标题" {
		t.Fatalf("valid titleZh = %#v", got)
	}
}

func TestWeeklyTitleForVideoFallsBackToCompleteSourceTitle(t *testing.T) {
	root := withTestMediaRoot(t)
	weeklyDir := filepath.Join(root, "__weekly__")
	if err := os.MkdirAll(weeklyDir, 0755); err != nil {
		t.Fatal(err)
	}
	data := []byte(`[{"id":"SAN-478Z","title":"SAN-478Z 完整日文标题","titleZh":"让"}]`)
	if err := os.WriteFile(filepath.Join(weeklyDir, "weekly.json"), data, 0644); err != nil {
		t.Fatal(err)
	}

	weeklyTitleMutex.Lock()
	oldCache, oldMod := weeklyTitleCache, weeklyTitleMod
	weeklyTitleCache, weeklyTitleMod = nil, time.Time{}
	weeklyTitleMutex.Unlock()
	t.Cleanup(func() {
		weeklyTitleMutex.Lock()
		weeklyTitleCache, weeklyTitleMod = oldCache, oldMod
		weeklyTitleMutex.Unlock()
	})

	if got := weeklyTitleForVideo("SAN-478Z"); got != "SAN-478Z 完整日文标题" {
		t.Fatalf("weekly title = %q", got)
	}
}
