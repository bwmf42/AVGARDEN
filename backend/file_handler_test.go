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
	t.Logf("GET %s Range bytes=2-5 -> %d %q", req.URL.Path, res.Code, res.Body.String())
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

func TestImageHandlerMediaRootScope(t *testing.T) {
	root := withTestMediaRoot(t)
	for _, relative := range []string{
		"艾薇/x/a.mp4", "__trash__/x/a.mp4", "incomplete/x/a.mp4", "thumb/x/a.jpg",
		"__hidden_START-656/x/a.mp4", "OMG-032/cover.jpg", "OMG-032/preview.jpg",
		"__weekly__/OMG-032/cover.jpg", "__online__/OMG-032/preview.jpg",
	} {
		path := filepath.Join(root, relative)
		if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte("fixture"), 0644); err != nil {
			t.Fatal(err)
		}
	}
	for _, tc := range []struct {
		path string
		want int
	}{
		{"/file/艾薇/x/a.mp4", 404},
		{"/file/__trash__/x/a.mp4", 404},
		{"/file/incomplete/x/a.mp4", 404},
		{"/file/thumb/x/a.jpg", 404},
		{"/file/%20incomplete%20/x/a.mp4", 404},
		{"/file/%E8%89%BE%E8%96%87/x/a.mp4", 404},
		// A normal-looking ID can resolve to a skipped directory by its embedded code.
		{"/file/START-656/x/a.mp4", 404},
		{"/file/OMG-032/cover.jpg", 200},
		{"/file/OMG-032/preview.jpg", 200},
		{"/file/__weekly__/OMG-032/cover.jpg", 200},
		{"/file/__online__/OMG-032/preview.jpg", 200},
	} {
		t.Run(tc.path, func(t *testing.T) {
			res := httptest.NewRecorder()
			imageHandler(res, httptest.NewRequest(http.MethodGet, tc.path, nil))
			t.Logf("GET %s -> %d", tc.path, res.Code)
			if res.Code != tc.want {
				t.Fatalf("status=%d body=%q, want %d", res.Code, res.Body.String(), tc.want)
			}
			if tc.want == http.StatusOK && res.Body.String() != "fixture" {
				t.Fatalf("unexpected file content: %q", res.Body.String())
			}
		})
	}
}
