package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

// Version is set at build time via -ldflags.
var Version = "dev"

// AnalyzePayload matches the FastAPI /api/v1/analyze endpoint.
type AnalyzePayload struct {
	Repository string `json:"repository"`
	PRNumber   string `json:"pr_number,omitempty"`
	JobName    string `json:"job_name"`
	BuildURL   string `json:"build_url,omitempty"`
	LogContent string `json:"log_content"`
}

func main() {
	repo := flag.String("repo", "", "Repository (e.g. org/repo) [required]")
	pr := flag.String("pr", "", "Pull request number")
	job := flag.String("job", "unknown-job", "CI job name (Jenkins job / GitHub workflow)")
	buildURL := flag.String("url", "", "URL to the failing build")
	logFile := flag.String("log", "", "Path to the build log file [required]")
	backend := flag.String("backend", "http://localhost:8080/api/v1/analyze", "Tracebow server URL")
	timeout := flag.Duration("timeout", 30*time.Second, "HTTP request timeout")
	version := flag.Bool("version", false, "Print version and exit")

	flag.Parse()

	if *version {
		fmt.Println("tracebow-cli", Version)
		os.Exit(0)
	}

	if *repo == "" || *logFile == "" {
		fmt.Fprintln(os.Stderr, "error: --repo and --log are required")
		fmt.Fprintln(os.Stderr, "usage: tracebow-cli --repo=org/app --log=build.log [--pr=42] [--job=ci] [--url=...] [--backend=...]")
		os.Exit(1)
	}

	logData, err := os.ReadFile(*logFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: cannot read log file %q: %v\n", *logFile, err)
		os.Exit(1)
	}

	payload := AnalyzePayload{
		Repository: *repo,
		PRNumber:   *pr,
		JobName:    *job,
		BuildURL:   *buildURL,
		LogContent: string(logData),
	}

	body, err := json.Marshal(payload)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: json marshal: %v\n", err)
		os.Exit(1)
	}

	fmt.Fprintf(os.Stderr, "tracebow-cli: sending %d bytes of logs for %s to %s\n",
		len(logData), *repo, *backend)

	client := &http.Client{Timeout: *timeout}
	req, err := http.NewRequest(http.MethodPost, *backend, bytes.NewReader(body))
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: failed to reach Tracebow backend: %v\n", err)
		os.Exit(1)
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)

	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		fmt.Fprintf(os.Stderr, "tracebow-cli: accepted (HTTP %d)\n", resp.StatusCode)
		os.Stdout.Write(respBody)
		os.Stdout.Write([]byte("\n"))
	} else {
		fmt.Fprintf(os.Stderr, "error: server returned HTTP %d: %s\n", resp.StatusCode, string(respBody))
		os.Exit(1)
	}
}
