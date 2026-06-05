import React, { useState, useEffect, useRef } from 'react';
import './ChatUI.css';

const API_BASE = 'http://localhost:8000';

const EXAMPLE_QUERIES = [
  'What is PROJECT_NAME?',
  'Explain Product Security Management architecture',
  'What are the fields in the Add New User window?',
  'What is the PROJECT_MODULE full form?',
];

// Fallback logic for localStorage to avoid SSR/hydration issues if any
const getInitialTheme = () => {
  try {
    return localStorage.getItem('chat_theme') || 'light';
  } catch {
    return 'light';
  }
};

function formatRelevance(score) {
  if (score == null || Number.isNaN(score)) return '—';
  const pct = score <= 1 ? score * 100 : score;
  return `${Math.max(0, Math.min(100, pct)).toFixed(0)}%`;
}

function renderInline(text, onCitation) {
  const parts = text.split(/(\*\*.*?\*\*|\[\d+\])/g);
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    const cite = part.match(/^\[(\d+)\]$/);
    if (cite) {
      const ref = parseInt(cite[1], 10);
      return (
        <button
          key={index}
          type="button"
          className="citation-badge"
          onClick={() => onCitation(ref)}
          title={`View source [${ref}]`}
        >
          [{ref}]
        </button>
      );
    }
    return <span key={index}>{part}</span>;
  });
}

function renderMarkdown(text, onCitation) {
  if (!text) return null;
  const footerIdx = text.indexOf('\n\n---\n**Sources:**');
  const body = footerIdx > -1 ? text.slice(0, footerIdx) : text;

  return body.split('\n').map((line, i) => {
    const trimmed = line.trim();
    if (trimmed.startsWith('### ')) {
      return <h4 key={i}>{trimmed.slice(4)}</h4>;
    }
    if (trimmed.startsWith('## ')) {
      return <h3 key={i}>{trimmed.slice(3)}</h3>;
    }
    if (trimmed.startsWith('# ')) {
      return <h2 key={i}>{trimmed.slice(2)}</h2>;
    }
    if (/^[-*] /.test(trimmed)) {
      return (
        <li key={i} className="md-li">
          {renderInline(trimmed.slice(2), onCitation)}
        </li>
      );
    }
    if (!trimmed) return <br key={i} />;
    return (
      <p key={i} className="md-p">
        {renderInline(line, onCitation)}
      </p>
    );
  });
}

export function ChatUI() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content:
        'Ask questions about your indexed PDFs. Answers use **hybrid search** (semantic + BM25), **cross-encoder re-ranking**, and **parent-page context** for higher accuracy.',
      sources: [],
    },
  ]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [expandedSources, setExpandedSources] = useState({});
  const [showMetrics, setShowMetrics] = useState(true);
  const [backendStatus, setBackendStatus] = useState('checking');
  const [docs, setDocs] = useState({ files: [], collection_size: 0 });
  const [health, setHealth] = useState({});
  const [activeSources, setActiveSources] = useState([]);
  const [highlightedRef, setHighlightedRef] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [theme, setTheme] = useState(getInitialTheme);
  const [searchHistory, setSearchHistory] = useState([]);

  const messagesEndRef = useRef(null);
  const abortControllerRef = useRef(null);

  useEffect(() => {
    document.documentElement.className = theme === 'dark' ? 'dark-theme' : '';
    try {
      localStorage.setItem('chat_theme', theme);
    } catch (e) {}
  }, [theme]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const refreshStatus = async () => {
    try {
      const healthRes = await fetch(`${API_BASE}/health`);
      if (healthRes.ok) {
        const h = await healthRes.json();
        setHealth(h);
        setBackendStatus('online');
        const docsRes = await fetch(`${API_BASE}/documents`);
        if (docsRes.ok) setDocs(await docsRes.json());
      } else {
        setBackendStatus('offline');
      }
    } catch {
      setBackendStatus('offline');
    }
  };

  useEffect(() => {
    refreshStatus();
    const id = setInterval(refreshStatus, 10000);
    return () => clearInterval(id);
  }, []);

  const handleCitation = (ref, sources) => {
    setHighlightedRef(ref);
    setActiveSources(sources || []);
    setDrawerOpen(true);
    setTimeout(() => {
      document.getElementById(`source-card-${ref}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }, 50);
  };

  const handleSendMessage = async (e, overrideText, productFilterOverride, fileFilterOverride) => {
    e?.preventDefault();
    const text = (overrideText ?? inputValue).trim();
    if (!text || loading) return;

    setInputValue('');
    setLoading(true);
    setSearchHistory((prev) => Array.from(new Set([text, ...prev])).slice(0, 20));

    // Create a new AbortController for this request
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const history = messages
      .filter((m) => (m.role === 'user' || m.role === 'assistant') && m.content && !m.error)
      .slice(-8)
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, { role: 'user', content: text }]);

    try {
      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          question: text, 
          history,
          product_filter: productFilterOverride || null,
          file_filter: fileFilterOverride || null
        }),
        signal: controller.signal,
      });

      if (!response.ok) throw new Error(`API error (${response.status})`);
      
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let answer = '';
      
      let assistantMessage = {
        role: 'assistant',
        content: '',
        sources: [],
      };
      
      setMessages((prev) => [...prev, assistantMessage]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const chunkStr = decoder.decode(value, { stream: true });
        const lines = chunkStr.split('\n');
        for (const line of lines) {
            if (line.startsWith('data: ')) {
                try {
                    const data = JSON.parse(line.slice(6));
                    if (data.chunk) {
                        answer += data.chunk;
                        setMessages((prev) => {
                            const newMessages = [...prev];
                            newMessages[newMessages.length - 1] = { ...assistantMessage, content: answer };
                            return newMessages;
                        });
                    }
                    if (data.done) {
                        assistantMessage.sources = data.sources || [];
                        setMessages((prev) => {
                            const newMessages = [...prev];
                            newMessages[newMessages.length - 1] = { ...assistantMessage, content: answer, sources: data.sources || [] };
                            return newMessages;
                        });
                        if (data.sources && data.sources.length > 0) {
                            setActiveSources(data.sources);
                            setDrawerOpen(true);
                        }
                    }
                } catch (e) {}
            }
        }
      }
    } catch (error) {
      if (error.name === 'AbortError') {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: 'Generation stopped by user.',
            sources: [],
          },
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `Could not reach the API at ${API_BASE}. Start the backend: uvicorn api:app --reload --port 8000`,
            error: true,
          },
        ]);
      }
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
    }
  };

  const stopResponse = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
  };

  const exportChat = () => {
    const dataStr = JSON.stringify(messages, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);
    const exportFileDefaultName = `chat-export-${new Date().toISOString()}.json`;
    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
  };

  return (
    <div className="chat-app">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div>
            <div className="brand-title">PDF RAG</div>
            <div className="brand-sub">Hybrid + Rerank</div>
          </div>
        </div>

        <div className="sidebar-block">
          <div className="block-label">Backend</div>
          <div className="status-pill">
            <span className={`dot ${backendStatus}`} />
            {backendStatus === 'online' ? 'Connected' : 'Offline'}
          </div>
          {health.hybrid_search && (
            <div className="tech-tags">
              <span className="tag">Dense+BM25</span>
              {health.reranker && <span className="tag">Cross-Encoder</span>}
            </div>
          )}
          <div className="stat-row">
            <span>Indexed chunks</span>
            <strong>{docs.collection_size}</strong>
          </div>
        </div>

        <div className="sidebar-block flex-grow">
          <div className="block-label">PDFs ({docs.files?.length || 0})</div>
          <div className="file-scroll">
            {docs.files?.length > 0 ? (
              docs.files.map((f, i) => (
                <div key={i} className="file-row" title={f}>
                  {f}
                </div>
              ))
            ) : (
              <p className="muted">Add PDFs to docs/ and run ingest</p>
            )}
          </div>
        </div>

        <div className="sidebar-block">
          <div className="block-label">Try asking</div>
          {EXAMPLE_QUERIES.map((q) => (
            <button
              key={q}
              type="button"
              className="example-btn"
              onClick={() => handleSendMessage(null, q)}
            >
              {q}
            </button>
          ))}
        </div>

        {searchHistory.length > 0 && (
          <div className="sidebar-block">
            <div className="block-label">Recent History</div>
            <div className="file-scroll">
              {searchHistory.map((q, i) => (
                <button
                  key={i}
                  type="button"
                  className="example-btn history-btn"
                  onClick={() => handleSendMessage(null, q)}
                  title={q}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
      </aside>

      <div className="chat-main">
        <header className="chat-header">
          <div>
            <h1>Document Assistant</h1>
            <p>Semantic + keyword search · Re-ranked · Page-level context</p>
          </div>
          <div className="header-actions">
            <button
              type="button"
              className="metrics-btn"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            >
              {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
            </button>
            <button
              type="button"
              className="metrics-btn"
              onClick={exportChat}
            >
              Export
            </button>
            <button
              type="button"
              className="metrics-btn"
              onClick={() => setShowMetrics(!showMetrics)}
            >
              {showMetrics ? 'Hide Metrics' : 'Show Metrics'}
            </button>
            {activeSources.length > 0 && (
              <button
                type="button"
                className="metrics-btn"
                onClick={() => setDrawerOpen(!drawerOpen)}
              >
                Sources ({activeSources.length})
              </button>
            )}
          </div>
        </header>

        <div className="chat-container">
          {messages.map((msg, idx) => (
            <div key={idx} className={`message ${msg.role}`}>
              <div className={`message-content ${msg.error ? 'error' : ''}`}>
                {msg.role === 'user' ? (
                  <p>{msg.content}</p>
                ) : (
                  <>
                    <div className="answer-text">
                      {renderMarkdown(msg.content, (ref) =>
                        handleCitation(ref, msg.sources)
                      )}
                    </div>

                    {msg.note === 'ollama_offline' && (
                      <div className="alert warn">
                        Ollama offline — showing retrieved excerpts only.
                      </div>
                    )}
                    {msg.note === 'ollama_timeout' && (
                      <div className="alert warn">Model timeout — excerpts shown.</div>
                    )}
                    {msg.note === 'verification_failed' && (
                      <div className="alert warn">
                        Answer could not be verified against sources — excerpts shown below.
                      </div>
                    )}

                    {msg.sources?.length > 0 && (
                      <div className="sources-panel">
                        <button
                          type="button"
                          className="sources-toggle"
                          onClick={() =>
                            setExpandedSources((p) => ({
                              ...p,
                              [idx]: !p[idx],
                            }))
                          }
                        >
                          {expandedSources[idx] ? '▼' : '▶'} References (
                          {msg.sources.length})
                        </button>
                        {expandedSources[idx] && (
                          <div className="sources-list">
                            {msg.sources.map((s) => (
                              <button
                                key={s.ref}
                                type="button"
                                className="source-item"
                                onClick={() => handleCitation(s.ref, msg.sources)}
                              >
                                <span className="source-ref">[{s.ref}]</span>
                                <div className="source-file">
                                  {s.section
                                    ? `${s.section}`
                                    : s.source_file}
                                </div>
                                {s.section && (
                                  <div className="source-doc">
                                    {s.source_file}
                                  </div>
                                )}
                                <span className="source-meta">
                                  p.{s.page} · {formatRelevance(s.score)}
                                </span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {showMetrics && msg.processingTimeMs != null && (
                      <div className="metrics-panel">
                        <div className="metric">
                          <span>Total</span>
                          <strong>{msg.processingTimeMs.toFixed(0)}ms</strong>
                        </div>
                        <div className="metric">
                          <span>Retrieval</span>
                          <strong>{msg.retrievalTimeMs?.toFixed(0)}ms</strong>
                        </div>
                        <div className="metric">
                          <span>Mode</span>
                          <strong>{msg.retrievalMode || '—'}</strong>
                        </div>
                        <div className="metric">
                          <span>Intent</span>
                          <strong>{msg.questionIntent}</strong>
                        </div>
                        <div className="metric">
                          <span>Retrieved</span>
                          <strong>{msg.numSourcesRetrieved}</strong>
                        </div>
                        <div className="metric">
                          <span>LLM</span>
                          <strong>{msg.usedLlm ? 'Yes' : 'No'}</strong>
                        </div>
                      </div>
                    )}
                    {((msg.options && msg.options.length > 0) || (msg.sources && msg.sources.length > 0)) && (
                      <div className="options-dropdown-container">
                        {/* Section / Heading matches dropdown */}
                        {msg.options && msg.options.length > 0 && (
                          <div className="filter-group">
                            <span className="options-dropdown-label">Alternative matching sections:</span>
                            <select
                              className="options-dropdown"
                              onChange={(e) => {
                                if (e.target.value) {
                                  handleSendMessage(null, e.target.value);
                                }
                              }}
                              defaultValue=""
                            >
                              <option value="" disabled>Select an option...</option>
                              {msg.options.map((opt, oIdx) => (
                                <option key={oIdx} value={opt}>{opt}</option>
                              ))}
                            </select>
                          </div>
                        )}

                        {/* File Name Filter Dropdown */}
                        {msg.sources && Array.from(new Set(msg.sources.map(s => s.source_file))).length > 1 && (
                          <div className="filter-group">
                            <span className="options-dropdown-label">Narrow search to a specific document:</span>
                            <select
                              className="options-dropdown"
                              onChange={(e) => {
                                if (e.target.value) {
                                  const lastUserMsg = messages.filter(m => m.role === 'user').pop()?.content || '';
                                  handleSendMessage(null, lastUserMsg, null, e.target.value);
                                }
                              }}
                              defaultValue=""
                            >
                              <option value="" disabled>Select Document...</option>
                              {Array.from(new Set(msg.sources.map(s => s.source_file))).map((file, fIdx) => (
                                <option key={fIdx} value={file}>{file.split('\\').pop().split('/').pop()}</option>
                              ))}
                            </select>
                          </div>
                        )}

                        {/* Product Filter Dropdown */}
                        {msg.sources && Array.from(new Set(msg.sources.map(s => s.product).filter(p => p && p !== 'unknown' && p !== 'demo'))).length > 1 && (
                          <div className="filter-group">
                            <span className="options-dropdown-label">Narrow search to a specific product:</span>
                            <select
                              className="options-dropdown"
                              onChange={(e) => {
                                if (e.target.value) {
                                  const lastUserMsg = messages.filter(m => m.role === 'user').pop()?.content || '';
                                  handleSendMessage(null, lastUserMsg, e.target.value, null);
                                }
                              }}
                              defaultValue=""
                            >
                              <option value="" disabled>Select Product...</option>
                              {Array.from(new Set(msg.sources.map(s => s.product).filter(p => p && p !== 'unknown' && p !== 'demo'))).map((prod, pIdx) => (
                                <option key={pIdx} value={prod}>{prod.toUpperCase()}</option>
                              ))}
                            </select>
                          </div>
                        )}
                      </div>
                    )}

                    <div className="message-actions">
                      <button
                        className="action-btn"
                        onClick={() => copyToClipboard(msg.content)}
                        title="Copy to clipboard"
                      >
                        Copy
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="message assistant loading">
              <div className="message-content">
                <div className="typing-indicator">
                  <span />
                  <span />
                  <span />
                </div>
                <p className="loading-label">Generating response...</p>
                <div className="message-actions">
                   <button className="action-btn stop-btn" onClick={stopResponse}>
                     Stop Generating
                   </button>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <form onSubmit={handleSendMessage} className="input-form">
          <textarea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Ask about PROJECT_MODULE, PROJECT_NAME, procedures, fields…"
            disabled={loading}
            rows={1}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSendMessage(e);
              }
            }}
          />
          <button type="submit" disabled={loading || !inputValue.trim()}>
            Send
          </button>
        </form>
      </div>

      {drawerOpen && activeSources.length > 0 && (
        <aside className="source-drawer">
          <div className="drawer-head">
            <h3>Sources</h3>
            <button type="button" onClick={() => setDrawerOpen(false)}>
              ✕
            </button>
          </div>
          <div className="drawer-body">
            {activeSources.map((s) => (
              <div
                key={s.ref}
                id={`source-card-${s.ref}`}
                className={`drawer-card ${highlightedRef === s.ref ? 'highlighted' : ''}`}
                onClick={() => setHighlightedRef(s.ref)}
              >
                <div className="drawer-card-top">
                  <span className="source-ref">[{s.ref}]</span>
                  <span className="score-pill">{formatRelevance(s.score)}</span>
                </div>
                <div className="drawer-file">
                  {s.section
                    ? s.section
                    : s.source_file}
                </div>
                {s.section && (
                <div className="drawer-doc">
                  {s.source_file}
                </div>
              )}
                <div className="drawer-page">Page {s.page}</div>
                <p className="excerpt">"{s.excerpt}"</p>
              </div>
            ))}
          </div>
        </aside>
      )}
    </div>
  );
}
