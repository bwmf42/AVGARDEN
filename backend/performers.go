package main

import (
	"regexp"
	"strings"
)

var performerProfilePattern = regexp.MustCompile(`(?i)[0-9]{1,3}\s*(?:歳|才|岁|さい|years?\s*old)|[（(]\s*[0-9]{1,3}\s*[）)]|大学生|女子大生|専門学生|学生モデル|モデル|会社員|専業主婦|主婦|フリーター|アルバイト|職業|职业|看護師|护士|保育士|店員|受付|新規\s*[0-9]+\s*分コース|腋もアナルも綺麗`)

func isPerformerProfile(value string) bool {
	return performerProfilePattern.MatchString(value)
}

// Separate legacy profile labels before actor filters/favorites are evaluated.
// Raw notes remain visible, without claiming they are reusable person identities.
func normalizePerformerFields(item map[string]interface{}) {
	notes := []interface{}{}
	seen := map[string]bool{}
	appendNote := func(value interface{}) {
		if text, ok := value.(string); ok {
			text = strings.TrimSpace(text)
			if text != "" && !seen[text] {
				seen[text] = true
				notes = append(notes, text)
			}
		}
	}
	for _, value := range interfaceStringList(item["performerNotes"]) {
		appendNote(value)
	}
	names := []interface{}{}
	for _, value := range interfaceStringList(item["actresses"]) {
		text := strings.TrimSpace(value)
		if isPerformerProfile(text) || seen[text] {
			appendNote(text)
		} else if text != "" {
			names = append(names, text)
		}
	}
	item["actresses"] = names
	if len(notes) > 0 {
		item["performerNotes"] = notes
	}
}

func interfaceStringList(value interface{}) []string {
	switch list := value.(type) {
	case []string:
		return list
	case []interface{}:
		result := []string{}
		for _, value := range list {
			if text, ok := value.(string); ok {
				result = append(result, text)
			}
		}
		return result
	}
	return nil
}
