package main

// tools.go — the full 15-tool MCP surface, ported from server.py.
// Schemas are inferred from the input structs' json/jsonschema tags by the SDK.

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func registerTools(s *mcp.Server) {
	// Kimi subscription (Tier 2)
	add(s, "kimi_ask", "Single-turn query to Kimi (default K2.7; 256K context). model= selects kimi-k2.7|kimi-k2.6|kimi-for-coding.",
		func(ctx context.Context, in KimiAskInput) string { return kimiAsk(ctx, in) })
	add(s, "kimi_analyze", "Analyze a codebase (work_dir) or large text (content) with Kimi. detail_level: summary|normal|detailed.",
		func(ctx context.Context, in KimiAnalyzeInput) string { return kimiAnalyze(ctx, in) })
	add(s, "kimi_batch", "Fan out N prompts to Kimi in parallel. Returns JSON array of {index, ok, result/error}.",
		func(ctx context.Context, in KimiBatchInput) string { return kimiBatch(ctx, in) })
	add(s, "kimi_research_compile", "Two-phase parallel research: extract per source, then synthesize. output_format: structured|narrative|table.",
		func(ctx context.Context, in KimiResearchInput) string { return kimiResearchCompile(ctx, in) })
	add(s, "kimi_sentiment_batch", "Mass parallel sentiment scoring. Returns JSON array with per-text scores.",
		func(ctx context.Context, in KimiSentimentInput) string { return kimiSentimentBatch(ctx, in) })
	add(s, "kimi_swarm", "Kimi native Agent Swarm for long-horizon tasks (Kimi decomposes internally). include_reasoning default true.",
		func(ctx context.Context, in KimiSwarmInput) string { return kimiSwarm(ctx, in) })
	addNoArg(s, "kimi_status", "Check connectivity to the Kimi endpoint + API key presence.",
		func(ctx context.Context) string { return kimiStatus(ctx) })

	// z.ai GLM subscription (Tier 2)
	add(s, "glm_ask", "Single-turn query to z.ai GLM (default glm-5.1). model= overrides (glm-5.1|glm-5|glm-4.7|glm-4.6|...).",
		func(ctx context.Context, in GLMAskInput) string { return glmAsk(ctx, in) })
	addNoArg(s, "glm_status", "Check connectivity to the z.ai GLM endpoint + API key.",
		func(ctx context.Context) string { return glmStatus(ctx) })

	// Sakana Fugu (frontier multi-agent model; per-token paid). NOT ZDR by default — see sakana_status.
	add(s, "sakana_ask", "Single-turn query to Sakana Fugu, a Fable-tier multi-agent frontier model (default fugu; model=fugu-ultra for hard multi-step reasoning, 272K ctx). effort=high|xhigh. WARNING: trains on prompts unless you opted out in the Sakana console — run sakana_status.",
		func(ctx context.Context, in SakanaAskInput) string { return sakanaAsk(ctx, in) })
	addNoArg(s, "sakana_status", "Check Sakana Fugu connectivity + API key, and the training/no-training opt-out state.",
		func(ctx context.Context) string { return sakanaStatus(ctx) })

	// Exa (web search / retrieval; per-token paid)
	add(s, "exa_search", "Web search via Exa. type=auto|fast|instant|deep-lite|deep|deep-reasoning. Returns ranked results with highlights (or text). Pass output_schema (JSON) for grounded structured synthesis.",
		func(ctx context.Context, in ExaSearchInput) string { return exaSearch(ctx, in) })
	add(s, "exa_answer", "Grounded answer to a question via Exa /answer, with source citations. Use for question-first lookups; use exa_search when you need to inspect raw results.",
		func(ctx context.Context, in ExaAnswerInput) string { return exaAnswer(ctx, in) })
	add(s, "exa_contents", "Extract clean parsed content (highlights or text) for URLs you already have, via Exa /contents.",
		func(ctx context.Context, in ExaContentsInput) string { return exaContents(ctx, in) })
	addNoArg(s, "exa_status", "Check connectivity to the Exa search API + API key.",
		func(ctx context.Context) string { return exaStatus(ctx) })

	// OpenRouter (Tier 3, per-token)
	add(s, "or_ask", "Route a single-turn query to the best model via OpenRouter. model:auto|id, profile:eco|mid|intel|max|research.",
		func(ctx context.Context, in OrAskInput) string { return orAsk(ctx, in) })
	add(s, "or_swarm", "Route a complex multi-step task via OpenRouter (defaults to deepseek-v4-pro). Prefer kimi_swarm when Kimi available.",
		func(ctx context.Context, in OrSwarmInput) string { return orSwarm(ctx, in) })
	add(s, "or_image", "Generate images via OpenRouter. use_case: thumbnail_text|thumbnail_cinematic|storyboard|bulk|auto. ZDR enforced.",
		func(ctx context.Context, in OrImageInput) string { return orImage(ctx, in) })
	add(s, "or_compare", "Run one prompt against multiple OR models in parallel, side-by-side. Subscription/banned models filtered out.",
		func(ctx context.Context, in OrCompareInput) string { return orCompare(ctx, in) })
	addNoArg(s, "or_status", "Check routing tier status, API keys, model catalog, and ZDR policy.",
		func(ctx context.Context) string { return orStatus(ctx) })
	add(s, "or_profile", "Show routing profiles. No arg: list all 5. With profile=: per-domain routing detail.",
		func(ctx context.Context, in OrProfileInput) string { return orProfile(ctx, in) })
}

// add registers a tool whose handler takes a typed input struct and returns text.
func add[In any](s *mcp.Server, name, desc string, h func(context.Context, In) string) {
	mcp.AddTool(s, &mcp.Tool{Name: name, Description: desc},
		func(ctx context.Context, _ *mcp.CallToolRequest, in In) (*mcp.CallToolResult, any, error) {
			return text(h(ctx, in)), nil, nil
		})
}

// addNoArg registers a tool with no arguments.
func addNoArg(s *mcp.Server, name, desc string, h func(context.Context) string) {
	mcp.AddTool(s, &mcp.Tool{Name: name, Description: desc},
		func(ctx context.Context, _ *mcp.CallToolRequest, _ NoArgs) (*mcp.CallToolResult, any, error) {
			return text(h(ctx)), nil, nil
		})
}

func text(s string) *mcp.CallToolResult {
	return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: s}}}
}

// =========================================================================
// Input schemas
// =========================================================================

type NoArgs struct{}

type KimiAskInput struct {
	Prompt           string `json:"prompt" jsonschema:"the prompt to send"`
	System           string `json:"system,omitempty"`
	MaxTokens        int    `json:"max_tokens,omitempty" jsonschema:"default 65536"`
	IncludeReasoning bool   `json:"include_reasoning,omitempty"`
	Model            string `json:"model,omitempty" jsonschema:"kimi-k2.7|kimi-k2.6|kimi-for-coding"`
}

type KimiAnalyzeInput struct {
	Question         string `json:"question" jsonschema:"the analysis question/task"`
	WorkDir          string `json:"work_dir,omitempty" jsonschema:"directory to auto-read source from"`
	Content          string `json:"content,omitempty" jsonschema:"raw text to analyze (alternative to work_dir)"`
	DetailLevel      string `json:"detail_level,omitempty" jsonschema:"summary|normal|detailed"`
	MaxTokens        int    `json:"max_tokens,omitempty"`
	IncludeReasoning bool   `json:"include_reasoning,omitempty"`
}

type KimiBatchInput struct {
	Prompts     []string `json:"prompts" jsonschema:"independent prompts to run in parallel"`
	System      string   `json:"system,omitempty"`
	MaxTokens   int      `json:"max_tokens,omitempty" jsonschema:"per-item, default 8192"`
	Concurrency int      `json:"concurrency,omitempty" jsonschema:"max simultaneous requests, default 8"`
}

type KimiResearchInput struct {
	Sources         []string `json:"sources" jsonschema:"raw text sources"`
	SynthesisPrompt string   `json:"synthesis_prompt" jsonschema:"the synthesis goal"`
	OutputFormat    string   `json:"output_format,omitempty" jsonschema:"structured|narrative|table"`
	MaxTokens       int      `json:"max_tokens,omitempty"`
	Concurrency     int      `json:"concurrency,omitempty"`
}

type KimiSentimentInput struct {
	Texts       []string `json:"texts" jsonschema:"texts to score"`
	Context     string   `json:"context,omitempty"`
	Dimensions  string   `json:"dimensions,omitempty" jsonschema:"comma-separated, default positive,negative,neutral,confidence"`
	Concurrency int      `json:"concurrency,omitempty"`
}

type KimiSwarmInput struct {
	Task             string `json:"task" jsonschema:"the long-horizon task"`
	Context          string `json:"context,omitempty"`
	MaxTokens        int    `json:"max_tokens,omitempty"`
	IncludeReasoning *bool  `json:"include_reasoning,omitempty" jsonschema:"default true"`
	Model            string `json:"model,omitempty"`
}

type GLMAskInput struct {
	Prompt           string  `json:"prompt"`
	System           string  `json:"system,omitempty"`
	MaxTokens        int     `json:"max_tokens,omitempty"`
	Temperature      float64 `json:"temperature,omitempty"`
	Model            string  `json:"model,omitempty"`
	IncludeReasoning bool    `json:"include_reasoning,omitempty"`
}

type SakanaAskInput struct {
	Prompt           string  `json:"prompt" jsonschema:"the prompt to send"`
	System           string  `json:"system,omitempty"`
	MaxTokens        int     `json:"max_tokens,omitempty" jsonschema:"default 16384"`
	Temperature      float64 `json:"temperature,omitempty" jsonschema:"default 0.7"`
	Model            string  `json:"model,omitempty" jsonschema:"fugu (default) | fugu-ultra"`
	Effort           string  `json:"effort,omitempty" jsonschema:"reasoning effort: high|xhigh (also max). Omit for the model default."`
	IncludeReasoning bool    `json:"include_reasoning,omitempty"`
}

type ExaSearchInput struct {
	Query          string   `json:"query" jsonschema:"the search query"`
	Type           string   `json:"type,omitempty" jsonschema:"auto|fast|instant|deep-lite|deep|deep-reasoning (default auto)"`
	NumResults     int      `json:"num_results,omitempty" jsonschema:"1-100, default 10"`
	Text           bool     `json:"text,omitempty" jsonschema:"return full page text instead of just highlights"`
	MaxCharacters  int      `json:"max_characters,omitempty" jsonschema:"cap on per-result text length when text=true (default 8000)"`
	IncludeDomains []string `json:"include_domains,omitempty"`
	ExcludeDomains []string `json:"exclude_domains,omitempty"`
	Category       string   `json:"category,omitempty" jsonschema:"company|people|research paper|news|personal site|financial report"`
	SystemPrompt   string   `json:"system_prompt,omitempty" jsonschema:"synthesis/source-preference instructions (use with output_schema)"`
	OutputSchema   string   `json:"output_schema,omitempty" jsonschema:"a JSON-schema string; when set, Exa returns grounded structured synthesis in output.content"`
}

type ExaAnswerInput struct {
	Query string `json:"query" jsonschema:"the question to answer"`
	Text  bool   `json:"text,omitempty" jsonschema:"include full source text in the citations"`
}

type ExaContentsInput struct {
	Urls          []string `json:"urls" jsonschema:"URLs to fetch clean content for"`
	Text          bool     `json:"text,omitempty" jsonschema:"return full text instead of highlights"`
	MaxCharacters int      `json:"max_characters,omitempty" jsonschema:"cap on per-URL text length when text=true (default 8000)"`
}

type OrAskInput struct {
	Prompt            string `json:"prompt" jsonschema:"the prompt to send"`
	Model             string `json:"model,omitempty" jsonschema:"'auto' or a specific OR model id"`
	TaskHint          string `json:"task_hint,omitempty"`
	Profile           string `json:"profile,omitempty" jsonschema:"eco|mid|intel|max|research"`
	MaxTokens         int    `json:"max_tokens,omitempty"`
	System            string `json:"system,omitempty"`
	HostTokenPressure bool   `json:"host_token_pressure,omitempty"`
}

type OrSwarmInput struct {
	Task              string `json:"task"`
	Model             string `json:"model,omitempty"`
	TaskHint          string `json:"task_hint,omitempty"`
	MaxTokens         int    `json:"max_tokens,omitempty"`
	System            string `json:"system,omitempty"`
	IncludeReasoning  *bool  `json:"include_reasoning,omitempty" jsonschema:"default true"`
	HostTokenPressure bool   `json:"host_token_pressure,omitempty"`
}

type OrImageInput struct {
	Prompt  string `json:"prompt"`
	UseCase string `json:"use_case,omitempty" jsonschema:"thumbnail_text|thumbnail_cinematic|thumbnail_photo|storyboard|bulk|auto"`
	Model   string `json:"model,omitempty"`
	Width   int    `json:"width,omitempty" jsonschema:"default 1792"`
	Height  int    `json:"height,omitempty" jsonschema:"default 1024"`
	N       int    `json:"n,omitempty" jsonschema:"default 1"`
}

type OrCompareInput struct {
	Prompt    string   `json:"prompt"`
	Models    []string `json:"models,omitempty"`
	System    string   `json:"system,omitempty"`
	MaxTokens int      `json:"max_tokens,omitempty"`
}

type OrProfileInput struct {
	Profile string `json:"profile,omitempty" jsonschema:"eco|mid|intel|max|research; empty lists all"`
}

func msgs(system, prompt string) []map[string]string {
	m := []map[string]string{}
	if system != "" {
		m = append(m, map[string]string{"role": "system", "content": system})
	}
	return append(m, map[string]string{"role": "user", "content": prompt})
}

// =========================================================================
// Kimi tools
// =========================================================================

func kimiAsk(ctx context.Context, in KimiAskInput) string {
	maxTokens := orDefaultInt(in.MaxTokens, 65536)
	result, err := kimiChat(ctx, msgs(in.System, in.Prompt), kimiOpts{
		maxTokens: maxTokens, includeReasoning: in.IncludeReasoning, useGeneral: true, model: in.Model,
	})
	if err != nil {
		return "Error: " + err.Error()
	}
	return outputOrFile(result, "kimi_ask")
}

func kimiAnalyze(ctx context.Context, in KimiAnalyzeInput) string {
	if in.Content == "" && in.WorkDir == "" {
		return "Error: provide either work_dir (path) or content (text)"
	}
	body := in.Content
	if body == "" {
		body = readDir(in.WorkDir, 900_000)
	}
	if strings.HasPrefix(body, "Error:") {
		return body
	}
	system := fmt.Sprintf("Analyze the following for another AI. %s %s", formatFor(in.DetailLevel), aiConsumer)
	user := fmt.Sprintf("%s\n\n---\n\nQuestion/Task: %s", body, in.Question)
	result, err := kimiChat(ctx, []map[string]string{
		{"role": "system", "content": system},
		{"role": "user", "content": user},
	}, kimiOpts{maxTokens: orDefaultInt(in.MaxTokens, 65536), includeReasoning: in.IncludeReasoning, useGeneral: false})
	if err != nil {
		return "Error: " + err.Error()
	}
	return outputOrFile(result, "kimi_analyze")
}

func kimiBatch(ctx context.Context, in KimiBatchInput) string {
	maxTokens := orDefaultInt(in.MaxTokens, 8192)
	conc := orDefaultInt(in.Concurrency, 8)
	results := parallelMap(in.Prompts, conc, func(i int, p string) map[string]any {
		r, err := kimiChat(ctx, msgs(in.System, p), kimiOpts{maxTokens: maxTokens, useGeneral: true, timeout: 0})
		if err != nil {
			return map[string]any{"index": i, "ok": false, "error": err.Error()}
		}
		return map[string]any{"index": i, "ok": true, "result": r}
	})
	return outputOrFile(jsonIndent(results), "kimi_batch")
}

func kimiResearchCompile(ctx context.Context, in KimiResearchInput) string {
	conc := orDefaultInt(in.Concurrency, 8)
	extracts := parallelMap(in.Sources, conc, func(i int, src string) string {
		r, err := kimiChat(ctx, []map[string]string{
			{"role": "system", "content": fmt.Sprintf(
				"Extract only what is relevant to: %s\nBe concise and structured. Omit irrelevant content.", in.SynthesisPrompt)},
			{"role": "user", "content": src},
		}, kimiOpts{maxTokens: 3072, useGeneral: true})
		if err != nil {
			return fmt.Sprintf("[Extract error for source %d: %v]", i, err)
		}
		return r
	})
	var combined strings.Builder
	for i, e := range extracts {
		if i > 0 {
			combined.WriteString("\n\n---\n\n")
		}
		fmt.Fprintf(&combined, "## Source %d\n%s", i+1, e)
	}
	fmtInstr := map[string]string{
		"structured": "Use markdown headers and bullet points.",
		"narrative":  "Write in flowing prose with clear sections.",
		"table":      "Use markdown tables wherever comparison is useful.",
	}[in.OutputFormat]
	result, err := kimiChat(ctx, []map[string]string{
		{"role": "system", "content": fmt.Sprintf("Synthesize the following research extracts. %s %s", fmtInstr, aiConsumer)},
		{"role": "user", "content": fmt.Sprintf("Goal: %s\n\n%s", in.SynthesisPrompt, combined.String())},
	}, kimiOpts{maxTokens: orDefaultInt(in.MaxTokens, 65536), useGeneral: true})
	if err != nil {
		return "Error: " + err.Error()
	}
	return outputOrFile(result, "kimi_research_compile")
}

func kimiSentimentBatch(ctx context.Context, in KimiSentimentInput) string {
	dimsRaw := in.Dimensions
	if dimsRaw == "" {
		dimsRaw = "positive,negative,neutral,confidence"
	}
	var dims []string
	for _, d := range strings.Split(dimsRaw, ",") {
		if d = strings.TrimSpace(d); d != "" {
			dims = append(dims, fmt.Sprintf("%q: float 0-1", d))
		}
	}
	contextNote := ""
	if in.Context != "" {
		contextNote = " Context: " + in.Context
	}
	system := fmt.Sprintf("Analyze sentiment and return ONLY valid JSON with fields: {%s, \"summary\": \"one sentence\"}. "+
		"No markdown, no explanation.%s", strings.Join(dims, ", "), contextNote)
	conc := orDefaultInt(in.Concurrency, 8)
	results := parallelMap(in.Texts, conc, func(i int, t string) map[string]any {
		raw, err := kimiChat(ctx, []map[string]string{
			{"role": "system", "content": system}, {"role": "user", "content": t},
		}, kimiOpts{maxTokens: 512, useGeneral: true})
		if err != nil {
			return map[string]any{"index": i, "ok": false, "error": err.Error()}
		}
		raw = stripCodeFence(strings.TrimSpace(raw))
		var parsed map[string]any
		if jsonUnmarshalStr(raw, &parsed) == nil {
			parsed["index"] = i
			parsed["ok"] = true
			return parsed
		}
		return map[string]any{"index": i, "ok": true, "raw": raw}
	})
	return outputOrFile(jsonIndent(results), "kimi_sentiment_batch")
}

func kimiSwarm(ctx context.Context, in KimiSwarmInput) string {
	includeReasoning := true
	if in.IncludeReasoning != nil {
		includeReasoning = *in.IncludeReasoning
	}
	m := []map[string]string{}
	if in.Context != "" {
		m = append(m, map[string]string{"role": "system", "content": in.Context})
	}
	m = append(m, map[string]string{"role": "user", "content": in.Task})
	result, err := kimiChat(ctx, m, kimiOpts{
		maxTokens: orDefaultInt(in.MaxTokens, 65536), includeReasoning: includeReasoning,
		thinking: true, useGeneral: true, model: in.Model, timeout: 600_000_000_000, // 600s
	})
	if err != nil {
		return "Error: " + err.Error()
	}
	return outputOrFile(result, "kimi_swarm")
}

func kimiStatus(ctx context.Context) string {
	var b strings.Builder
	keyState := "NOT SET — add op://claude/kimi-api-key or export KIMI_API_KEY"
	if getKimiKey() != "" {
		keyState = "set ✓"
	}
	fmt.Fprintf(&b, "API key : %s\n", keyState)
	fmt.Fprintf(&b, "UA      : %s  (coding-agent gate — see KIMI_USER_AGENT)\n", kimiUA)
	fmt.Fprintf(&b, "Models  : general default=%s, coding=%s\n", kimiGenModel, kimiCodingModel)
	if getKimiKey() == "" {
		return b.String()
	}
	gen := probeEndpoint(ctx, kimiBaseURL, kimiGenModel, kimiHeaders(), "KIMI_API_KEY")
	cod := probeEndpoint(ctx, kimiBaseURL, kimiCodingModel, kimiHeaders(), "KIMI_API_KEY")
	fmt.Fprintf(&b, "\nGeneral (all tools)\n  url   : %s  model=%s\n  status: %s\n", kimiBaseURL, kimiGenModel, gen)
	fmt.Fprintf(&b, "\nCoding (kimi_analyze)\n  url   : %s  model=%s\n  status: %s\n", kimiBaseURL, kimiCodingModel, cod)
	return b.String()
}

// =========================================================================
// GLM tools
// =========================================================================

func glmAsk(ctx context.Context, in GLMAskInput) string {
	temp := in.Temperature
	if temp == 0 {
		temp = 0.7
	}
	result, err := glmChat(ctx, msgs(in.System, in.Prompt), orDefaultInt(in.MaxTokens, 32768), temp, in.Model, in.IncludeReasoning)
	if err != nil {
		return "Error: " + err.Error()
	}
	return outputOrFile(result, "glm_ask")
}

func glmStatus(ctx context.Context) string {
	var b strings.Builder
	keyState := "NOT SET — add op://claude/glm-api-key or export GLM_API_KEY"
	if getGLMKey() != "" {
		keyState = "set ✓ (op://claude/glm-api-key)"
	}
	fmt.Fprintf(&b, "API key : %s\nUA      : %s\n", keyState, glmUA)
	if getGLMKey() == "" {
		return b.String()
	}
	status := probeEndpoint(ctx, glmBaseURL, glmModel, glmHeaders(), "GLM_API_KEY")
	fmt.Fprintf(&b, "\nGLM Coding Plan (glm_ask)\n  url   : %s  model=%s\n  status: %s\n", glmBaseURL, glmModel, status)
	return b.String()
}

// =========================================================================
// Sakana Fugu tools
// =========================================================================

func sakanaAsk(ctx context.Context, in SakanaAskInput) string {
	temp := in.Temperature
	if temp == 0 {
		temp = 0.7
	}
	result, err := sakanaChat(ctx, msgs(in.System, in.Prompt), orDefaultInt(in.MaxTokens, defaultMaxTokens), temp, in.Model, in.Effort, in.IncludeReasoning)
	if err != nil {
		return "Error: " + err.Error()
	}
	model := orDefaultStr(in.Model, sakanaModel)
	return outputOrFile(fmt.Sprintf("[Model: sakana/%s | per-token paid | ZDR: NOT enforced — see sakana_status]\n\n", model)+result, "sakana_ask")
}

func sakanaStatus(ctx context.Context) string {
	var b strings.Builder
	keyState := "NOT SET — add op://claude/sakana-api-key or export SAKANA_API_KEY"
	if getSakanaKey() != "" {
		keyState = "set ✓ (op://claude/sakana-api-key)"
	}
	fmt.Fprintf(&b, "Sakana Fugu (sakana_ask) — Fable-tier multi-agent frontier model\n")
	fmt.Fprintf(&b, "API key : %s\n", keyState)
	b.WriteString(
		"\n!!! NO-TRAINING WARNING !!!\n" +
			"  Sakana TRAINS on API prompts BY DEFAULT. There is no per-call ZDR switch\n" +
			"  (unlike OpenRouter). The no-training guarantee holds ONLY after you flip the\n" +
			"  training opt-out toggle in the console: https://console.sakana.ai (account → privacy).\n" +
			"  Zero-retention is NOT confirmed available. Treat as a non-ZDR route until you opt out.\n")
	fmt.Fprintf(&b, "\nBilling : per-token paid (fugu $1.50/$6.00 per M, fugu-ultra $5.00/$30.00 per M) — NOT a flat-rate sub.\n")
	if getSakanaKey() == "" {
		return b.String()
	}
	status := probeModelsEndpoint(ctx, sakanaBaseURL, sakanaHeaders(), "SAKANA_API_KEY")
	fmt.Fprintf(&b, "\nEndpoint\n  url   : %s  models=fugu, fugu-ultra\n  status: %s (GET /models)\n", sakanaBaseURL, status)
	return b.String()
}

// =========================================================================
// Exa search tools
// =========================================================================

const exaDefaultMaxChars = 8000

// exaContentsObj builds the nested `contents` object for /search.
func exaContentsObj(text bool, maxChars int) map[string]any {
	if text {
		if maxChars == 0 {
			maxChars = exaDefaultMaxChars
		}
		return map[string]any{"text": map[string]any{"maxCharacters": maxChars}}
	}
	return map[string]any{"highlights": true}
}

func exaSearch(ctx context.Context, in ExaSearchInput) string {
	if strings.TrimSpace(in.Query) == "" {
		return "Error: query is required."
	}
	payload := map[string]any{
		"query":      in.Query,
		"type":       orDefaultStr(in.Type, "auto"),
		"numResults": orDefaultInt(in.NumResults, 10),
		"contents":   exaContentsObj(in.Text, in.MaxCharacters),
	}
	if len(in.IncludeDomains) > 0 {
		payload["includeDomains"] = in.IncludeDomains
	}
	if len(in.ExcludeDomains) > 0 {
		payload["excludeDomains"] = in.ExcludeDomains
	}
	if in.Category != "" {
		payload["category"] = in.Category
	}
	if in.SystemPrompt != "" {
		payload["systemPrompt"] = in.SystemPrompt
	}
	if strings.TrimSpace(in.OutputSchema) != "" {
		var schema any
		if err := jsonUnmarshalStr(in.OutputSchema, &schema); err != nil {
			return "Error: output_schema is not valid JSON: " + err.Error()
		}
		payload["outputSchema"] = schema
	}
	parsed, status, err := exaPost(ctx, "/search", payload, 90*time.Second)
	if err != nil {
		return "Error (Exa): " + err.Error()
	}
	if status != 200 {
		return fmt.Sprintf("Exa /search error: %s", apiErrorMsg(parsed, status))
	}
	return outputOrFile(formatExaResponse(parsed, fmt.Sprintf("Exa search · type=%s · %q", payload["type"], in.Query)), "exa_search")
}

func exaAnswer(ctx context.Context, in ExaAnswerInput) string {
	if strings.TrimSpace(in.Query) == "" {
		return "Error: query is required."
	}
	payload := map[string]any{"query": in.Query}
	if in.Text {
		payload["text"] = true
	}
	parsed, status, err := exaPost(ctx, "/answer", payload, 90*time.Second)
	if err != nil {
		return "Error (Exa): " + err.Error()
	}
	if status != 200 {
		return fmt.Sprintf("Exa /answer error: %s", apiErrorMsg(parsed, status))
	}
	var b strings.Builder
	fmt.Fprintf(&b, "## Exa answer · %q\n\n", in.Query)
	if ans, ok := parsed["answer"].(string); ok && ans != "" {
		b.WriteString(ans + "\n")
	} else {
		b.WriteString("_(no answer field in response)_\n")
	}
	if cites, ok := parsed["citations"].([]any); ok && len(cites) > 0 {
		b.WriteString("\n### Citations\n")
		for i, c := range cites {
			m, _ := c.(map[string]any)
			title, _ := m["title"].(string)
			url, _ := m["url"].(string)
			fmt.Fprintf(&b, "%d. [%s](%s)\n", i+1, orDefaultStr(title, url), url)
		}
	}
	return outputOrFile(b.String(), "exa_answer")
}

func exaContents(ctx context.Context, in ExaContentsInput) string {
	if len(in.Urls) == 0 {
		return "Error: at least one url is required."
	}
	payload := map[string]any{"urls": in.Urls}
	for k, v := range exaContentsObj(in.Text, in.MaxCharacters) {
		payload[k] = v // /contents takes these fields top-level, not nested
	}
	parsed, status, err := exaPost(ctx, "/contents", payload, 90*time.Second)
	if err != nil {
		return "Error (Exa): " + err.Error()
	}
	if status != 200 {
		return fmt.Sprintf("Exa /contents error: %s", apiErrorMsg(parsed, status))
	}
	return outputOrFile(formatExaResponse(parsed, fmt.Sprintf("Exa contents · %d URL(s)", len(in.Urls))), "exa_contents")
}

func exaStatus(ctx context.Context) string {
	var b strings.Builder
	keyState := "NOT SET — add op://claude/exa-ai-api-key or export EXA_API_KEY"
	if getExaKey() != "" {
		keyState = "set ✓ (op://claude/exa-ai-api-key)"
	}
	fmt.Fprintf(&b, "Exa search API (exa_search / exa_answer / exa_contents)\n")
	fmt.Fprintf(&b, "API key : %s\nBilling : per-token/credit paid (per-search + per-content)\n", keyState)
	if getExaKey() == "" {
		return b.String()
	}
	parsed, status, err := exaPost(ctx, "/search", map[string]any{"query": "ping", "type": "instant", "numResults": 1}, 15*time.Second)
	statusLine := "OK ✓"
	switch {
	case err != nil:
		statusLine = "ERROR — " + err.Error()
	case status == 401 || status == 403:
		statusLine = fmt.Sprintf("HTTP %d (auth error — check the Exa key)", status)
	case status != 200:
		statusLine = fmt.Sprintf("HTTP %d — %s", status, apiErrorMsg(parsed, status))
	}
	fmt.Fprintf(&b, "\nEndpoint\n  url   : %s/search\n  status: %s\n", exaBaseURL, statusLine)
	return b.String()
}

// formatExaResponse renders an Exa /search or /contents JSON response as markdown:
// the results list plus any grounded outputSchema synthesis.
func formatExaResponse(parsed map[string]any, header string) string {
	var b strings.Builder
	b.WriteString("## " + header + "\n")
	if cd, ok := parsed["costDollars"].(map[string]any); ok {
		if total, ok := cd["total"].(float64); ok {
			fmt.Fprintf(&b, "_cost: $%.4f_\n", total)
		}
	}
	results, _ := parsed["results"].([]any)
	if len(results) == 0 {
		b.WriteString("\n_(no results)_\n")
	}
	for i, r := range results {
		m, _ := r.(map[string]any)
		title, _ := m["title"].(string)
		url, _ := m["url"].(string)
		fmt.Fprintf(&b, "\n### %d. %s\n%s\n", i+1, orDefaultStr(title, "(untitled)"), url)
		if pd, _ := m["publishedDate"].(string); pd != "" {
			fmt.Fprintf(&b, "_published: %s_\n", pd)
		}
		if hs, ok := m["highlights"].([]any); ok && len(hs) > 0 {
			for _, h := range hs {
				if s, ok := h.(string); ok {
					fmt.Fprintf(&b, "> %s\n", strings.ReplaceAll(strings.TrimSpace(s), "\n", " "))
				}
			}
		}
		if s, _ := m["summary"].(string); s != "" {
			fmt.Fprintf(&b, "%s\n", s)
		}
		if t, _ := m["text"].(string); t != "" {
			fmt.Fprintf(&b, "\n%s\n", t)
		}
	}
	if out, ok := parsed["output"].(map[string]any); ok {
		b.WriteString("\n---\n### Synthesized output\n")
		switch c := out["content"].(type) {
		case string:
			b.WriteString(c + "\n")
		default:
			b.WriteString("```json\n" + jsonIndent(out["content"]) + "\n```\n")
		}
		if g, ok := out["grounding"].([]any); ok && len(g) > 0 {
			fmt.Fprintf(&b, "\n_%d grounded field(s) with citations._\n", len(g))
		}
	}
	return b.String()
}

// =========================================================================
// OpenRouter tools
// =========================================================================

func orAsk(ctx context.Context, in OrAskInput) string {
	model := orDefaultStr(in.Model, "auto")
	maxTokens := orDefaultInt(in.MaxTokens, 32768)
	hasKimi := getKimiKey() != ""

	if model == "auto" && in.TaskHint != "" && in.Profile == "" && shouldRedirectToHost(in.TaskHint, in.HostTokenPressure) {
		return hostRedirectMsg(in.TaskHint)
	}
	if in.TaskHint != "" && containsAny(strings.ToLower(in.TaskHint), []string{"image", "visual", "thumbnail", "picture"}) {
		return "Use `or_image` for image generation tasks. It routes to Flux 1.1 Pro, Ideogram V2, Flux Schnell, or SDXL based on your use case."
	}

	profileNote := ""
	if model == "auto" && in.Profile != "" {
		resolved, note := resolveProfileModel(in.Profile, in.TaskHint, hasKimi)
		profileNote = note
		if resolved == profileUseKimi {
			r, err := kimiChat(ctx, msgs(in.System, in.Prompt), kimiOpts{maxTokens: maxTokens, useGeneral: true})
			if err != nil {
				return "Error (Kimi): " + err.Error()
			}
			return outputOrFile(note+"\n[Routed to Kimi subscription — no marginal $, overrides profile]\n\n"+r, "or_ask")
		}
		if resolved != "" {
			model = resolved
		}
	}

	showCreativeAlts := false
	if model == "auto" {
		if in.TaskHint == "" {
			return buildAlternativesTable("")
		}
		routed, matched := routeORModel(in.TaskHint, hasKimi)
		if !matched {
			return buildAlternativesTable("")
		}
		if routed == routeKimi {
			r, err := kimiChat(ctx, msgs(in.System, in.Prompt), kimiOpts{maxTokens: maxTokens, useGeneral: true})
			if err != nil {
				return "Error (Kimi): " + err.Error()
			}
			return outputOrFile("[Routed to Kimi subscription — no marginal $]\n\n"+r, "or_ask")
		}
		if isAmbiguousCreative(in.TaskHint) {
			showCreativeAlts = true
		}
		model = routed
	}

	if getORKey() == "" {
		return "OpenRouter key unavailable — could not read it from 1Password (op://claude/openrouter-api-key). Is op signed in?\nWould have used model: " + model
	}
	result, err := orChat(ctx, []map[string]string{{"role": "user", "content": in.Prompt}}, model, maxTokens, in.System, false)
	if err != nil {
		return "Error (" + model + "): " + err.Error()
	}
	header := fmt.Sprintf("[Model: %s | ZDR: enforced]\n\n", model)
	if profileNote != "" {
		header = profileNote + "\n" + header
	}
	if showCreativeAlts {
		return outputOrFile(header+result+buildCreativeAlternativesTable(model, modelName(model), in.TaskHint), "or_ask")
	}
	return outputOrFile(header+result, "or_ask")
}

func orSwarm(ctx context.Context, in OrSwarmInput) string {
	model := orDefaultStr(in.Model, "auto")
	maxTokens := orDefaultInt(in.MaxTokens, 65536)
	includeReasoning := true
	if in.IncludeReasoning != nil {
		includeReasoning = *in.IncludeReasoning
	}
	hasKimi := getKimiKey() != ""

	if model == "auto" && in.TaskHint != "" && shouldRedirectToHost(in.TaskHint, in.HostTokenPressure) {
		return hostRedirectMsg(in.TaskHint)
	}
	showCreativeAlts := false
	if model == "auto" {
		if in.TaskHint == "" {
			model = "deepseek/deepseek-v4-pro"
		} else {
			routed, matched := routeORModel(in.TaskHint, hasKimi)
			switch {
			case !matched:
				model = "deepseek/deepseek-v4-pro"
			case routed == routeKimi:
				m := []map[string]string{}
				if in.System != "" {
					m = append(m, map[string]string{"role": "system", "content": in.System})
				}
				m = append(m, map[string]string{"role": "user", "content": in.Task})
				r, err := kimiChat(ctx, m, kimiOpts{maxTokens: maxTokens, includeReasoning: includeReasoning, thinking: true, useGeneral: true})
				if err != nil {
					return "Error (Kimi swarm): " + err.Error()
				}
				return outputOrFile("[Routed to Kimi subscription (kimi_swarm) — no marginal $]\n\n"+r, "or_swarm")
			default:
				if isAmbiguousCreative(in.TaskHint) {
					showCreativeAlts = true
				}
				model = routed
			}
		}
	}

	if getORKey() == "" {
		return "OpenRouter key unavailable — could not read it from 1Password (op://claude/openrouter-api-key). Is op signed in?\nWould have used model: " + model
	}
	result, err := orChat(ctx, []map[string]string{{"role": "user", "content": in.Task}}, model, maxTokens, in.System, includeReasoning)
	if err != nil {
		return "Error (" + model + "): " + err.Error()
	}
	header := fmt.Sprintf("[Model: %s | ZDR: enforced]\n\n", model)
	if showCreativeAlts {
		return outputOrFile(header+result+buildCreativeAlternativesTable(model, modelName(model), in.TaskHint), "or_swarm")
	}
	return outputOrFile(header+result, "or_swarm")
}

var imageModelMap = map[string]string{
	"thumbnail_text":      "ideogram/ideogram-v2",
	"thumbnail_cinematic": "black-forest-labs/flux-1.1-pro",
	"thumbnail_photo":     "black-forest-labs/flux-1.1-pro", // DALL-E 3 banned
	"storyboard":          "black-forest-labs/flux-1-schnell",
	"bulk":                "stability/stable-diffusion-xl",
}

var imageCosts = map[string]float64{
	"black-forest-labs/flux-1.1-pro":   0.04,
	"black-forest-labs/flux-1-schnell": 0.002,
	"ideogram/ideogram-v2":             0.08,
	"stability/stable-diffusion-xl":    0.002,
}

func orImage(ctx context.Context, in OrImageInput) string {
	if getORKey() == "" {
		return "OpenRouter key unavailable — could not read it from 1Password (op://claude/openrouter-api-key). Is op signed in?"
	}
	useCase := orDefaultStr(in.UseCase, "auto")
	model := orDefaultStr(in.Model, "auto")
	width := orDefaultInt(in.Width, 1792)
	height := orDefaultInt(in.Height, 1024)
	n := orDefaultInt(in.N, 1)

	if model == "auto" {
		if useCase != "auto" && imageModelMap[useCase] != "" {
			model = imageModelMap[useCase]
		} else {
			pl := strings.ToLower(in.Prompt)
			switch {
			case containsAny(pl, []string{"text", "title", "logo", "typography", "headline", "label"}):
				model, useCase = "ideogram/ideogram-v2", "thumbnail_text"
			case containsAny(pl, []string{"storyboard", "sketch", "rough", "concept", "draft"}):
				model, useCase = "black-forest-labs/flux-1-schnell", "storyboard"
			default:
				model, useCase = "black-forest-labs/flux-1.1-pro", "thumbnail_cinematic"
			}
		}
	}
	costPer, ok := imageCosts[model]
	if !ok {
		costPer = 0.05
	}
	urls, raw, err := imageGen(ctx, model, in.Prompt, n, width, height)
	if err != nil {
		return fmt.Sprintf("OR image API error (%s): %v", model, err)
	}
	var b strings.Builder
	fmt.Fprintf(&b, "[Model: %s | use_case: %s | ZDR: enforced | est. cost: $%.3f]\n\n", model, useCase, costPer*float64(n))
	for i, u := range urls {
		fmt.Fprintf(&b, "Image %d: %s\n", i+1, u)
	}
	if len(urls) == 0 {
		fmt.Fprintf(&b, "No image URLs returned. Check OR response format.\nRaw response: %s", truncRunes(jsonIndent(raw), 500))
	}
	return b.String()
}

func orCompare(ctx context.Context, in OrCompareInput) string {
	if getORKey() == "" {
		return "OpenRouter key unavailable — could not read it from 1Password (op://claude/openrouter-api-key). Is op signed in?"
	}
	models := in.Models
	if len(models) == 0 {
		models = []string{"minimax/minimax-m2.7", "deepseek/deepseek-v4-pro", "xiaomi/mimo-v2.5-pro"}
	}
	var kept, rejected []string
	for _, m := range models {
		if isBlockedFromOR(m) || isBanned(m) {
			rejected = append(rejected, m)
		} else {
			kept = append(kept, m)
		}
	}
	blockNote := ""
	if len(rejected) > 0 {
		blockNote = "⚠️  Removed blocked/banned models: " + strings.Join(rejected, ", ") + "\n\n"
	}
	if len(kept) == 0 {
		return "All requested models are blocked or banned. No OR comparison run."
	}
	maxTokens := orDefaultInt(in.MaxTokens, 8192)

	type res struct{ model, body string }
	results := parallelMap(kept, len(kept), func(_ int, m string) res {
		r, err := orChat(ctx, []map[string]string{{"role": "user", "content": in.Prompt}}, m, maxTokens, in.System, false)
		if err != nil {
			return res{m, "[ERROR] " + err.Error()}
		}
		return res{m, r}
	})

	preview := in.Prompt
	if len(preview) > 80 {
		preview = preview[:80] + "..."
	}
	var b strings.Builder
	fmt.Fprintf(&b, "## Model Comparison — %q\n\nZDR: enforced on all %d calls | Ran in parallel\n\n", preview, len(kept))
	for _, r := range results {
		fmt.Fprintf(&b, "### %s (%s)\n\n%s\n\n", r.model, estCost(r.model, maxTokens), r.body)
	}
	b.WriteString("---\nRe-call with `or_ask(model=\"<id>\", ...)` to use your preferred result's model.")
	return outputOrFile(blockNote+b.String(), "or_compare")
}

func orStatus(ctx context.Context) string {
	var b strings.Builder
	rc := catalog.Routing
	fmt.Fprintf(&b, "## Three-Tier Model Routing Status\n\n")
	fmt.Fprintf(&b, "### Tier 1 — Host-Native (flat-rate sub; no marginal $)\n")
	fmt.Fprintf(&b, "  Blocked from OR : prefixes %v\n", rc.Tier1.Prefixes)
	if rc.Tier1.Note != "" {
		fmt.Fprintf(&b, "  Note            : %s\n", rc.Tier1.Note)
	}
	fmt.Fprintf(&b, "\n### Tier 2 — Subscription API (flat-rate; no marginal $)\n")
	for _, e := range rc.Tier2.Entries {
		keyState := "NOT SET"
		switch e.Provider {
		case "moonshotai":
			if getKimiKey() != "" {
				keyState = "set ✓"
			}
		case "zai":
			if getGLMKey() != "" {
				keyState = "set ✓"
			}
		case "sakana":
			if getSakanaKey() != "" {
				keyState = "set ✓ (per-token; NOT ZDR by default — see sakana_status)"
			}
		case "exa":
			if getExaKey() != "" {
				keyState = "set ✓ (search API, per-token)"
			}
		}
		fmt.Fprintf(&b, "  %s (%s*)\n    API key  : %s\n    MCP tools: %s\n",
			e.Provider, e.Prefix, keyState, strings.Join(e.MCPTools, ", "))
	}
	fmt.Fprintf(&b, "\n### Tier 3 — OpenRouter (per-token; ZDR enforced)\n")
	orState := "NOT SET — could not read op://claude/openrouter-api-key (op signed in?)"
	if getORKey() != "" {
		orState = "set ✓ (op://claude/openrouter-api-key)"
	}
	fmt.Fprintf(&b, "  API key : %s\n", orState)
	fmt.Fprintf(&b, "  ZDR     : enforced via provider.data_collection=deny on ALL OR calls\n")
	fmt.Fprintf(&b, "  Catalog : %d text + %d image models\n", len(catalog.ORModels), len(catalog.ImageModels))
	fmt.Fprintf(&b, "  Version : %s (updated %s)\n", catalog.Version, catalog.Updated)
	fmt.Fprintf(&b, "\n### Active Blocked Prefixes (never routed via OR)\n  %v\n", orBlockedPrefixes)
	fmt.Fprintf(&b, "  Banned providers: %v\n", bannedPrefixes)
	return b.String()
}

func orProfile(_ context.Context, in OrProfileInput) string {
	if in.Profile == "" {
		return profileListView()
	}
	return profileDetailView(strings.ToLower(strings.TrimSpace(in.Profile)))
}

func profileListView() string {
	order := []string{"eco", "mid", "intel", "max", "research"}
	desc := map[string]string{
		"eco": "Fast cheap tasks, high volume, prototyping", "mid": "Balanced quality/cost, 1M context",
		"intel": "Reasoning, math, code analysis (80.6% SWE-bench)", "max": "Strongest general quality, no budget constraint",
		"research": "Long-doc synthesis, 1.05M context window",
	}
	var rows []string
	for _, p := range order {
		mid := profileDefaultModels[p]
		cost := "see OR"
		if m, ok := catalogByID[mid]; ok {
			cost = fmt.Sprintf("$%.2f/M", m.InputCostPerM)
		}
		rows = append(rows, fmt.Sprintf("| %-8s | %-36s | %-8s | %s |", p, mid, cost, desc[p]))
	}
	return "## Available Profiles\n\n| Profile  | Primary Model                        | Cost (in) | Best For |\n|---|---|---|---|\n" +
		strings.Join(rows, "\n") +
		"\n\n**Subscription overrides (always win, no marginal $):** Kimi for coding/analysis; host Claude for reasoning/Q&A/math when not token-pressured.\n" +
		"**Specialist overrides:** creative/story/fiction → minimax/minimax-m2.7.\n\n" +
		"**Usage:** `or_ask(prompt=\"...\", profile=\"eco\")` · `or_profile(profile=\"max\")` for domain detail."
}

func profileDetailView(profile string) string {
	valid := map[string]bool{"eco": true, "mid": true, "intel": true, "max": true, "research": true}
	if !valid[profile] {
		return fmt.Sprintf("Unknown profile: %q. Valid: eco, intel, max, mid, research\nCall or_profile() with no argument to list all.", profile)
	}
	def := profileDefaultModels[profile]
	modelCost := func(id string) string {
		if strings.HasPrefix(id, "subscription:") {
			return "sub (no marginal $)"
		}
		if m, ok := catalogByID[id]; ok {
			return fmt.Sprintf("$%.3f/M", m.InputCostPerM)
		}
		return "see OR"
	}
	reasoningModel := def
	if profile == "intel" || profile == "research" || profile == "max" {
		reasoningModel = "deepseek/deepseek-v4-pro"
	}
	analysisModel := "subscription:kimi"
	if profile == "research" {
		analysisModel = "subscription:kimi_analyze"
	}
	fastModel := def
	if profile == "eco" {
		fastModel = "deepseek/deepseek-v4-flash"
	}
	reasoningRationale := "profile reasoning"
	if profile == "max" {
		reasoningRationale = "max reasoning → DeepSeek V4 Pro (80.6% SWE-bench at lower cost than mimo)"
	}
	domains := [][3]string{
		{"general (no hint)", def, "profile default"},
		{"coding / debug / refactor", "subscription:kimi", "Kimi subscription always wins (no marginal $)"},
		{"analysis / codebase", analysisModel, "Kimi subscription always wins (no marginal $)"},
		{"reasoning / math / proof", reasoningModel, reasoningRationale},
		{"creative / story / fiction", "minimax/minimax-m2.7", "specialist override"},
		{"ultra long context (>262K)", "deepseek/deepseek-v4-pro", "1.05M ctx"},
		{"fast / cheap / batch", fastModel, "eco uses flash; others use profile default"},
	}
	var rows []string
	for _, d := range domains {
		rows = append(rows, fmt.Sprintf("| %s | %s | %s | %s |", d[0], strings.TrimPrefix(d[1], "subscription:"), modelCost(d[1]), d[2]))
	}
	p, _ := getProfile(profile)
	out := fmt.Sprintf("## Profile: %s\n\n**Description:** %s\n**Cost target:** %s\n**Primary model:** `%s`\n**Fallback model:** `%s`\n",
		profile, p.Description, p.CostTarget, orDefaultStr(p.PrimaryModel, def), p.FallbackModel)
	if p.Note != "" {
		out += "**Note:** " + p.Note + "\n"
	}
	out += fmt.Sprintf("\n### Domain Routing for profile=%q\n\n| Domain / task_hint | Model Used | Cost (in) | Rationale |\n|---|---|---|---|\n%s\n\n"+
		"**Activate:** `or_ask(prompt=\"...\", profile=\"%s\")`", profile, strings.Join(rows, "\n"), profile)
	return out
}

// =========================================================================
// shared helpers
// =========================================================================

func hostRedirectMsg(taskHint string) string {
	return fmt.Sprintf("## Use Your Own Models\n\nYou (Claude Code) have a Max subscription with Opus/Sonnet/Haiku natively. "+
		"This task — `%s` — is within your native capability. Handle it directly without calling this MCP.\n\n"+
		"Re-call with `host_token_pressure=true` if you are actually token-constrained.", taskHint)
}

func modelName(id string) string {
	if m, ok := catalogByID[id]; ok {
		return m.Name
	}
	return lastSeg(id)
}

func estCost(id string, maxTokens int) string {
	m, ok := catalogByID[id]
	if !ok {
		return "cost unknown"
	}
	return fmt.Sprintf("~$%.4f/req est.", m.OutputCostPerM*float64(maxTokens)/1_000_000)
}

func stripCodeFence(s string) string {
	if !strings.HasPrefix(s, "```") {
		return s
	}
	if i := strings.Index(s, "\n"); i >= 0 {
		s = s[i+1:]
	}
	if i := strings.LastIndex(s, "```"); i >= 0 {
		s = s[:i]
	}
	return strings.TrimSpace(s)
}

func orDefaultInt(v, def int) int {
	if v == 0 {
		return def
	}
	return v
}

func orDefaultStr(v, def string) string {
	if v == "" {
		return def
	}
	return v
}
