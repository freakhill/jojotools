package main

// http.go — chat/image/probe transport + overflow-to-file + parallel helper.
// Ports server.py:_chat / _glm_chat / _or_chat / or_image / _probe_endpoint /
// _output_or_file. ZDR ("provider":{"data_collection":"deny"}) is injected on
// EVERY OpenRouter call (chat + image) and is never caller-overridable.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

const (
	orReferer = "https://github.com/freakhill/jojotools"
	orTitle   = "ai-router-mcp"

	kimiCodingModel = "kimi-for-coding"

	defaultMaxTokens = 16384
	maxRetries       = 2
	retryBackoff     = time.Second
)

// Base URLs are vars so tests can point them at an httptest server.
var (
	orBaseURL   = "https://openrouter.ai/api/v1"
	kimiBaseURL = "https://api.kimi.com/coding/v1"
)

// env-overridable knobs (server.py reads these from the environment)
var (
	kimiUA        = env("KIMI_USER_AGENT", "KimiCLI/1.44.0")
	kimiGenModel  = env("KIMI_GENERAL_MODEL", "kimi-k2.7")
	glmBaseURL    = env("GLM_BASE_URL", "https://api.z.ai/api/coding/paas/v4")
	glmModel      = env("GLM_MODEL", "glm-5.1")
	glmUA         = env("GLM_USER_AGENT", "ai-router-mcp/glm")
	retryStatuses = map[int]bool{429: true, 500: true, 502: true, 503: true, 504: true}
	// No client-level timeout — deadlines are applied per-call via context so a
	// 600s kimi_swarm and a 15s probe can share one connection pool.
	httpClient = &http.Client{}
)

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// postChat sends an OpenAI-style chat request with retry on transient statuses.
// The timeout covers all attempts (matches server.py's per-call timeout arg).
func postChat(ctx context.Context, baseURL string, headers map[string]string, payload map[string]any, timeout time.Duration) (parsed map[string]any, status int, err error) {
	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	body, _ := json.Marshal(payload)
	var lastErr error
	for attempt := 0; attempt <= maxRetries; attempt++ {
		req, e := http.NewRequestWithContext(cctx, http.MethodPost, baseURL+"/chat/completions", bytes.NewReader(body))
		if e != nil {
			return nil, 0, e
		}
		for k, v := range headers {
			req.Header.Set(k, v)
		}
		resp, e := httpClient.Do(req)
		if e != nil {
			lastErr = e
			if attempt < maxRetries {
				time.Sleep(retryBackoff * time.Duration(attempt+1))
				continue
			}
			return nil, 0, e
		}
		data, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if retryStatuses[resp.StatusCode] && attempt < maxRetries {
			time.Sleep(retryBackoff * time.Duration(attempt+1))
			continue
		}
		var out map[string]any
		_ = json.Unmarshal(data, &out)
		return out, resp.StatusCode, nil
	}
	return nil, 0, lastErr
}

func extractMessage(parsed map[string]any) (content, reasoning string) {
	choices, ok := parsed["choices"].([]any)
	if !ok || len(choices) == 0 {
		return "", ""
	}
	c0, _ := choices[0].(map[string]any)
	msg, _ := c0["message"].(map[string]any)
	content, _ = msg["content"].(string)
	reasoning, _ = msg["reasoning_content"].(string)
	if content == "" && reasoning != "" {
		content, reasoning = reasoning, ""
	}
	return content, reasoning
}

func withReasoning(content, reasoning string, include bool) string {
	if include && reasoning != "" {
		return "<reasoning>\n" + reasoning + "\n</reasoning>\n\n" + content
	}
	return content
}

func apiErrorMsg(parsed map[string]any, status int) string {
	if e, ok := parsed["error"].(map[string]any); ok {
		if m, ok := e["message"].(string); ok && m != "" {
			return fmt.Sprintf("HTTP %d — %s", status, m)
		}
	}
	return fmt.Sprintf("HTTP %d", status)
}

// --- headers ---

func orHeaders() map[string]string {
	return map[string]string{
		"Authorization": "Bearer " + getORKey(),
		"Content-Type":  "application/json",
		"HTTP-Referer":  orReferer,
		"X-Title":       orTitle,
	}
}

func kimiHeaders() map[string]string {
	return map[string]string{
		"Authorization": "Bearer " + getKimiKey(),
		"Content-Type":  "application/json",
		"User-Agent":    kimiUA,
	}
}

func glmHeaders() map[string]string {
	return map[string]string{
		"Authorization": "Bearer " + getGLMKey(),
		"Content-Type":  "application/json",
		"User-Agent":    glmUA,
	}
}

// --- Kimi (server.py:_resolve_kimi_model + _chat) ---

func resolveKimiModel(model string, useGeneral bool) (string, error) {
	if model == "" {
		if useGeneral {
			return kimiGenModel, nil
		}
		return kimiCodingModel, nil
	}
	m := strings.TrimPrefix(strings.TrimSpace(model), "moonshotai/")
	if m == kimiCodingModel || strings.HasPrefix(m, "kimi-") {
		return m, nil
	}
	return "", fmt.Errorf("model=%q is not a Kimi-family id. The kimi_* tools only run Kimi "+
		"models on the subscription key (e.g. 'kimi-k2.7', 'kimi-k2.6', 'kimi-for-coding'). "+
		"Use or_ask / glm_ask for other providers", model)
}

type kimiOpts struct {
	maxTokens        int
	includeReasoning bool
	thinking         bool
	useGeneral       bool
	model            string
	timeout          time.Duration
}

func kimiChat(ctx context.Context, messages []map[string]string, o kimiOpts) (string, error) {
	if getKimiKey() == "" {
		return "", fmt.Errorf("Kimi key unavailable — could not read it from 1Password (op://claude/kimi-api-key) or KIMI_API_KEY env")
	}
	chosen, err := resolveKimiModel(o.model, o.useGeneral)
	if err != nil {
		return "", err
	}
	if o.maxTokens == 0 {
		o.maxTokens = defaultMaxTokens
	}
	if o.timeout == 0 {
		o.timeout = 300 * time.Second
	}
	payload := map[string]any{
		"model":      chosen,
		"messages":   messages,
		"max_tokens": o.maxTokens,
		// Kimi only accepts temperature=1 — pinned regardless of caller (server.py note).
		"temperature": 1.0,
	}
	if o.thinking {
		payload["thinking"] = map[string]any{"type": "enabled"}
	}
	parsed, status, err := postChat(ctx, kimiBaseURL, kimiHeaders(), payload, o.timeout)
	if err != nil {
		return "", err
	}
	if status != http.StatusOK {
		return "", fmt.Errorf("%s", apiErrorMsg(parsed, status))
	}
	content, reasoning := extractMessage(parsed)
	return withReasoning(content, reasoning, o.includeReasoning), nil
}

// --- GLM (server.py:_glm_chat) ---

func glmChat(ctx context.Context, messages []map[string]string, maxTokens int, temperature float64, model string, includeReasoning bool) (string, error) {
	if getGLMKey() == "" {
		return "", fmt.Errorf("GLM key unavailable — could not read it from 1Password (op://claude/glm-api-key) or GLM_API_KEY env")
	}
	if model == "" {
		model = glmModel
	}
	if maxTokens == 0 {
		maxTokens = defaultMaxTokens
	}
	payload := map[string]any{
		"model":       model,
		"messages":    messages,
		"max_tokens":  maxTokens,
		"temperature": temperature,
		"stream":      false,
	}
	parsed, status, err := postChat(ctx, glmBaseURL, glmHeaders(), payload, 300*time.Second)
	if err != nil {
		return "", err
	}
	if status != http.StatusOK {
		return "", fmt.Errorf("%s", apiErrorMsg(parsed, status))
	}
	content, reasoning := extractMessage(parsed)
	return withReasoning(content, reasoning, includeReasoning), nil
}

// --- OpenRouter (server.py:_or_chat) — ban + OR-block + ZDR enforced here ---

func orChat(ctx context.Context, messages []map[string]string, model string, maxTokens int, system string, includeReasoning bool) (string, error) {
	if getORKey() == "" {
		return "", fmt.Errorf("OpenRouter key unavailable — could not read it from 1Password (op://claude/openrouter-api-key). Is op signed in?")
	}
	if isBanned(model) && !gptAuditExceptionAllowed(model) {
		return "", fmt.Errorf("model %q is from a banned provider. Edit routing_config.banned_providers in models.json to change this", model)
	}
	if isBlockedFromOR(model) {
		return "", fmt.Errorf("model %q is blocked from OpenRouter. %s", model, blockedFromORReason(model))
	}
	all := make([]map[string]string, 0, len(messages)+1)
	if system != "" {
		all = append(all, map[string]string{"role": "system", "content": system})
	}
	all = append(all, messages...)
	payload := map[string]any{
		"model":       model,
		"messages":    all,
		"max_tokens":  maxTokens,
		"temperature": 0.7,
		// NO-TRAINING ENFORCEMENT — never remove, never caller-overridable.
		"provider": map[string]any{"data_collection": "deny"},
	}
	parsed, status, err := postChat(ctx, orBaseURL, orHeaders(), payload, 180*time.Second)
	if err != nil {
		return "", err
	}
	if status != http.StatusOK {
		return "", fmt.Errorf("OR API error (%s): %s", model, apiErrorMsg(parsed, status))
	}
	content, reasoning := extractMessage(parsed)
	return withReasoning(content, reasoning, includeReasoning), nil
}

// imageGen (server.py:or_image core) — ZDR enforced, POST /images/generations.
func imageGen(ctx context.Context, model, prompt string, n, width, height int) (urls []string, raw map[string]any, err error) {
	payload := map[string]any{
		"model":           model,
		"prompt":          prompt,
		"n":               n,
		"size":            fmt.Sprintf("%dx%d", width, height),
		"response_format": "url",
		"provider":        map[string]any{"data_collection": "deny"},
	}
	cctx, cancel := context.WithTimeout(ctx, 180*time.Second)
	defer cancel()
	body, _ := json.Marshal(payload)
	req, _ := http.NewRequestWithContext(cctx, http.MethodPost, orBaseURL+"/images/generations", bytes.NewReader(body))
	for k, v := range orHeaders() {
		req.Header.Set(k, v)
	}
	resp, e := httpClient.Do(req)
	if e != nil {
		return nil, nil, e
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	_ = json.Unmarshal(data, &raw)
	if resp.StatusCode != http.StatusOK {
		return nil, raw, fmt.Errorf("%s", apiErrorMsg(raw, resp.StatusCode))
	}
	if arr, ok := raw["data"].([]any); ok {
		for _, it := range arr {
			if m, ok := it.(map[string]any); ok {
				if u, ok := m["url"].(string); ok {
					urls = append(urls, u)
				}
			}
		}
	}
	return urls, raw, nil
}

// probeEndpoint — 1-token health check (server.py:_probe_endpoint).
func probeEndpoint(ctx context.Context, baseURL, model string, headers map[string]string, authVar string) string {
	payload := map[string]any{
		"model":      model,
		"messages":   []map[string]string{{"role": "user", "content": "hi"}},
		"max_tokens": 1,
	}
	body, _ := json.Marshal(payload)
	cctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(cctx, http.MethodPost, baseURL+"/chat/completions", bytes.NewReader(body))
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return "ERROR — " + err.Error()
	}
	defer resp.Body.Close()
	switch {
	case resp.StatusCode == 200:
		return "OK ✓"
	case resp.StatusCode == 401 || resp.StatusCode == 403:
		return fmt.Sprintf("HTTP %d (auth error — check %s)", resp.StatusCode, authVar)
	case resp.StatusCode == 404:
		return "HTTP 404 (endpoint not found — check base URL)"
	case resp.StatusCode == 429:
		return "HTTP 429 (rate limited — tools will still work when quota resets)"
	case resp.StatusCode >= 500:
		return fmt.Sprintf("HTTP %d (server error)", resp.StatusCode)
	default:
		return fmt.Sprintf("HTTP %d", resp.StatusCode)
	}
}

// --- parallel fan-out (replaces asyncio.Semaphore + gather) ---

func parallelMap[T, R any](items []T, concurrency int, fn func(i int, item T) R) []R {
	if concurrency < 1 {
		concurrency = 1
	}
	out := make([]R, len(items))
	sem := make(chan struct{}, concurrency)
	var wg sync.WaitGroup
	for i, it := range items {
		wg.Add(1)
		sem <- struct{}{}
		go func(i int, it T) {
			defer wg.Done()
			defer func() { <-sem }()
			out[i] = fn(i, it)
		}(i, it)
	}
	wg.Wait()
	return out
}

// --- overflow-to-file (server.py:_output_or_file) ---

const inlineMaxChars = 8000

func outputOrFile(content, tool string) string {
	if len(content) <= inlineMaxChars {
		return content
	}
	dir := env("AI_ROUTER_FALLBACK_DIR", "/tmp")
	path := fmt.Sprintf("%s/ai-router-%s-%d.md", dir, tool, time.Now().UnixMilli())
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		return truncRunes(content, inlineMaxChars) +
			fmt.Sprintf("\n\n[Output truncated at %d chars; file fallback failed: %v]", inlineMaxChars, err)
	}
	return fmt.Sprintf("[Output too large to return inline; full result written to file]\n\n"+
		"File: %s\nSize: %d chars\n\n"+
		"Read the file with the Read tool to consume the full output.\n\n"+
		"=== Preview (first 1500 chars) ===\n\n%s",
		path, len(content), truncRunes(content, 1500))
}

func truncRunes(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}

func jsonUnmarshalStr(s string, v any) error { return json.Unmarshal([]byte(s), v) }

// jsonIndent marshals with HTML-escaping off (matches Python ensure_ascii=False
// + indent=2 used by the batch/sentiment tools).
func jsonIndent(v any) string {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	if err := enc.Encode(v); err != nil {
		return fmt.Sprintf("%v", v)
	}
	return strings.TrimRight(buf.String(), "\n")
}
