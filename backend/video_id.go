package main

import (
	"regexp"
	"strings"
	"unicode"
)

var (
	fc2InputPattern       = regexp.MustCompile(`^FC2(?:\s*[-_]?\s*PPV)?\s*[-_]?\s*(\d{5,8})$`)
	heydougaInputPattern  = regexp.MustCompile(`^HEY(?:DOUGA)?\s*[-_]?\s*(\d{4})\s*[-_]\s*0?(\d{3,5})$`)
	simpleSpecialPattern  = regexp.MustCompile(`^(HEYZO|GETCHU|GYUTTO)\s*[-_]?\s*(\d{3,8})$`)
	mugenSPattern         = regexp.MustCompile(`^(MKB?D)\s*[-_]?\s*(S\d{2,3})$`)
	mugenNumberPattern    = regexp.MustCompile(`^(MK3D2DBD|S2M|S2MBD)\s*[-_]?\s*(\d{2,3})$`)
	tmaInputPattern       = regexp.MustCompile(`^(T[23]8)\s*[-_]?\s*(\d{3})$`)
	r18InputPattern       = regexp.MustCompile(`^R18\s*[-_]?\s*(\d{3})$`)
	ibwInputPattern       = regexp.MustCompile(`^(IBW)\s*[-_]?\s*(\d{2,5}Z)$`)
	numericDatePattern    = regexp.MustCompile(`^(\d{6})[-_](\d{2,3})$`)
	compactKeepPattern    = regexp.MustCompile(`^(?:(?:N|K)\d{4}|RED[01]\d{2}|SKY[0-3]\d{2}|EX00[01]\d)$`)
	separatedInputPattern = regexp.MustCompile(`^([A-Z0-9]*[A-Z][A-Z0-9]{0,15})\s*[-_]\s*(\d{2,8})([A-Z]?)$`)
	compactInputPattern   = regexp.MustCompile(`^([0-9]*[A-Z][A-Z0-9]*[A-Z])(\d{2,8})([A-Z]?)$`)
	dmmHInputPattern      = regexp.MustCompile(`^H_\d{3,4}[A-Z]{1,10}\d{2,5}[A-Z0-9]{0,8}$`)
	dmmNumericPattern     = regexp.MustCompile(`^\d{3}_\d{4,5}$`)
	dmm402Pattern         = regexp.MustCompile(`^402[A-Z]{3,6}\d*_[A-Z]{3,8}\d{5,6}$`)
	localSourcePattern    = regexp.MustCompile(`^(?:328|348|390|420|857|892)([A-Z][A-Z0-9]{1,15}-\d{2,8}[A-Z]?)`)
	localLeadingPattern   = regexp.MustCompile(`^([0-9]*[A-Z][A-Z0-9]{0,15}-\d{2,8}[A-Z]?)(?:$|[-_ .(])`)
	localAnywherePattern  = regexp.MustCompile(`([A-Z][A-Z0-9]{1,15}-\d{2,8}[A-Z]?)`)
	legacySourcePattern   = regexp.MustCompile(`^\d+([A-Z][A-Z0-9]{1,15}-\d{2,8}[A-Z]?)`)
)

func prepareVideoIDInput(raw string) string {
	var normalized strings.Builder
	for _, r := range raw {
		if r == '\u3000' {
			r = ' '
		} else if r >= '\uff01' && r <= '\uff5e' {
			r -= 0xfee0
		}
		normalized.WriteRune(r)
	}
	replacer := strings.NewReplacer("‐", "-", "‑", "-", "‒", "-", "–", "-", "—", "-", "−", "-", "－", "-")
	value := strings.ToUpper(strings.TrimSpace(replacer.Replace(normalized.String())))
	if value == "" || len(value) > 64 || strings.Contains(value, "/") || strings.Contains(value, `\`) || strings.Contains(value, "..") {
		return ""
	}
	for _, r := range value {
		if unicode.IsControl(r) {
			return ""
		}
	}
	return value
}

func canonicalVideoIDSuffix(suffix string) string {
	if suffix == "V" {
		return ""
	}
	return suffix
}

func normalizeUserVideoID(raw string) string {
	value := prepareVideoIDInput(raw)
	if value == "" {
		return ""
	}

	patterns := []struct {
		re *regexp.Regexp
		fn func([]string) string
	}{
		{fc2InputPattern, func(m []string) string { return "FC2-" + m[1] }},
		{heydougaInputPattern, func(m []string) string { return "HEYDOUGA-" + m[1] + "-" + m[2] }},
		{simpleSpecialPattern, func(m []string) string { return m[1] + "-" + m[2] }},
		{mugenSPattern, func(m []string) string { return m[1] + "-" + m[2] }},
		{mugenNumberPattern, func(m []string) string { return m[1] + "-" + m[2] }},
		{tmaInputPattern, func(m []string) string { return m[1] + "-" + m[2] }},
		{r18InputPattern, func(m []string) string { return "R18-" + m[1] }},
		{ibwInputPattern, func(m []string) string { return m[1] + "-" + m[2] }},
		{numericDatePattern, func(m []string) string { return m[1] + "-" + m[2] }},
		{separatedInputPattern, func(m []string) string { return m[1] + "-" + m[2] + canonicalVideoIDSuffix(m[3]) }},
	}
	for _, pattern := range patterns {
		if match := pattern.re.FindStringSubmatch(value); match != nil {
			return pattern.fn(match)
		}
	}
	if compactKeepPattern.MatchString(value) || dmmHInputPattern.MatchString(value) || dmmNumericPattern.MatchString(value) || dmm402Pattern.MatchString(value) {
		return value
	}
	if match := compactInputPattern.FindStringSubmatch(value); match != nil && len(match[1]) <= 16 {
		return match[1] + "-" + match[2] + canonicalVideoIDSuffix(match[3])
	}
	return ""
}

func normalizeLocalVideoID(raw string) string {
	value := strings.ToUpper(strings.TrimSpace(raw))
	if value == "" {
		return ""
	}
	value = strings.ReplaceAll(value, `\`, "/")
	if index := strings.LastIndex(value, "/"); index >= 0 {
		value = value[index+1:]
	}
	if match := localSourcePattern.FindStringSubmatch(value); match != nil {
		if normalized := normalizeUserVideoID(match[1]); normalized != "" {
			return normalized
		}
	}
	if match := localLeadingPattern.FindStringSubmatch(value); match != nil {
		if normalized := normalizeUserVideoID(match[1]); normalized != "" {
			return normalized
		}
	}
	for _, match := range localAnywherePattern.FindAllStringSubmatch(value, -1) {
		if normalized := normalizeUserVideoID(match[1]); normalized != "" {
			return normalized
		}
	}
	return normalizeUserVideoID(value)
}

func legacyLocalVideoID(raw string) string {
	value := strings.ToUpper(strings.TrimSpace(raw))
	if match := legacySourcePattern.FindStringSubmatch(value); match != nil {
		return normalizeUserVideoID(match[1])
	}
	return ""
}

func comparableVideoID(raw string) string {
	if normalized := normalizeUserVideoID(raw); normalized != "" {
		return normalized
	}
	return cleanVideoID(raw)
}
