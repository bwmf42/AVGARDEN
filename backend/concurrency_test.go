package main

import (
	"encoding/json"
	"net/http"
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

func TestPreferencesPersistRemovalAndRefreshFoldIndex(t *testing.T) {
	configureBlockedListTestFiles(t)
	request := func(method, path string, handler http.HandlerFunc) {
		t.Helper()
		response := httptest.NewRecorder()
		handler(response, httptest.NewRequest(method, path, nil))
		if response.Code != http.StatusOK {
			t.Fatalf("%s %s: %d %s", method, path, response.Code, response.Body.String())
		}
	}
	for _, entry := range []struct {
		path, file string
		handler    http.HandlerFunc
	}{
		{"/api/block-actress/Example", blockedActressesFile, blockActressHandler},
		{"/api/block-genre/Example", blockedGenresFile, blockGenreHandler},
	} {
		request(http.MethodPost, entry.path, entry.handler)
		request(http.MethodDelete, entry.path, entry.handler)
		content, err := os.ReadFile(entry.file)
		if err != nil {
			t.Fatal(err)
		}
		if len(content) != 0 {
			t.Fatalf("unblocked entry remained in %s: %q", entry.file, content)
		}
	}
	request(http.MethodPost, "/api/block-keyword/Example", blockKeywordHandler)
	request(http.MethodDelete, "/api/block-keyword/Example", blockKeywordHandler)
	content, err := os.ReadFile(blockedKeywordsFile)
	if err != nil {
		t.Fatal(err)
	}
	if len(content) != 0 {
		t.Fatalf("keyword remained after removal: %q", content)
	}
	request(http.MethodPost, "/api/fav-actress/Example", favActressHandler)
	if !isFavActressName("Example") {
		t.Fatal("favorite fold index did not update on add")
	}
	request(http.MethodDelete, "/api/fav-actress/Example", favActressHandler)
	if isFavActressName("Example") {
		t.Fatal("favorite fold index remained after removal")
	}
	loadBlockedLists()
	blockedListsMtx.RLock()
	defer blockedListsMtx.RUnlock()
	if blockedActresses["Example"] || blockedGenres["Example"] || blockedKeywords["Example"] || favActresses["Example"] {
		t.Fatal("removed preference returned after reload")
	}
}
