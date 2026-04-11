import { useState, useEffect } from "react";
import { FailuresList } from "../components/FailuresList";
import type { Failure } from "../types";

export default function Failures() {
  const [failures, setFailures] = useState<Failure[]>([]);

  useEffect(() => {
    fetch("/api/v1/failures")
      .then((r) => r.json())
      .then((d) => setFailures(d.failures ?? []))
      .catch(() => setFailures([]));
  }, []);

  return (
    <div className="failures-page">
      <h1>Pipeline Failures</h1>
      <FailuresList
        failures={failures}
        onRefresh={() => window.location.reload()}
      />
    </div>
  );
}
