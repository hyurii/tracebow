import { useState, useRef, useEffect } from "react";
import { api, pollTask } from "../api";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    if (!input.trim() || loading) return;
    const userMsg: Message = { role: "user", content: input.trim() };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setLoading(true);
    try {
      const accepted = await api.chat(userMsg.content);
      const result = await pollTask<{ response?: string; error?: string }>(accepted.task_id, {
        intervalMs: 1000,
        timeoutMs: 120_000,
      });
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: result.response ?? result.error ?? "No response.",
        },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `Error: ${String((e as Error).message ?? e)}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-section">
      <h2>Agent Chat</h2>
      <p className="chat-desc">
        Ask the agent to investigate a failure, correlate logs with PRs, or search Jira/Slack.
      </p>
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-placeholder">
            <p>Example prompts:</p>
            <ul>
              <li>"Why did the last build fail?"</li>
              <li>"Search Jira for database timeout issues"</li>
              <li>"What changed in the last PR that might have caused the failure?"</li>
            </ul>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`chat-message ${msg.role}`}>
            <span className="role">{msg.role}</span>
            <pre>{msg.content}</pre>
          </div>
        ))}
        {loading && (
          <div className="chat-message assistant">
            <span className="role">assistant</span>
            <span className="typing">Thinking…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="chat-input">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
          placeholder="Ask the agent…"
          rows={2}
        />
        <button onClick={send} disabled={loading}>
          Send
        </button>
      </div>
    </div>
  );
}
