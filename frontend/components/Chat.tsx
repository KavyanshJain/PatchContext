"use client";
import { FormEvent, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, Answer, Citation, Repo } from "../lib/api";

type Message = { role: "user" | "assistant"; text: string; citations?: Citation[]; refused?: boolean };

export function Chat({ repo }: { repo: Repo }) {
  const [temperature, setTemperature] = useState(0.2);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);

  async function ask(event: FormEvent) {
    event.preventDefault();
    const value = question.trim();
    if (!value || loading) return;

    setMessages((current) => [...current, { role: "user", text: value }]);
    setQuestion("");
    setLoading(true);

    try {
      const response: Answer = await api.ask(repo.key, value, temperature);
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: response.answer,
          citations: response.citations,
          refused: response.refused,
        },
      ]);
    } catch (err) {
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: err instanceof Error ? err.message : "The query failed.",
          refused: true,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="chat-shell">
      <header className="chat-head">
        <div>
          <span className="eyebrow">
            EXPLORATION / {repo.owner.toUpperCase()} / {repo.repo.toUpperCase()}
          </span>
          <h1>Trace the decisions behind the code.</h1>
        </div>
        <a href={repo.url} target="_blank" rel="noreferrer">
          Open repository ↗
        </a>
      </header>

      <div className="messages" aria-live="polite">
        {messages.length === 0 && (
          <div className="empty-state">
            <span>⌁</span>
            <p>Ask why something was built, changed, or linked to an issue.</p>
            <small>Answers are constrained to indexed commits, pull requests, and issue discussions.</small>
          </div>
        )}

        {messages.map((message, index) => (
          <article
            key={index}
            className={`message ${message.role} ${message.refused ? "refusal" : ""}`}
          >
            <div className="message-label">
              {message.role === "user"
                ? "YOU"
                : message.refused
                ? "GROUNDING GATE"
                : "PATCHCONTEXT"}
            </div>
            {message.role === "assistant" && !message.refused ? (
              <div className="markdown-body">
                <ReactMarkdown>{message.text}</ReactMarkdown>
              </div>
            ) : (
              <p>{message.text}</p>
            )}
            
            {message.citations && message.citations.length > 0 && (
              <div className="citations">
                {message.citations.map((citation) => (
                  <a key={citation.id} href={citation.url} target="_blank" rel="noreferrer">
                    {citation.label} ↗
                  </a>
                ))}
              </div>
            )}
          </article>
        ))}

        {loading && (
          <article className="message assistant loading">
            <div className="message-label">PATCHCONTEXT</div>
            <p>Following the repository graph…</p>
          </article>
        )}
      </div>

      <form className="composer" onSubmit={ask}>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about this repository…"
          rows={2}
        />
        <div className="composer-bar">
          <label>
            Temperature{" "}
            <input
              type="range"
              min="0"
              max="1.5"
              step="0.1"
              value={temperature}
              onChange={(e) => setTemperature(Number(e.target.value))}
            />
            <code>{temperature.toFixed(1)}</code>
          </label>
          <button disabled={loading || !question.trim()}>Ask →</button>
        </div>
      </form>
    </section>
  );
}
