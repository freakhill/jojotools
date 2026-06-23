package main

// keys.go — JIT secret fetch from 1Password via the `op` CLI, mirroring
// server.py:_read_*_from_op / _get_*_api_key. Keys are read once per process,
// cached, and never logged. Env vars are the documented fallback.

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"
)

type opField struct {
	ID    string `json:"id"`
	Value string `json:"value"`
}

func opItemFields(item string) []opField {
	if _, err := exec.LookPath("op"); err != nil {
		return nil
	}
	vault := os.Getenv("AI_ROUTER_OP_VAULT")
	if vault == "" {
		vault = "claude"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, "op", "item", "get", item,
		"--vault", vault, "--reveal", "--format", "json").Output()
	if err != nil {
		return nil
	}
	var parsed struct {
		Fields []opField `json:"fields"`
	}
	if json.Unmarshal(out, &parsed) != nil {
		return nil
	}
	return parsed.Fields
}

func fieldVal(f opField) string { return strings.TrimSpace(f.Value) }

// --- OpenRouter key (op://claude/openrouter-api-key) ---

var (
	orKeyOnce sync.Once
	orKey     string
)

// pickByPrefixThenID selects a key from op fields: first a value with one of
// `prefixes`, then the first non-empty value whose id is in `idsAllowed`.
// Pure → unit-tested without a live `op`.
func pickByPrefixThenID(fields []opField, prefixes, idsAllowed []string) string {
	for _, f := range fields {
		for _, p := range prefixes {
			if strings.HasPrefix(fieldVal(f), p) {
				return fieldVal(f)
			}
		}
	}
	for _, f := range fields {
		if contains(idsAllowed, f.ID) && fieldVal(f) != "" {
			return fieldVal(f)
		}
	}
	return ""
}

func pickORKey(fields []opField) string {
	return pickByPrefixThenID(fields, []string{"sk-or"}, []string{"credential", "password"})
}

func pickKimiKey(fields []opField) string {
	return pickByPrefixThenID(fields, []string{"sk-"}, []string{"credential", "password", "notesPlain"})
}

// pickGLMKey: GLM keys have no fixed prefix — secure-note/credential first, else any value.
func pickGLMKey(fields []opField) string {
	if v := pickByPrefixThenID(fields, nil, []string{"credential", "password", "notesPlain"}); v != "" {
		return v
	}
	for _, f := range fields {
		if fieldVal(f) != "" {
			return fieldVal(f)
		}
	}
	return ""
}

func readORKeyFromOp() string { return pickORKey(opItemFields("openrouter-api-key")) }

func getORKey() string {
	if orKey != "" { // test seam: pre-set bypasses op
		return orKey
	}
	orKeyOnce.Do(func() { orKey = readORKeyFromOp() })
	return orKey
}

// --- Kimi key (op://claude/kimi-api-key, env KIMI_API_KEY fallback) ---

var (
	kimiKeyOnce sync.Once
	kimiKey     string
)

func readKimiKeyFromOp() string { return pickKimiKey(opItemFields("kimi-api-key")) }

func getKimiKey() string {
	if kimiKey != "" {
		return kimiKey
	}
	kimiKeyOnce.Do(func() {
		kimiKey = readKimiKeyFromOp()
		if kimiKey == "" {
			kimiKey = os.Getenv("KIMI_API_KEY")
		}
	})
	return kimiKey
}

// --- GLM key (op://claude/glm-api-key, env GLM_API_KEY fallback) ---

var (
	glmKeyOnce sync.Once
	glmKey     string
)

func readGLMKeyFromOp() string { return pickGLMKey(opItemFields("glm-api-key")) }

func getGLMKey() string {
	if glmKey != "" {
		return glmKey
	}
	glmKeyOnce.Do(func() {
		glmKey = readGLMKeyFromOp()
		if glmKey == "" {
			glmKey = os.Getenv("GLM_API_KEY")
		}
	})
	return glmKey
}
