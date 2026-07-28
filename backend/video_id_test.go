package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestNormalizeUserVideoID(t *testing.T) {
	cases := map[string]string{
		"omg-032":            "OMG-032",
		"OMG032":             "OMG-032",
		"ABP984":             "ABP-984",
		"ＡＢＰ９８４":             "ABP-984",
		"300MIUM-1395":       "300MIUM-1395",
		"300mium1395":        "300MIUM-1395",
		"259luxu1234":        "259LUXU-1234",
		"857OMG-032":         "857OMG-032",
		"FC2 PPV 1234567":    "FC2-1234567",
		"fc2ppv_1234567":     "FC2-1234567",
		"062620_001":         "062620-001",
		"HEYZO1009":          "HEYZO-1009",
		"heydouga-4017-0123": "HEYDOUGA-4017-123",
		"T28557":             "T28-557",
		"IBW123Z":            "IBW-123Z",
		"START-612V":         "START-612",
		"start612v":          "START-612",
		"N1234":              "N1234",
		"h_086abc00123":      "H_086ABC00123",
	}
	for raw, expected := range cases {
		if actual := normalizeUserVideoID(raw); actual != expected {
			t.Errorf("normalizeUserVideoID(%q) = %q, want %q", raw, actual, expected)
		}
	}
}

func TestNormalizeUserVideoIDRejectsUnsafeInput(t *testing.T) {
	for _, raw := range []string{"../OMG-032", "OMG-032; touch X", "ABC", "123456", "A/B-123", ""} {
		if actual := normalizeUserVideoID(raw); actual != "" {
			t.Errorf("normalizeUserVideoID(%q) = %q, want empty", raw, actual)
		}
	}
}

func TestIsPathInsideBase(t *testing.T) {
	if !isPathInsideBase("/data/OMG-032/cover.jpg", "/data") {
		t.Fatal("expected /data/OMG-032/cover.jpg under /data")
	}
	if !isPathInsideBase("/data", "/data") {
		t.Fatal("base itself should be allowed")
	}
	// Classic prefix trap: /data-evil must not match base /data
	if isPathInsideBase("/data-evil/secret", "/data") {
		t.Fatal("/data-evil must not be treated as under /data")
	}
	if isPathInsideBase("/etc/passwd", "/data") {
		t.Fatal("/etc/passwd must not be under /data")
	}
}

func TestNormalizeLocalVideoIDPreservesRealNumericPrefixes(t *testing.T) {
	cases := map[string]string{
		"300MIUM-1395":           "300MIUM-1395",
		"259LUXU-1881":           "259LUXU-1881",
		"857OMG-032":             "OMG-032",
		"420HOI-397":             "HOI-397",
		"18bt.net_VENX-276C.mp4": "VENX-276C",
		"fns-224ch":              "FNS-224",
		"[HD] FNS-224-CH.mp4":    "FNS-224",
	}
	for raw, expected := range cases {
		if actual := normalizeLocalVideoID(raw); actual != expected {
			t.Errorf("normalizeLocalVideoID(%q) = %q, want %q", raw, actual, expected)
		}
	}
}

func TestResolveVideoDirHandlesLocalChineseSuffix(t *testing.T) {
	root := withTestMediaRoot(t)
	if err := os.Mkdir(filepath.Join(root, "fns-224ch"), 0755); err != nil {
		t.Fatal(err)
	}
	dir, id := resolveVideoDir("FNS-224")
	if dir != "fns-224ch" || id != "FNS-224" {
		t.Fatalf("dir=%q id=%q", dir, id)
	}
}

func TestResolveVideoDirKeepsLegacyURLAliasButReturnsCanonicalID(t *testing.T) {
	root := withTestMediaRoot(t)
	if err := os.Mkdir(filepath.Join(root, "300MIUM-1395"), 0755); err != nil {
		t.Fatal(err)
	}
	dir, id := resolveVideoDir("MIUM-1395")
	if dir != "300MIUM-1395" || id != "300MIUM-1395" {
		t.Fatalf("dir=%q id=%q", dir, id)
	}
}
