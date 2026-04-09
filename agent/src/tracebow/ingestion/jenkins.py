"""Jenkins log ingestion pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tracebow.ingestion.base import ChunkMetadata, IngestionPipeline, RawDocument

if TYPE_CHECKING:
    from tracebow.services.embeddings import EmbeddingService


@dataclass
class JenkinsLogChunk(RawDocument):
    """Jenkins console output chunk with build context."""

    job_name: str
    build_number: int
    git_commit: str | None
    workspace_path: str | None
    failure_signature: str | None


class JenkinsIngestionPipeline(IngestionPipeline[JenkinsLogChunk]):
    """Ingests Jenkins console output, filters noise, extracts anomaly clusters."""

    # Patterns for boilerplate noise to filter
    NOISE_PATTERNS = [
        r"\[Pipeline\]\s*(?:echo|sh|withCredentials)",
        r"^(?:#!/bin/bash|/usr/bin/env)\s",
        r"^\s*$",
        r"^[\+\-\=\*]{20,}$",
        r"^\d{4}-\d{2}-\d{2}T[\d:\.]+Z\s+",
        r"^\[INFO\]\s+",
        r"^\s*\.{3}\s*\d+:\d+$",  # Line number markers
    ]
    NOISE_RE = re.compile("|".join(f"({p})" for p in NOISE_PATTERNS), re.MULTILINE)

    # Patterns indicating failure or anomaly
    FAILURE_INDICATORS = [
        r"ERROR|FAILURE|FAILED|Exception|Traceback|error:|fatal:",
        r"AssertionError|SyntaxError|TypeError|ValueError",
        r"timeout|Timed out|Connection refused",
        r"exit code \d+|Build failed|Tests failed",
    ]
    FAILURE_RE = re.compile("|".join(FAILURE_INDICATORS), re.IGNORECASE)

    CONTEXT_LINES = 10

    def _extract_anomaly_clusters(self, raw_text: str) -> list[tuple[int, str]]:
        """Extract failure clusters with surrounding context."""
        lines = raw_text.splitlines()
        clusters: list[tuple[int, str]] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if self.FAILURE_RE.search(line):
                start = max(0, i - self.CONTEXT_LINES)
                end = min(len(lines), i + self.CONTEXT_LINES + 1)
                cluster_lines = lines[start:end]
                cluster_text = "\n".join(cluster_lines)
                if not self._is_mostly_noise(cluster_text):
                    clusters.append((start, cluster_text))
                i = end
            else:
                i += 1
        return clusters

    def _is_mostly_noise(self, text: str) -> bool:
        """Check if text is predominantly boilerplate."""
        if len(text.strip()) < 20:
            return True
        non_noise = self.NOISE_RE.sub("", text)
        return len(non_noise.strip()) < len(text) * 0.3

    def parse(self, raw: dict) -> list[JenkinsLogChunk]:
        """Parse Jenkins webhook or raw log payload into chunks."""
        job_name = raw.get("job_name", "unknown")
        build_number = raw.get("build_number", 0)
        git_commit = raw.get("git_commit")
        workspace = raw.get("workspace_path")
        console_text = raw.get("console_output", raw.get("log", ""))
        if not console_text:
            return []

        clusters = self._extract_anomaly_clusters(console_text)
        chunks: list[JenkinsLogChunk] = []
        for idx, (line_offset, cluster_text) in enumerate(clusters):
            failure_sig = self._extract_failure_signature(cluster_text)
            chunk = JenkinsLogChunk(
                id=f"jenkins:{job_name}:{build_number}:{idx}",
                source="jenkins",
                content=self._normalize(cluster_text),
                metadata={
                    "job_name": job_name,
                    "build_number": build_number,
                    "git_commit": git_commit,
                    "workspace_path": workspace,
                    "line_offset": line_offset,
                },
                job_name=job_name,
                build_number=build_number,
                git_commit=git_commit,
                workspace_path=workspace,
                failure_signature=failure_sig,
            )
            chunks.append(chunk)
        return chunks

    def _extract_failure_signature(self, text: str) -> str | None:
        """Extract a compact failure signature for correlation."""
        for m in self.FAILURE_RE.finditer(text):
            return m.group(0)[:80]
        return None

    def _normalize(self, text: str) -> str:
        """Remove excessive whitespace and normalize."""
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def to_embedding_payload(self, chunk: JenkinsLogChunk) -> str:
        """Format chunk for embedding."""
        parts = [
            f"[Jenkins] {chunk.job_name} build #{chunk.build_number}",
            chunk.content,
        ]
        if chunk.failure_signature:
            parts.insert(1, f"Failure: {chunk.failure_signature}")
        return "\n\n".join(parts)
