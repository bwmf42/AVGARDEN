package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func configureBlockByCodeTestMedia(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	oldBasePath := basePath
	basePath = root
	t.Cleanup(func() { basePath = oldBasePath })
	return root
}

func writeTestNFO(t *testing.T, root, code string, actresses ...string) {
	t.Helper()
	dir := filepath.Join(root, code)
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatal(err)
	}
	var actors strings.Builder
	for _, name := range actresses {
		actors.WriteString("<actor><name>" + name + "</name></actor>")
	}
	nfo := "<?xml version=\"1.0\" encoding=\"UTF-8\"?><movie>" + actors.String() + "</movie>"
	if err := os.WriteFile(filepath.Join(dir, code+".nfo"), []byte(nfo), 0644); err != nil {
		t.Fatal(err)
	}
}

func TestBlockByCodeReadsLibraryNFOAndNormalizesCode(t *testing.T) {
	root := configureBlockByCodeTestMedia(t)
	writeTestNFO(t, root, "300MIUM-1395", "河北彩花", "----")

	request := httptest.NewRequest(http.MethodGet, "/api/block-by-code/300mium1395", nil)
	response := httptest.NewRecorder()
	blockByCodeHandler(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	var payload struct {
		Code      string   `json:"code"`
		Source    string   `json:"source"`
		Actresses []string `json:"actresses"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.Code != "300MIUM-1395" || payload.Source != "library" {
		t.Fatalf("payload = %+v", payload)
	}
	if len(payload.Actresses) != 1 || payload.Actresses[0] != "河北彩伽" {
		t.Fatalf("actresses = %#v", payload.Actresses)
	}
}

func TestBlockByCodeDoesNotDropRealNumericPrefixDuringLibraryLookup(t *testing.T) {
	root := configureBlockByCodeTestMedia(t)
	writeTestNFO(t, root, "259LUXU-1234-C", "错误女优")
	writeTestNFO(t, root, "300LUXU-1234-C", "正确女优")

	request := httptest.NewRequest(http.MethodGet, "/api/block-by-code/300luxu1234", nil)
	response := httptest.NewRecorder()
	blockByCodeHandler(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	var payload struct {
		Actresses []string `json:"actresses"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload.Actresses) != 1 || payload.Actresses[0] != "正确女优" {
		t.Fatalf("actresses = %#v", payload.Actresses)
	}
}

func TestBlockByCodeCanMatchLegacySourcePrefixedFolder(t *testing.T) {
	root := configureBlockByCodeTestMedia(t)
	writeTestNFO(t, root, "857OMG-032", "小島みこ")

	request := httptest.NewRequest(http.MethodGet, "/api/block-by-code/OMG032", nil)
	response := httptest.NewRecorder()
	blockByCodeHandler(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	if !strings.Contains(response.Body.String(), "小島みこ") {
		t.Fatalf("body = %s", response.Body.String())
	}
}

func TestBlockByCodeRequiresSelectionAndExpandsRenameAliases(t *testing.T) {
	configureBlockedListTestFiles(t)

	emptyRequest := httptest.NewRequest(http.MethodPost, "/api/block-by-code/SNOS233", strings.NewReader(`{}`))
	emptyResponse := httptest.NewRecorder()
	blockByCodeHandler(emptyResponse, emptyRequest)
	if emptyResponse.Code != http.StatusBadRequest {
		t.Fatalf("empty selection status = %d", emptyResponse.Code)
	}

	request := httptest.NewRequest(
		http.MethodPost,
		"/api/block-by-code/SNOS233",
		strings.NewReader(`{"actresses":["河北彩伽"]}`),
	)
	response := httptest.NewRecorder()
	blockByCodeHandler(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	if !isBlockedActressName("河北彩伽") || !isBlockedActressName("河北彩花") {
		t.Fatal("rename aliases should both match the block list")
	}
	data, err := os.ReadFile(blockedActressesFile)
	if err != nil {
		t.Fatal(err)
	}
	text := string(data)
	if strings.Count(text, "河北彩伽\n") != 1 || strings.Count(text, "河北彩花\n") != 1 {
		t.Fatalf("block list should contain both aliases once: %q", text)
	}

	repeatResponse := httptest.NewRecorder()
	repeatRequest := httptest.NewRequest(
		http.MethodPost,
		"/api/block-by-code/SNOS233",
		strings.NewReader(`{"actresses":["河北彩伽"]}`),
	)
	blockByCodeHandler(repeatResponse, repeatRequest)
	if repeatResponse.Code != http.StatusOK {
		t.Fatalf("repeat status = %d", repeatResponse.Code)
	}
	data, err = os.ReadFile(blockedActressesFile)
	if err != nil {
		t.Fatal(err)
	}
	text = string(data)
	if strings.Count(text, "河北彩伽\n") != 1 || strings.Count(text, "河北彩花\n") != 1 {
		t.Fatalf("repeat must not duplicate aliases: %q", text)
	}
}

func TestBlockByCodeDistinguishesNotFoundFromUnavailable(t *testing.T) {
	configureBlockByCodeTestMedia(t)
	oldQueueAPI := queueAPI
	t.Cleanup(func() { queueAPI = oldQueueAPI })

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"source":"none","actresses":[],"error":"no actresses found"}`))
	}))
	queueAPI = server.URL
	request := httptest.NewRequest(http.MethodGet, "/api/block-by-code/OMG032", nil)
	response := httptest.NewRecorder()
	blockByCodeHandler(response, request)
	server.Close()
	if response.Code != http.StatusNotFound || !strings.Contains(response.Body.String(), "未找到女优") {
		t.Fatalf("not-found response = %d %s", response.Code, response.Body.String())
	}

	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = w.Write([]byte(`{"error":"unavailable"}`))
	}))
	defer server.Close()
	queueAPI = server.URL
	request = httptest.NewRequest(http.MethodGet, "/api/block-by-code/OMG032", nil)
	response = httptest.NewRecorder()
	blockByCodeHandler(response, request)
	if response.Code != http.StatusBadGateway || !strings.Contains(response.Body.String(), "查询服务暂不可用") {
		t.Fatalf("unavailable response = %d %s", response.Code, response.Body.String())
	}
}
