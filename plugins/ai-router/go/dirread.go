package main

// dirread.go — codebase reader for kimi_analyze (server.py:_read_dir + skip sets)
// plus the analysis format helpers.

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

var skipDirs = set(".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
	".next", "target", ".cache", ".idea", ".mypy_cache", ".pytest_cache", "coverage", ".tox", "eggs", "vendor")

var skipExts = set(".lock", ".sum", ".min.js", ".min.css", ".png", ".jpg", ".jpeg", ".gif",
	".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip", ".gz", ".tar", ".pyc",
	".pyo", ".class", ".o", ".a", ".so", ".dylib", ".dll", ".exe", ".bin", ".db", ".sqlite", ".sqlite3")

var textExts = set(".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".rb", ".java", ".c",
	".cpp", ".cc", ".h", ".hpp", ".cs", ".php", ".swift", ".kt", ".scala", ".ml", ".mli", ".ex",
	".exs", ".clj", ".hs", ".elm", ".vue", ".svelte", ".html", ".css", ".scss", ".less", ".md",
	".txt", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf", ".sh", ".fish", ".zsh",
	".bash", ".env.example", ".gitignore", ".dockerignore")

var textNames = set("Dockerfile", "Makefile", "Procfile", "Pipfile", "Gemfile")

func set(xs ...string) map[string]bool {
	m := make(map[string]bool, len(xs))
	for _, x := range xs {
		m[x] = true
	}
	return m
}

func expandHome(p string) string {
	if strings.HasPrefix(p, "~") {
		if home, err := os.UserHomeDir(); err == nil {
			return filepath.Join(home, strings.TrimPrefix(p, "~"))
		}
	}
	return p
}

func readDir(workDir string, maxBytes int) string {
	root, err := filepath.Abs(expandHome(workDir))
	if err != nil {
		return fmt.Sprintf("Error: %q is not a directory", workDir)
	}
	if info, err := os.Stat(root); err != nil || !info.IsDir() {
		return fmt.Sprintf("Error: %q is not a directory", workDir)
	}

	var b strings.Builder
	total, skipped := 0, 0

	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			if path != root && skipDirs[d.Name()] {
				return fs.SkipDir
			}
			return nil
		}
		ext := strings.ToLower(filepath.Ext(d.Name()))
		if skipExts[ext] {
			return nil
		}
		if !textExts[ext] && !textNames[d.Name()] {
			return nil
		}
		data, e := os.ReadFile(path)
		if e != nil {
			skipped++
			return nil
		}
		rel, _ := filepath.Rel(root, path)
		chunk := fmt.Sprintf("### %s\n```\n%s\n```\n\n", rel, string(data))
		if total+len(chunk) > maxBytes {
			fmt.Fprintf(&b, "\n[Truncated after %d bytes — %d files skipped]\n", total, skipped)
			return fs.SkipAll
		}
		b.WriteString(chunk)
		total += len(chunk)
		return nil
	})

	if b.Len() == 0 {
		return fmt.Sprintf("No readable source files found in %q", workDir)
	}
	return b.String()
}

// --- analysis format helpers (server.py:_FORMAT / _AI_CONSUMER) ---

var formatInstr = map[string]string{
	"summary":  "Be extremely concise. Bullet points only. Max ~1500 words. Put critical findings first.",
	"normal":   "Be thorough but structured. Use markdown headers. Max ~6000 words.",
	"detailed": "Include code snippets (≤30 lines each). Full analysis. Max ~20000 words.",
}

const aiConsumer = "IMPORTANT: Your response will be consumed by another AI (Claude) with a limited context window. " +
	"Prioritize information density. No pleasantries. Put the most critical findings first."

func formatFor(level string) string {
	if f, ok := formatInstr[level]; ok {
		return f
	}
	return formatInstr["normal"]
}
