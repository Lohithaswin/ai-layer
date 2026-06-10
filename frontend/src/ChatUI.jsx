import React, { useState, useEffect, useRef, useCallback } from 'react';
import './ChatUI.css';
import { Zap, Bot, User, Search, FileText, Clock, BarChart2, Download, Sun, Moon, Paperclip, Send, HelpCircle, FolderOpen, PanelLeftClose, PanelLeftOpen, X, ChevronRight, ChevronDown, Copy, Square } from 'lucide-react';

const API_BASE = 'http://localhost:8000';

const EXAMPLE_QUERIES = [
  'What is PROJECT_NAME?',
  'Explain Product Security Management architecture',
  'What are the fields in the Add New User window?',
  'What is the PROJECT_MODULE full form?',
];

const getInitialTheme = () => {
  try { return localStorage.getItem('chat_theme') || 'dark'; } catch { return 'dark'; }
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
        <button key={index} type="button" className="citation-badge" onClick={() => onCitation(ref)} title={`View source [${ref}]`}>
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
    if (trimmed.startsWith('### ')) return <h4 key={i}>{trimmed.slice(4)}</h4>;
    if (trimmed.startsWith('## ')) return <h3 key={i}>{trimmed.slice(3)}</h3>;
    if (trimmed.startsWith('# ')) return <h2 key={i}>{trimmed.slice(2)}</h2>;
    if (/^[-*] /.test(trimmed)) return <li key={i} className="md-li">{renderInline(trimmed.slice(2), onCitation)}</li>;
    if (trimmed === '---') return <hr key={i} className="md-hr" />;
    if (trimmed.startsWith('*') && trimmed.endsWith('*') && trimmed.length > 2) return <p key={i} className="satisfaction-note">{trimmed.slice(1, -1)}</p>;
    if (!trimmed) return <br key={i} />;
    return <p key={i} className="md-p">{renderInline(line, onCitation)}</p>;
  });
}

export function ChatUI() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Hello! I\'m your **Document Intelligence Assistant**. Ask me anything about YOUR_PRODUCT — I\'ll search through all indexed PDFs and deliver precise, sourced answers.\n\nYou can also use the **section search bar** above to jump directly to any section.',
      sources: [],
    },
  ]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [expandedSources, setExpandedSources] = useState({});
  const [showMetrics, setShowMetrics] = useState(false);
  const [backendStatus, setBackendStatus] = useState('checking');
  const [docs, setDocs] = useState({ files: [], collection_size: 0 });
  const [health, setHealth] = useState({});
  const [activeSources, setActiveSources] = useState([]);
  const [highlightedRef, setHighlightedRef] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [theme, setTheme] = useState(getInitialTheme);
  const [searchHistory, setSearchHistory] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [selectedProduct, setSelectedProduct] = useState('');
  const [availableProducts, setAvailableProducts] = useState([]);
  const [availableSections, setAvailableSections] = useState([]);
  const [sectionSearchTerm, setSectionSearchTerm] = useState('');
  const [showSectionDropdown, setShowSectionDropdown] = useState(false);
  const [sectionFetching, setSectionFetching] = useState(false);
  const [availableModels, setAvailableModels] = useState([]);
  const [activeModel, setActiveModel] = useState('');
  const [modelSaving, setModelSaving] = useState(false);

  const messagesEndRef = useRef(null);
  const abortControllerRef = useRef(null);
  const searchInputRef = useRef(null);
  const dropdownRef = useRef(null);
  const wrapperRef = useRef(null);

  useEffect(() => {
    document.documentElement.className = theme === 'dark' ? 'dark-theme' : '';
    try { localStorage.setItem('chat_theme', theme); } catch (e) {}
  }, [theme]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target) && !searchInputRef.current?.contains(e.target)) {
        setShowSectionDropdown(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const refreshStatus = async () => {
    try {
      const healthRes = await fetch(`${API_BASE}/health`);
      if (healthRes.ok) {
        const h = await healthRes.json();
        setHealth(h);
        setBackendStatus('online');
        const docsRes = await fetch(`${API_BASE}/documents`);
        if (docsRes.ok) setDocs(await docsRes.json());
        const prodRes = await fetch(`${API_BASE}/products`);
        if (prodRes.ok) { const pd = await prodRes.json(); setAvailableProducts(pd.products || []); }
        const sectRes = await fetch(`${API_BASE}/sections`);
        if (sectRes.ok) { const sd = await sectRes.json(); setAvailableSections(sd.sections || []); }
        const modRes = await fetch(`${API_BASE}/models`);
        if (modRes.ok) { const md = await modRes.json(); setAvailableModels(md.models || []); setActiveModel(prev => prev || md.active || ''); }
      } else { setBackendStatus('offline'); }
    } catch { setBackendStatus('offline'); }
  };

  useEffect(() => {
    refreshStatus();
    const id = setInterval(refreshStatus, 15000);
    return () => clearInterval(id);
  }, []);

  const handleCitation = (ref, sources) => {
    setHighlightedRef(ref);
    setActiveSources(sources || []);
    setDrawerOpen(true);
    setTimeout(() => {
      document.getElementById(`source-card-${ref}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 50);
  };

  const filteredSections = useCallback(() => {
    if (!sectionSearchTerm) return [];
    const lower = sectionSearchTerm.toLowerCase();
    return availableSections
      .filter(s => s.section_title?.toLowerCase().includes(lower))
      .slice(0, 50);
  }, [sectionSearchTerm, availableSections]);

  const handleSectionSelect = async (sectionTitle, sourceFile) => {
    setSectionSearchTerm('');
    setShowSectionDropdown(false);
    setSectionFetching(true);

    // Add user "fetch" message
    setMessages(prev => [...prev, {
      role: 'user',
      content: `Fetch section: **${sectionTitle}**\n\n*From: ${sourceFile}*`,
    }]);

    try {
      const response = await fetch(`${API_BASE}/section-content?section=${encodeURIComponent(sectionTitle)}&source_file=${encodeURIComponent(sourceFile)}`);
      if (!response.ok) throw new Error('Failed to fetch section content');
      const data = await response.json();
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `### ${sectionTitle}\n\n${data.content}`,
        sources: [],
        note: 'direct_section_fetch',
        sectionRef: { title: sectionTitle, file: sourceFile },
      }]);
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Could not fetch content for section **"${sectionTitle}"**. Please try again.`,
        error: true,
      }]);
    } finally {
      setSectionFetching(false);
    }
  };

  const handleSendMessage = async (e, overrideText, productFilterOverride, fileFilterOverride) => {
    e?.preventDefault();
    const text = (overrideText ?? inputValue).trim();
    if (!text || loading) return;

    setInputValue('');
    setLoading(true);
    setSearchHistory(prev => Array.from(new Set([text, ...prev])).slice(0, 20));

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const history = messages
      .filter(m => (m.role === 'user' || m.role === 'assistant') && m.content && !m.error)
      .slice(-8)
      .map(m => ({ role: m.role, content: m.content }));

    setMessages(prev => [...prev, { role: 'user', content: text }]);

    const effectiveProductFilter = productFilterOverride !== undefined ? productFilterOverride : (selectedProduct || null);

    try {
      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, history, product_filter: effectiveProductFilter, file_filter: fileFilterOverride || null }),
        signal: controller.signal,
      });

      if (!response.ok) throw new Error(`API error (${response.status})`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let answer = '';
      let isClarification = false;

      let assistantMessage = { role: 'assistant', content: '', sources: [], isClarification: false };
      setMessages(prev => [...prev, assistantMessage]);

      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.chunk) {
                answer += data.chunk;
                setMessages(prev => {
                  const newMessages = [...prev];
                  newMessages[newMessages.length - 1] = { ...assistantMessage, content: answer, isClarification };
                  return newMessages;
                });
              }
              if (data.done) {
                isClarification = data.clarification === true;
                assistantMessage.sources = data.sources || [];
                assistantMessage.isClarification = isClarification;
                setMessages(prev => {
                  const newMessages = [...prev];
                  newMessages[newMessages.length - 1] = { ...assistantMessage, content: answer, sources: data.sources || [], isClarification };
                  return newMessages;
                });
                if (data.sources && data.sources.length > 0) { setActiveSources(data.sources); setDrawerOpen(true); }
              }
            } catch (e) {}
          }
        }
      }
    } catch (error) {
      if (error.name === 'AbortError') {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Generation stopped.', sources: [] }]);
      } else {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: `Could not reach the API at ${API_BASE}. Make sure the backend is running.`,
          error: true,
        }]);
      }
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
    }
  };

  const stopResponse = () => { if (abortControllerRef.current) abortControllerRef.current.abort(); };
  const copyToClipboard = (text) => navigator.clipboard.writeText(text);
  const exportChat = () => {
    const dataStr = JSON.stringify(messages, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);
    const a = document.createElement('a');
    a.setAttribute('href', dataUri);
    a.setAttribute('download', `chat-export-${new Date().toISOString()}.json`);
    a.click();
  };

  const handleModelChange = async (model) => {
    if (!model || model === activeModel) return;
    setModelSaving(true);
    try {
      const res = await fetch(`${API_BASE}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model }),
      });
      if (res.ok) {
        setActiveModel(model);
      }
    } catch {}
    setModelSaving(false);
  };


  const sections = filteredSections();

  return (
    <div className={`chat-app ${theme}`}>
      {/* ── SIDEBAR ── */}
      <aside className={`sidebar ${sidebarOpen ? 'open' : 'collapsed'}`}>
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <div className="logo-icon"><Zap size={20} /></div>
            <div className="logo-text">
              <span className="logo-title">DocIntel</span>
              <span className="logo-sub">AI Document Search</span>
            </div>
          </div>
          <button className="sidebar-toggle-btn" onClick={() => setSidebarOpen(!sidebarOpen)}>
            {sidebarOpen ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}
          </button>
        </div>

        {sidebarOpen && (
          <>
            {/* Status */}
            <div className="sidebar-section">
              <div className="sidebar-section-title">System Status</div>
              <div className={`status-indicator ${backendStatus}`}>
                <span className="status-dot" />
                <span className="status-text">{backendStatus === 'online' ? 'Connected' : 'Offline'}</span>
                <span className="status-count">{docs.collection_size.toLocaleString()} chunks</span>
              </div>
              {health.hybrid_search && (
                <div className="tech-pills">
                  <span className="tech-pill">Dense+BM25</span>
                  {health.reranker && <span className="tech-pill">Re-ranker</span>}
                </div>
              )}
            </div>

            {/* Product Filter */}
            {availableProducts.length > 0 && (
              <div className="sidebar-section">
                <div className="sidebar-section-title">Product Filter</div>
                <select className="sidebar-select" value={selectedProduct} onChange={e => setSelectedProduct(e.target.value)}>
                  <option value="">All Products</option>
                  {availableProducts.map(p => <option key={p} value={p}>{p.toUpperCase()}</option>)}
                </select>
                {selectedProduct && (
                  <div className="active-filter">
                    <span>{selectedProduct.toUpperCase()}</span>
                    <button onClick={() => setSelectedProduct('')}><X size={14} /></button>
                  </div>
                )}
              </div>
            )}

            {/* Docs list */}
            <div className="sidebar-section flex-grow">
              <div className="sidebar-section-title">Documents ({docs.files?.length || 0})</div>
              <div className="docs-list">
                {docs.files?.length > 0 ? (
                  docs.files.map((f, i) => (
                    <div key={i} className="doc-item" title={f}>
                      <span className="doc-icon"><FileText size={14} /></span>
                      <span className="doc-name">{f.split('/').pop()}</span>
                    </div>
                  ))
                ) : (
                  <p className="muted-text">No documents indexed</p>
                )}
              </div>
            </div>

            {/* Quick queries */}
            <div className="sidebar-section">
              <div className="sidebar-section-title">Quick Queries</div>
              <div className="quick-queries">
                {EXAMPLE_QUERIES.map(q => (
                  <button key={q} type="button" className="quick-btn" onClick={() => handleSendMessage(null, q)}>
                    {q}
                  </button>
                ))}
              </div>
            </div>

            {/* Recent History */}
            {searchHistory.length > 0 && (
              <div className="sidebar-section">
                <div className="sidebar-section-title">Recent</div>
                <div className="docs-list">
                  {searchHistory.slice(0, 8).map((q, i) => (
                    <button key={i} type="button" className="history-item" onClick={() => handleSendMessage(null, q)} title={q}>
                      <span className="history-icon"><Clock size={14} /></span>
                      <span className="history-text">{q}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </aside>

      {/* ── MAIN AREA ── */}
      <div className="chat-main">
        {/* ── TOP BAR ── */}
        <header className="chat-header">
          {!sidebarOpen && (
            <button className="hdr-btn" onClick={() => setSidebarOpen(true)} title="Expand sidebar">
              <PanelLeftOpen size={18} />
            </button>
          )}
          <div className="header-brand">
            <h1>Document Assistant</h1>
            <span className="header-sub">Semantic · Hybrid · Re-ranked</span>
          </div>

          {/* ── SECTION SEARCH BAR (center, wide) ── */}
          <div className={`section-search-wrapper ${showSectionDropdown ? 'expanded' : ''}`} ref={wrapperRef}>
            <div className="section-search-bar">
              <span className="search-icon-left"><Search size={16} /></span>
              <input
                ref={searchInputRef}
                type="text"
                className="section-search-input"
                placeholder="Search sections & subsections — jump directly to any content…"
                value={sectionSearchTerm}
                onChange={e => { setSectionSearchTerm(e.target.value); setShowSectionDropdown(true); }}
                onFocus={() => setShowSectionDropdown(true)}
                autoComplete="off"
              />
              {sectionSearchTerm && (
                <button className="search-clear-btn" onClick={() => { setSectionSearchTerm(''); setShowSectionDropdown(false); }}><X size={14} /></button>
              )}
            </div>
            {showSectionDropdown && sectionSearchTerm && (
              <div className="section-dropdown" ref={dropdownRef}>
                {sections.length === 0 ? (
                  <div className="dropdown-empty">No sections found for "{sectionSearchTerm}"</div>
                ) : (
                  <>
                    <div className="dropdown-header">
                      <span>{sections.length} section{sections.length !== 1 ? 's' : ''} found</span>
                    </div>
                    <div className="dropdown-list">
                      {sections.map((s, i) => (
                        <button
                          key={i}
                          className="dropdown-item"
                          onMouseDown={() => handleSectionSelect(s.section_title, s.source_file)}
                        >
                          <div className="dropdown-item-title">{s.section_title}</div>
                          <div className="dropdown-item-file">
                            <span className="file-icon"><FileText size={14} /></span>
                            {s.source_file.split('/').pop()}
                          </div>
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          {/* ── HEADER ACTIONS ── */}
          <div className="header-actions">
            {/* Model selector */}
            <div className="model-selector-wrapper" title="Switch AI model — faster models respond quicker">
              <span className="model-selector-label">Model</span>
              <select
                className="model-selector-select"
                value={activeModel || 'llama3.2'}
                onChange={e => handleModelChange(e.target.value)}
                disabled={modelSaving || loading || backendStatus === 'offline'}
              >
                {availableModels.length > 0 ? (
                  availableModels.map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))
                ) : (
                  <option value={activeModel || 'llama3.2'}>{activeModel || 'llama3.2'}</option>
                )}
              </select>
              {modelSaving && <span className="model-saving-dot" title="Switching model…" />}
            </div>
            
            <button className="hdr-btn" onClick={() => setShowMetrics(!showMetrics)} title="Toggle metrics">
              {showMetrics ? <><BarChart2 size={16} /> Metrics: On</> : <><BarChart2 size={16} /> Metrics</>}
            </button>
            <button className="hdr-btn" onClick={exportChat} title="Export chat"><Download size={16} /> Export</button>
            <button className="hdr-btn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} title="Toggle theme">
              {theme === 'dark' ? <><Sun size={16} /> Light Mode</> : <><Moon size={16} /> Dark Mode</>}
            </button>
            {activeSources.length > 0 && (
              <button className="hdr-btn sources-hdr-btn" onClick={() => setDrawerOpen(!drawerOpen)}>
                <><Paperclip size={16} /> Sources</> {activeSources.length}
              </button>
            )}
          </div>
        </header>

        {/* ── MESSAGES ── */}
        <div className="chat-container">
          {(sectionFetching) && (
            <div className="section-fetching-banner">
              <div className="fetching-spinner" />
              <span>Fetching section content…</span>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div key={idx} className={`message ${msg.role}`}>
              {msg.role === 'assistant' && (
                <div className="avatar assistant-avatar"><Bot size={18} /></div>
              )}
              <div className={`message-bubble ${msg.role} ${msg.error ? 'error' : ''} ${msg.isClarification ? 'clarification' : ''}`}>
                {msg.role === 'user' ? (
                  <div className="user-text">{renderMarkdown(msg.content, () => {})}</div>
                ) : (
                  <>
                    {msg.isClarification && (
                      <div className="clarification-header">
                        <span className="clarification-icon"><HelpCircle size={16} /></span>
                        <span>Clarification needed</span>
                      </div>
                    )}

                    {msg.note === 'direct_section_fetch' && msg.sectionRef && (
                      <div className="section-fetch-badge">
                        <span className="fetch-icon"><FolderOpen size={16} /></span>
                        <div className="fetch-info">
                          <span className="fetch-label">Direct Section Fetch</span>
                          <span className="fetch-file">{msg.sectionRef.file.split('/').pop()}</span>
                        </div>
                        <span className="fetch-tag">No LLM</span>
                      </div>
                    )}

                    <div className="answer-text">
                      {renderMarkdown(msg.content, ref => handleCitation(ref, msg.sources))}
                    </div>

                    {msg.note === 'ollama_offline' && <div className="alert warn">Ollama offline — showing retrieved excerpts only.</div>}
                    {msg.note === 'ollama_timeout' && <div className="alert warn">Model timeout — excerpts shown.</div>}
                    {msg.note === 'verification_failed' && <div className="alert warn">Answer could not be verified against sources.</div>}

                    {msg.sources?.length > 0 && (
                      <div className="sources-panel">
                        <button type="button" className="sources-toggle" onClick={() => setExpandedSources(p => ({ ...p, [idx]: !p[idx] }))}>
                          <span className="sources-toggle-icon">{expandedSources[idx] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
                          <span>{msg.sources.length} Reference{msg.sources.length !== 1 ? 's' : ''}</span>
                        </button>
                        {expandedSources[idx] && (
                          <div className="sources-list">
                            {msg.sources.map(s => (
                              <button key={s.ref} type="button" className="source-item" onClick={() => handleCitation(s.ref, msg.sources)}>
                                <span className="source-ref">[{s.ref}]</span>
                                <div className="source-info">
                                  <div className="source-section">{s.section || s.source_file}</div>
                                  {s.section && <div className="source-doc">{s.source_file.split('/').pop()}</div>}
                                </div>
                                <span className="source-meta">p.{s.page} · {formatRelevance(s.score)}</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {showMetrics && msg.processingTimeMs != null && (
                      <div className="metrics-panel">
                        {[
                          ['Total', `${msg.processingTimeMs.toFixed(0)}ms`],
                          ['Retrieval', `${msg.retrievalTimeMs?.toFixed(0)}ms`],
                          ['Mode', msg.retrievalMode || '—'],
                          ['Intent', msg.questionIntent || '—'],
                          ['Sources', msg.numSourcesRetrieved],
                          ['LLM', msg.usedLlm ? 'Yes' : 'No'],
                        ].map(([label, val]) => (
                          <div key={label} className="metric-pill">
                            <span className="metric-label">{label}</span>
                            <span className="metric-value">{val}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Per-message filters */}
                    {msg.sources && Array.from(new Set(msg.sources.map(s => s.source_file))).length > 1 && (
                      <div className="filter-row">
                        <span className="filter-label">Narrow to:</span>
                        <select className="filter-select" onChange={e => {
                          if (e.target.value) {
                            const lastUser = messages.filter(m => m.role === 'user').pop()?.content || '';
                            handleSendMessage(null, lastUser, null, e.target.value);
                          }
                        }} defaultValue="">
                          <option value="" disabled>Select document…</option>
                          {Array.from(new Set(msg.sources.map(s => s.source_file))).map((file, i) => (
                            <option key={i} value={file}>{file.split('/').pop()}</option>
                          ))}
                        </select>
                      </div>
                    )}

                    <div className="message-actions">
                      <button className="action-btn" onClick={() => copyToClipboard(msg.content)} title="Copy">
                        <Copy size={14} /> Copy
                      </button>
                    </div>
                  </>
                )}
              </div>
              {msg.role === 'user' && (
                <div className="avatar user-avatar"><User size={18} /></div>
              )}
            </div>
          ))}

          {loading && (
            <div className="message assistant">
              <div className="avatar assistant-avatar"><Bot size={18} /></div>
              <div className="message-bubble assistant">
                <div className="typing-indicator">
                  <span /><span /><span />
                </div>
                <p className="loading-label">Searching documents & generating response…</p>
                <button className="action-btn stop-btn" onClick={stopResponse}><Square size={14} /> Stop</button>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* ── INPUT AREA ── */}
        <form onSubmit={handleSendMessage} className="input-area">
          <div className="input-wrapper">
            <textarea
              value={inputValue}
              onChange={e => setInputValue(e.target.value)}
              placeholder={selectedProduct ? `Ask about ${selectedProduct.toUpperCase()} documents…` : 'Ask anything about PROJECT_MODULE, PROJECT_NAME, procedures, configurations…'}
              disabled={loading}
              rows={1}
              className="chat-textarea"
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage(e); }
              }}
            />
            <button type="submit" disabled={loading || !inputValue.trim()} className="send-btn">
              <span>{loading ? '⏳' : '➤'}</span>
            </button>
          </div>
          <div className="input-hint">Press Enter to send · Shift+Enter for new line · Use the search bar above to jump to sections</div>
        </form>
      </div>

      {/* ── SOURCES DRAWER ── */}
      {drawerOpen && activeSources.length > 0 && (
        <aside className="source-drawer">
          <div className="drawer-head">
            <h3>📎 Sources</h3>
            <button type="button" className="drawer-close" onClick={() => setDrawerOpen(false)}>✕</button>
          </div>
          <div className="drawer-body">
            {activeSources.map(s => (
              <div
                key={s.ref}
                id={`source-card-${s.ref}`}
                className={`drawer-card ${highlightedRef === s.ref ? 'highlighted' : ''}`}
                onClick={() => setHighlightedRef(s.ref)}
              >
                <div className="drawer-card-top">
                  <span className="source-ref">[{s.ref}]</span>
                  <div className="drawer-card-badges">
                    {s.product && s.product !== 'unknown' && <span className="product-pill">{s.product.toUpperCase()}</span>}
                    <span className="score-pill">{formatRelevance(s.score)}</span>
                  </div>
                </div>
                <div className="drawer-section">{s.section || s.source_file}</div>
                {s.section && <div className="drawer-doc">{s.source_file.split('/').pop()}</div>}
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
