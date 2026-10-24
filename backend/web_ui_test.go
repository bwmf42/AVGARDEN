package main

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

var webUICases = []struct {
	name    string
	value   string
	enabled bool
}{
	{"unset", "", true},
	{"empty", "", true},
	{"on", "on", true},
	{"uppercase_on", "ON", true},
	{"yes", "yes", true},
	{"zero", "0", true},
	{"off_suffix", "off-now", true},
	{"off", "off", false},
	{"padded_off", " Off ", false},
	{"uppercase_off", "OFF", false},
}

func TestWebUIEnabled(t *testing.T) {
	for _, tc := range webUICases {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("AVGARDEN_WEB_UI", tc.value)
			if tc.name == "unset" {
				if err := os.Unsetenv("AVGARDEN_WEB_UI"); err != nil {
					t.Fatal(err)
				}
			}
			if got := webUIEnabled(os.Getenv); got != tc.enabled {
				t.Fatalf("webUIEnabled = %v, want %v", got, tc.enabled)
			}
		})
	}
}

func webUIFixture(t *testing.T) (string, string) {
	t.Helper()
	previous := frontendDir
	frontendDir = t.TempDir()
	t.Cleanup(func() { frontendDir = previous })
	index := `<html><script src="/assets/x.js"></script><link href="/assets/x.css"></html>`
	asset := "console.log('legacy UI');\n"
	if err := os.MkdirAll(filepath.Join(frontendDir, "assets"), 0o755); err != nil {
		t.Fatal(err)
	}
	for path, body := range map[string]string{"index.html": index, "assets/x.js": asset} {
		if err := os.WriteFile(filepath.Join(frontendDir, path), []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	return index, asset
}

func TestWebUIFallback(t *testing.T) {
	index, asset := webUIFixture(t)
	fixtureDir := frontendDir
	previousLogger := logger
	var logs bytes.Buffer
	logger = log.New(&logs, "", 0)
	t.Cleanup(func() { logger = previousLogger })
	for _, present := range []bool{true, false} {
		for _, tc := range webUICases {
			t.Run(tc.name+"/frontend_present="+map[bool]string{true: "yes", false: "no"}[present], func(t *testing.T) {
				frontendDir = fixtureDir
				if !present {
					frontendDir = filepath.Join(fixtureDir, "missing")
				}
				t.Setenv("AVGARDEN_WEB_UI", tc.value)
				logs.Reset()
				mux := http.NewServeMux()
				registerWebUI(mux, os.Getenv)
				if !tc.enabled && !strings.Contains(logs.String(), "disabled by AVGARDEN_WEB_UI=off") {
					t.Fatalf("missing disabled startup log: %s", logs.String())
				}
				for _, path := range []string{"/", "/weekly", "/download", "/assets/x.js", "/assets/missing.js", "/anything"} {
					rec := httptest.NewRecorder()
					mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
					if !tc.enabled {
						if rec.Code != http.StatusNotFound || rec.Body.String() != "旧网页界面已关闭，请使用 Peach\n" || rec.Header().Get("Cache-Control") != "no-store" || rec.Header().Get("Content-Type") != "text/plain; charset=utf-8" {
							t.Fatalf("%s: disabled response = %d %v %q", path, rec.Code, rec.Header(), rec.Body.String())
						}
						continue
					}
					want, cacheControl := index, "no-cache"
					if path == "/assets/x.js" {
						want, cacheControl = asset, ""
					}
					if !present {
						want, cacheControl = "AV/GARDEN Server API is running.\nFrontend not available — build the Vue project first.", ""
						if rec.Header().Get("Content-Type") != "text/plain" || !strings.Contains(logs.String(), "API only mode") {
							t.Fatal("API only mode content type or log changed")
						}
					}
					if rec.Code != http.StatusOK || rec.Body.String() != want || rec.Header().Get("Cache-Control") != cacheControl {
						t.Fatalf("%s: enabled response = %d %v %q, want %q", path, rec.Code, rec.Header(), rec.Body.String(), want)
					}
				}
			})
		}
	}
}

func TestWebUIKeepsAPIAndFiles(t *testing.T) {
	index, _ := webUIFixture(t)
	previousBase, previousQueue, previousAPI := basePath, queuePath, queueAPI
	previousClient, previousOnlineClient := queueHTTPClient, onlineQueueHTTPClient
	basePath, queuePath, queueAPI = t.TempDir(), filepath.Join(t.TempDir(), "queue.txt"), "http://queue.test"
	t.Cleanup(func() {
		basePath, queuePath, queueAPI = previousBase, previousQueue, previousAPI
		queueHTTPClient, onlineQueueHTTPClient = previousClient, previousOnlineClient
	})
	const resolveBody = `{"code":"START-653","kind":"magnet","magnet":"magnet:?xt=urn:btih:TEST"}`
	client := &http.Client{Transport: resolveRoundTripper(func(r *http.Request) (*http.Response, error) {
		body := `[{"code":"START-653","status":"downloading","target":"qb","transport":"qb"}]`
		switch r.URL.RequestURI() {
		case "/api/queue":
		case "/api/resolve/START-653?test=1":
			body = resolveBody
			if r.Header.Get("X-Request-ID") != "web-ui-test" {
				t.Fatal("resolve request ID was not forwarded")
			}
		default:
			t.Fatalf("unexpected upstream request: %s", r.URL)
		}
		return &http.Response{StatusCode: http.StatusOK, Header: http.Header{"Content-Type": {"application/json"}}, Body: io.NopCloser(strings.NewReader(body))}, nil
	})}
	queueHTTPClient, onlineQueueHTTPClient = client, client
	if err := os.MkdirAll(filepath.Join(basePath, "START-653"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(basePath, "START-653", "poster.jpg"), []byte("file bytes"), 0o600); err != nil {
		t.Fatal(err)
	}
	baseline := map[string]map[string]interface{}{}
	for _, setting := range []string{"on", "off", " Off "} {
		t.Run(setting, func(t *testing.T) {
			t.Setenv("AVGARDEN_WEB_UI", setting)
			mux := http.NewServeMux()
			mux.HandleFunc("/api/version", versionHandler)
			mux.HandleFunc("/api/queue-status", queueStatusHandler)
			mux.HandleFunc("/api/resolve/", resolveHandler)
			mux.HandleFunc("/file/", imageHandler)
			registerWebUI(mux, os.Getenv)
			handler := gzipMiddleware(enableCORS(mux))
			for _, path := range []string{"/api/version", "/api/queue-status", "/api/resolve/START-653?test=1", "/file/START-653/poster.jpg"} {
				req := httptest.NewRequest(http.MethodGet, path, nil)
				req.Header.Set("Accept-Encoding", "gzip")
				req.Header.Set("X-Request-ID", "web-ui-test")
				rec := httptest.NewRecorder()
				handler.ServeHTTP(rec, req)
				if rec.Code != http.StatusOK || rec.Header().Get("Access-Control-Allow-Origin") != "*" || rec.Header().Get("Content-Encoding") != "gzip" || rec.Header().Get("Cache-Control") == "no-store" {
					t.Fatalf("%s: API/file response = %d %v", path, rec.Code, rec.Header())
				}
				reader, err := gzip.NewReader(rec.Body)
				if err != nil {
					t.Fatal(err)
				}
				body, err := io.ReadAll(reader)
				reader.Close()
				if err != nil {
					t.Fatal(err)
				}
				if strings.HasPrefix(path, "/file/") {
					if string(body) != "file bytes" {
						t.Fatalf("file body changed: %q", body)
					}
					continue
				}
				var payload map[string]interface{}
				if err := json.Unmarshal(body, &payload); err != nil {
					t.Fatal(err)
				}
				if path == "/api/version" {
					if payload["frontend_js"] != "/assets/x.js" || payload["frontend_css"] != "/assets/x.css" || payload["frontend_index"] != filepath.Join(frontendDir, "index.html") || payload["build_time"] == "" || payload["server_time"] == "" || payload["version"] == "" {
						t.Fatalf("version payload changed: %s", body)
					}
					delete(payload, "server_time")
				}
				if setting == "on" {
					baseline[path] = payload
				} else if !reflect.DeepEqual(payload, baseline[path]) {
					t.Fatalf("%s: UI switch changed API payload: %s", path, body)
				}
				if strings.HasPrefix(path, "/api/resolve/") && string(body) != resolveBody {
					t.Fatalf("resolve body changed: %s", body)
				}
				if path == "/api/queue-status" {
					var status queueStatusResponse
					if err := json.Unmarshal(body, &status); err != nil || len(status.Active) != 1 || status.Active[0].ID != "START-653" {
						t.Fatalf("queue-status payload changed: %s", body)
					}
				}
			}
			preflight := httptest.NewRecorder()
			handler.ServeHTTP(preflight, httptest.NewRequest(http.MethodOptions, "/api/resolve/START-653", nil))
			if preflight.Code != http.StatusOK || preflight.Header().Get("Access-Control-Allow-Methods") != "GET, POST, OPTIONS, PUT, DELETE" {
				t.Fatalf("CORS preflight changed: %d %v", preflight.Code, preflight.Header())
			}
			if body, err := os.ReadFile(filepath.Join(frontendDir, "index.html")); err != nil || string(body) != index {
				t.Fatal("frontend index was changed or removed")
			}
		})
	}
}
