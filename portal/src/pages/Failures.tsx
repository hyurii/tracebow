import { useCallback, useEffect, useState } from "react";
import { FailuresList } from "../components/FailuresList";
import { api } from "../api";
import type { Failure } from "../types";

export default function Failures() {
  const [failures, setFailures] = useState<Failure[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.listFailures();
      setFailures(data.failures);
      setError(null);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="failures-page">
      <h1>Pipeline Failures</h1>
      {error && <p className="wiki-error">{error}</p>}
      <FailuresList failures={failures} onRefresh={load} />
    </div>
  );
}
