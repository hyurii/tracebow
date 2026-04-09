APP     := tracebow-cli
VERSION := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
LDFLAGS := -s -w -X main.Version=$(VERSION)
OUT     := dist

.PHONY: all clean linux-amd64 darwin-arm64 darwin-amd64 windows-amd64

all: linux-amd64 darwin-arm64 darwin-amd64 windows-amd64

linux-amd64:
	GOOS=linux GOARCH=amd64 go build -ldflags "$(LDFLAGS)" -o $(OUT)/$(APP)-linux-amd64 .

darwin-arm64:
	GOOS=darwin GOARCH=arm64 go build -ldflags "$(LDFLAGS)" -o $(OUT)/$(APP)-darwin-arm64 .

darwin-amd64:
	GOOS=darwin GOARCH=amd64 go build -ldflags "$(LDFLAGS)" -o $(OUT)/$(APP)-darwin-amd64 .

windows-amd64:
	GOOS=windows GOARCH=amd64 go build -ldflags "$(LDFLAGS)" -o $(OUT)/$(APP)-windows-amd64.exe .

clean:
	rm -rf $(OUT)
