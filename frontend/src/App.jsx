import React, { useState, useEffect, useRef } from 'react';
import './App.css';

const API_BASE = 'http://localhost:8000';

function App() {
  const [messages, setMessages] = useState([
    {
      id: 1,
      text: "Hello! I am your local PDF assistant. I can answer questions about the PDFs indexed in your database and cite the exact pages.",
      sender: 'bot',
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      sources: []
    }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [docs, setDocs] = useState({ files: [], collection_size: 0 });
  const [backendStatus, setBackendStatus] = useState('checking');
  const [activeSources, setActiveSources] = useState([]);
  const [highlightedSourceRef, setHighlightedSourceRef] = useState(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  const messagesEndRef = useRef(null);

  // Scroll to bottom when messages list changes
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Load docs & check backend health
  const checkHealthAndLoadDocs = async () => {
    try {
      const healthRes = await fetch(`${API_BASE}/health`);
      if (healthRes.ok) {
        setBackendStatus('online');
        const docsRes = await fetch(`${API_BASE}/documents`);
        if (docsRes.ok) {
          const docsData = await docsRes.json();
          setDocs(docsData);
        }
      } else {
        setBackendStatus('offline');
      }
    } catch (e) {
      setBackendStatus('offline');
    }
  };

  useEffect(() => {
    checkHealthAndLoadDocs();
    const interval = setInterval(checkHealthAndLoadDocs, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleCitationClick = (refNum) => {
    setHighlightedSourceRef(refNum);
    setIsDrawerOpen(true);
    // Find the source element and scroll it into view if needed
    const cardEl = document.getElementById(`source-card-${refNum}`);
    if (cardEl) {
      cardEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  };

  const parseMarkdown = (text) => {
    if (!text) return '';
    
    const lines = text.split('\n');
    let elements = [];
    let currentList = null;
    let listType = null; // 'ul' or 'ol'
    let listItems = [];

    const flushList = (key) => {
      if (currentList) {
        if (listType === 'ul') {
          elements.push(<ul key={`list-${key}`} className="chat-ul">{listItems}</ul>);
        } else {
          elements.push(<ol key={`list-${key}`} className="chat-ol">{listItems}</ol>);
        }
        currentList = null;
        listType = null;
        listItems = [];
      }
    };

    lines.forEach((line, lineIdx) => {
      const trimmed = line.trim();
      
      // Matches bullet lists: starts with * or - followed by spaces
      const bulletMatch = line.match(/^(\s*)([*+-])\s+(.*)$/);
      // Matches ordered lists: starts with digits followed by . and spaces
      const orderMatch = line.match(/^(\s*)(\d+)\.\s+(.*)$/);

      if (bulletMatch) {
        if (listType !== 'ul') {
          flushList(lineIdx);
        }
        listType = 'ul';
        currentList = true;
        listItems.push(
          <li key={`li-${lineIdx}`} className="chat-li">
            {parseInlineMarkup(bulletMatch[3])}
          </li>
        );
      } else if (orderMatch) {
        if (listType !== 'ol') {
          flushList(lineIdx);
        }
        listType = 'ol';
        currentList = true;
        listItems.push(
          <li key={`li-${lineIdx}`} className="chat-li">
            {parseInlineMarkup(orderMatch[3])}
          </li>
        );
      } else {
        flushList(lineIdx);
        if (trimmed) {
          elements.push(
            <p key={`p-${lineIdx}`} className="chat-p">
              {parseInlineMarkup(line)}
            </p>
          );
        } else {
          elements.push(<div key={`spacer-${lineIdx}`} className="chat-line-spacer" />);
        }
      }
    });

    flushList(lines.length);
    return elements;
  };

  const parseInlineMarkup = (text) => {
    if (!text) return '';
    const parts = text.split(/(\*\*.*?\*\*|\[\d+\])/g);
    return parts.map((part, index) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={index}>{part.slice(2, -2)}</strong>;
      }
      const citationMatch = part.match(/^\[(\d+)\]$/);
      if (citationMatch) {
        const refNum = parseInt(citationMatch[1], 10);
        return (
          <span
            key={index}
            className="citation-tag"
            onClick={() => handleCitationClick(refNum)}
            title={`View Source [${refNum}]`}
          >
            {refNum}
          </span>
        );
      }
      return part;
    });
  };

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMsgText = input;
    setInput('');
    setLoading(true);

    const userMessage = {
      id: Date.now(),
      text: userMsgText,
      sender: 'user',
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages((prev) => [...prev, userMessage]);

    try {
      const response = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: userMsgText })
      });

      if (!response.ok) throw new Error('API server returned an error');

      const data = await response.json();
      
      // Clean footer off raw answers to prevent double source output
      let cleanAnswer = data.answer;
      const footerIndex = cleanAnswer.indexOf('\n\n---\n**Sources:**');
      if (footerIndex !== -1) {
        cleanAnswer = cleanAnswer.substring(0, footerIndex);
      }

      const botMessage = {
        id: Date.now() + 1,
        text: cleanAnswer,
        sender: 'bot',
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        sources: data.sources || [],
        note: data.note
      };

      setMessages((prev) => [...prev, botMessage]);

      if (data.sources && data.sources.length > 0) {
        setActiveSources(data.sources);
        setIsDrawerOpen(true);
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          text: "I couldn't contact the backend service. Please make sure the FastAPI server is running.",
          sender: 'bot',
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          error: true
        }
      ]);
    } finally {
      setLoading(false);
    }
  };

  const selectSample = (query) => {
    setInput(query);
  };

  return (
    <div className="app-container">
      {/* Left Sidebar */}
      <aside className="sidebar">
        <div className="logo-section">
          <div className="logo-icon">📖</div>
          <div className="app-title">PDF RAG Bot</div>
        </div>

        <div className="sidebar-section">
          <div className="section-title">System Status</div>
          <div className="status-card">
            <div className="status-row">
              <span className="status-label">FastAPI Backend</span>
              <span className="status-value">
                <span className={`status-dot ${backendStatus}`} />
                {backendStatus === 'online' ? 'Connected' : 'Offline'}
              </span>
            </div>
            <div className="status-row">
              <span className="status-label">Indexed Chunks</span>
              <span className="status-value">{docs.collection_size}</span>
            </div>
          </div>
        </div>

        <div className="sidebar-section" style={{ flexGrow: 1, minHeight: 0 }}>
          <div className="section-title">Indexed PDF files ({docs.files.length})</div>
          <div className="file-list">
            {docs.files.length > 0 ? (
              docs.files.map((file, idx) => (
                <div key={idx} className="file-item" title={file}>
                  📄 {file}
                </div>
              ))
            ) : (
              <div className="no-files">No PDFs found. Add files to docs/ and run ingest.py</div>
            )}
          </div>
        </div>

        <div className="sidebar-section">
          <div className="section-title">Example Queries</div>
          <div className="sample-queries">
            <button className="query-btn" onClick={() => selectSample('What is the deployment process?')}>
              🚀 Deployment process?
            </button>
            <button className="query-btn" onClick={() => selectSample('How long do JWT tokens last?')}>
              🔑 JWT lifespan?
            </button>
            <button className="query-btn" onClick={() => selectSample('Which services consume payment events?')}>
              📡 payment.events consumer?
            </button>
          </div>
        </div>
      </aside>

      {/* Main Chat Pane */}
      <main className="chat-area">
        <header className="chat-header">
          <div className="header-info">
            <h2 className="header-title">Cognitive Search Chat</h2>
            <p className="header-subtitle">Strict source tracing & local model citations</p>
          </div>
          {activeSources.length > 0 && (
            <button 
              className="query-btn" 
              onClick={() => setIsDrawerOpen(!isDrawerOpen)}
              style={{ fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              📚 Sources ({activeSources.length})
            </button>
          )}
        </header>

        {/* Message scrolling panel */}
        <div className="message-list">
          {messages.map((msg) => (
            <div key={msg.id} className={`message-row ${msg.sender}`}>
              <div className="avatar">
                {msg.sender === 'user' ? '👤' : '🤖'}
              </div>
              <div className={`message-bubble ${msg.sender}`}>
                <div className="message-text">
                  {parseMarkdown(msg.text)}
                </div>
                
                {msg.sender === 'bot' && msg.sources && msg.sources.length > 0 && (
                  <details className="sources-collapse">
                    <summary className="sources-summary">📖 View References ({msg.sources.length})</summary>
                    <div className="sources-list-inline">
                      {msg.sources.map((src) => (
                        <div 
                          key={src.ref} 
                          className="source-item-inline" 
                          onClick={() => handleCitationClick(src.ref)}
                        >
                          <span className="source-ref-inline">[{src.ref}]</span>
                          <span className="source-file-inline">
                            {src.source_file} (Page {src.page})
                          </span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}

                {msg.note === 'ollama_offline' && (
                  <div className="note-box">
                    ⚠️ <strong>Model Offline:</strong> Running in retrieval-only mode. Excerpts are formatted above. Start Ollama and pull a model to enable synthesis.
                  </div>
                )}
                {msg.note === 'ollama_timeout' && (
                  <div className="note-box">
                    🕒 <strong>Timeout:</strong> Local model took too long to respond. Displaying raw retrieved context above.
                  </div>
                )}

                <div className="message-meta">
                  <span>{msg.sender === 'user' ? 'You' : 'Assistant'}</span>
                  <span>•</span>
                  <span>{msg.time}</span>
                </div>
              </div>
            </div>
          ))}

          {loading && (
            <div className="message-bubble bot">
              <div className="loading-dots">
                <span></span>
                <span></span>
                <span></span>
              </div>
              <div className="message-meta">Searching local documents...</div>
            </div>
          )}
          
          <div ref={messagesEndRef} />
        </div>

        {/* Send Input Area */}
        <footer className="input-area">
          <form onSubmit={handleSend} className="input-wrapper">
            <textarea
              className="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about your documents..."
              rows={1}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(e);
                }
              }}
            />
            <button type="submit" className="send-btn" disabled={!input.trim() || loading}>
              ✈️
            </button>
          </form>
        </footer>
      </main>

      {/* Right Drawer (Citations Details) */}
      {isDrawerOpen && activeSources.length > 0 && (
        <aside className="drawer">
          <div className="drawer-header">
            <div className="drawer-title">📖 Referenced Sources</div>
            <button className="close-btn" onClick={() => setIsDrawerOpen(false)}>✕</button>
          </div>
          <div className="drawer-content">
            {activeSources.map((src) => (
              <div 
                key={src.ref} 
                id={`source-card-${src.ref}`}
                className={`source-card ${highlightedSourceRef === src.ref ? 'highlighted' : ''}`}
                onClick={() => setHighlightedSourceRef(src.ref)}
              >
                <div className="source-card-header">
                  <div className="source-number">[{src.ref}]</div>
                  <div className="source-meta">
                    <div className="source-file-name">{src.source_file}</div>
                    <div className="source-page">Page {src.page}</div>
                  </div>
                  <div className="source-score">{Math.round(src.score * 100)}% Match</div>
                </div>
                <div className="source-excerpt">
                  "{src.excerpt}"
                </div>
              </div>
            ))}
          </div>
        </aside>
      )}
    </div>
  );
}

export default App;
