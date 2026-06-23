# ai-router (Go) — build matrix. Cross-compiles 5 static binaries from one host.
BINARY := ai-router
DIST   := dist
# os/arch pairs requested: macOS aarch64, Linux x86_64/aarch64, Windows x86_64/aarch64
TARGETS := darwin/arm64 linux/amd64 linux/arm64 windows/amd64 windows/arm64

.PHONY: build test all dist clean run

build:                ## native build for this host
	go build -o $(BINARY) .

test:
	go test ./...

all: $(TARGETS)       ## cross-compile every target into dist/bin/

$(TARGETS):
	@os=$$(echo $@ | cut -d/ -f1); arch=$$(echo $@ | cut -d/ -f2); \
	ext=""; [ "$$os" = "windows" ] && ext=".exe"; \
	out=$(DIST)/bin/$(BINARY)-$$os-$$arch$$ext; \
	echo "→ $$out"; \
	CGO_ENABLED=0 GOOS=$$os GOARCH=$$arch go build -trimpath -ldflags "-s -w" -o $$out . ; \
	ls -lh $$out

dist: all             ## bundle launcher + all binaries
	cp scripts/ai-router $(DIST)/ai-router
	chmod +x $(DIST)/ai-router
	@echo ""
	@echo "dist/ layout (point .mcp.json command at dist/ai-router):"
	@echo "  dist/ai-router            launcher (selects by uname)"
	@echo "  dist/bin/ai-router-<os>-<arch>[.exe]"

clean:
	rm -rf $(BINARY) $(DIST)
