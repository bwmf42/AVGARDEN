package main

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"testing"
)

func configureBlockedListTestFiles(t *testing.T) {
	t.Helper()
	dir := t.TempDir()
	oldActresses := blockedActressesFile
	oldGenres := blockedGenresFile
	oldFavorites := favActressesFile
	oldKeywords := blockedKeywordsFile
	oldAges := actressAgesFile
	blockedActressesFile = filepath.Join(dir, "actresses.txt")
	blockedGenresFile = filepath.Join(dir, "genres.txt")
	favActressesFile = filepath.Join(dir, "favorites.txt")
	blockedKeywordsFile = filepath.Join(dir, "keywords.txt")
	actressAgesFile = filepath.Join(dir, "ages.json")
	for _, path := range []string{blockedActressesFile, blockedGenresFile, favActressesFile, blockedKeywordsFile} {
		if err := os.WriteFile(path, nil, 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(actressAgesFile, []byte(`{}`), 0600); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		blockedActressesFile = oldActresses
		blockedGenresFile = oldGenres
		favActressesFile = oldFavorites
		blockedKeywordsFile = oldKeywords
		actressAgesFile = oldAges
		loadBlockedLists()
	})
	loadBlockedLists()
}

func TestBlockedListsConcurrentReloadAndRead(t *testing.T) {
	configureBlockedListTestFiles(t)
	var wait sync.WaitGroup
	for i := 0; i < 50; i++ {
		wait.Add(2)
		go func() {
			defer wait.Done()
			loadBlockedLists()
		}()
		go func() {
			defer wait.Done()
			items := []map[string]interface{}{{"id": "OMG-032", "actresses": []interface{}{"Example"}}}
			filterWeeklyItems(items, map[string]bool{}, map[string]string{})
		}()
	}
	wait.Wait()
}

func TestBlockActressResponseEscapesJSON(t *testing.T) {
	configureBlockedListTestFiles(t)
	request := httptest.NewRequest("POST", `/api/block-actress/A%22B`, nil)
	response := httptest.NewRecorder()
	blockActressHandler(response, request)
	if response.Code != 200 {
		t.Fatalf("status = %d", response.Code)
	}
	var payload map[string]string
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("invalid JSON response: %v", err)
	}
	if payload["name"] != `A"B` {
		t.Fatalf("name = %q", payload["name"])
	}
}
