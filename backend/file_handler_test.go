package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestImageHandlerSupportsRangeInsideOwnerDirectory(t *testing.T) {
	root := withTestMediaRoot(t)
	path := filepath.Join(root, "OMG-032", "OMG-032.mp4")
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("0123456789"), 0644); err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodGet, "/file/OMG-032/OMG-032.mp4", nil)
	req.Header.Set("Range", "bytes=2-5")
	res := httptest.NewRecorder()
	imageHandler(res, req)
	if res.Code != http.StatusPartialContent || res.Body.String() != "2345" {
		t.Fatalf("status=%d body=%q", res.Code, res.Body.String())
	}
}

func TestImageHandlerRejectsCrossTitleAndEscapingSymlink(t *testing.T) {
	root := withTestMediaRoot(t)
	owner := filepath.Join(root, "OMG-032")
	other := filepath.Join(root, "ROE-500")
	if err := os.MkdirAll(owner, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(other, 0755); err != nil {
		t.Fatal(err)
	}
	secret := filepath.Join(other, "secret.jpg")
	if err := os.WriteFile(secret, []byte("secret"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(secret, filepath.Join(owner, "escape.jpg")); err != nil {
		t.Fatal(err)
	}

	for _, path := range []string{
		"/file/OMG-032/../ROE-500/secret.jpg",
		"/file/OMG-032/escape.jpg",
	} {
		res := httptest.NewRecorder()
		imageHandler(res, httptest.NewRequest(http.MethodGet, path, nil))
		if res.Code < 400 {
			t.Fatalf("path %q unexpectedly returned %d", path, res.Code)
		}
	}
}

func TestImageHandlerSeparatesWeeklyOwners(t *testing.T) {
	root := withTestMediaRoot(t)
	path := filepath.Join(root, "__weekly__", "OMG-032", "cover.jpg")
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("cover"), 0644); err != nil {
		t.Fatal(err)
	}
	res := httptest.NewRecorder()
	imageHandler(res, httptest.NewRequest(http.MethodGet, "/file/__weekly__/OMG-032/cover.jpg", nil))
	if res.Code != http.StatusOK || !strings.Contains(res.Body.String(), "cover") {
		t.Fatalf("status=%d body=%q", res.Code, res.Body.String())
	}
}

func TestConfiguredHTTPServerTimeouts(t *testing.T) {
	server := configuredHTTPServer(http.NewServeMux())
	if server.ReadTimeout != serverReadTimeout || server.ReadHeaderTimeout != serverReadHeaderTimeout ||
		server.WriteTimeout != serverWriteTimeout || server.IdleTimeout != serverIdleTimeout {
		t.Fatalf("unexpected timeouts: %#v", server)
	}
}
