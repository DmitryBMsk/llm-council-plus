import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import TokenStats from './TokenStats';
import SearchContext from './SearchContext';
import { api } from '../api';
import { exportToMarkdown, downloadMarkdown, generateFilename } from '../utils/exportMarkdown';
import { formatDuration, formatTimestamp } from '../utils/timing';
import './ChatInterface.css';

// File size limits (in bytes)
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB for regular files
const MAX_IMAGE_SIZE = 5 * 1024 * 1024; // 5MB for images

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Real-time elapsed time display component
function RealtimeTimer({ startTime }) {
  const [elapsed, setElapsed] = useState(0);
  const [isAnimating, setIsAnimating] = useState(false);
  // Keep a stable start time without "derived state via effect" (lint rule: react-hooks/set-state-in-effect).
  // We intentionally avoid refs during render (lint rule: react-hooks/refs) by using a lazy state fallback.
  const [fallbackStartTime] = useState(() => Date.now() / 1000);
  const actualStartTime = startTime || fallbackStartTime;
  const animationTimeoutRef = useRef(null);

  useEffect(() => {
    const updateElapsed = () => {
      const now = Date.now() / 1000;
      const newElapsed = now - actualStartTime;
      setElapsed(Math.max(0, newElapsed));
      setIsAnimating(true);
      // Clear previous timeout before setting new one
      if (animationTimeoutRef.current) {
        clearTimeout(animationTimeoutRef.current);
      }
      animationTimeoutRef.current = setTimeout(() => setIsAnimating(false), 100);
    };

    updateElapsed();
    const interval = setInterval(updateElapsed, 50);

    return () => {
      clearInterval(interval);
      // Clean up the animation timeout on unmount
      if (animationTimeoutRef.current) {
        clearTimeout(animationTimeoutRef.current);
      }
    };
  }, [actualStartTime]);

  return (
    <div className="realtime-timing">
      {actualStartTime && (
        <span className="timing-start">Started: {formatTimestamp(actualStartTime)}</span>
      )}
      <span className={`timing-elapsed ${isAnimating ? 'pulse' : ''}`}>
        Elapsed: {formatDuration(elapsed) || '0.0s'}
      </span>
    </div>
  );
}

export default function ChatInterface({
  conversation,
  onSendMessage,
  onAbort,
  onUploadFile,
  isLoading,
  webSearchAvailable = false,
  tavilyEnabled = false,
  exaEnabled = false,
  duckduckgoEnabled = false,
  braveEnabled = false,
}) {
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  const [webSearchProvider, setWebSearchProvider] = useState('off'); // 'off', 'duckduckgo', 'tavily', 'exa', 'brave'
  const [driveStatus, setDriveStatus] = useState({ enabled: false, configured: false });
  const [driveUploading, setDriveUploading] = useState({});
  const [driveUploaded, setDriveUploaded] = useState({});
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);

  // Check Google Drive status on mount
  useEffect(() => {
    api.getDriveStatus()
      .then(setDriveStatus)
      .catch((err) => console.log('Drive not configured:', err));
  }, []);

  // Auto-enable web search for TTCC mode conversations
  useEffect(() => {
    if (conversation?.system_prompt && webSearchProvider === 'off') {
      // Auto-select the first available search provider
      if (duckduckgoEnabled) setWebSearchProvider('duckduckgo');
      else if (tavilyEnabled) setWebSearchProvider('tavily');
      else if (exaEnabled) setWebSearchProvider('exa');
      else if (braveEnabled) setWebSearchProvider('brave');
    }
  }, [conversation?.id]); // Only trigger on conversation change

  // Upload to Google Drive
  const uploadToDrive = async (index, userContent, assistantMessage) => {
    if (driveUploading[index]) return;

    setDriveUploading((prev) => ({ ...prev, [index]: true }));
    try {
      const md = exportToMarkdown(userContent, assistantMessage);
      const result = await api.uploadToDrive(generateFilename(index), md);
      setDriveUploaded((prev) => ({
        ...prev,
        [index]: result.file.webViewLink
      }));
    } catch (error) {
      console.error('Drive upload failed:', error);
      alert(`Failed to upload to Drive: ${error.message}`);
    } finally {
      setDriveUploading((prev) => ({ ...prev, [index]: false }));
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  // Auto-resize textarea based on content
  const adjustTextareaHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 300)}px`;
    }
  };

  useEffect(() => {
    adjustTextareaHeight();
  }, [input]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isLoading && !isUploading) {
      onSendMessage(input, attachments.length > 0 ? attachments : null, webSearchProvider);
      setInput('');
      setAttachments([]);
      // Keep webSearchProvider value for next query
    }
  };

  const handleKeyDown = (e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleFileSelect = async (e) => {
    const files = Array.from(e.target.files);
    if (files.length === 0) return;

    // Validate file sizes before uploading
    const invalidFiles = [];
    for (const file of files) {
      const isImage = file.type.startsWith('image/');
      const maxSize = isImage ? MAX_IMAGE_SIZE : MAX_FILE_SIZE;
      if (file.size > maxSize) {
        invalidFiles.push({
          name: file.name,
          size: file.size,
          maxSize,
          isImage,
        });
      }
    }

    if (invalidFiles.length > 0) {
      const messages = invalidFiles.map(
        (f) => `"${f.name}" (${formatFileSize(f.size)}) exceeds ${f.isImage ? 'image' : 'file'} limit of ${formatFileSize(f.maxSize)}`
      );
      alert(`File size limit exceeded:\n\n${messages.join('\n')}`);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      return;
    }

    setIsUploading(true);
    try {
      for (const file of files) {
        const result = await onUploadFile(file);
        setAttachments((prev) => [...prev, result]);
      }
    } catch (error) {
      console.error('File upload failed:', error);
      alert(`Failed to upload file: ${error.message}`);
    } finally {
      setIsUploading(false);
      // Clear the file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleRemoveAttachment = (index) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  };

  // Drag-and-drop handlers
  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isLoading && !isUploading) {
      setIsDragOver(true);
    }
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  };

  const handleDrop = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    if (isLoading || isUploading) return;

    const files = Array.from(e.dataTransfer.files);
    if (files.length === 0) return;

    // Filter to supported file types
    const supportedExtensions = ['.pdf', '.txt', '.md', '.mdx', '.jpg', '.jpeg', '.png', '.gif', '.webp'];
    const supportedFiles = files.filter((file) => {
      const ext = '.' + file.name.split('.').pop().toLowerCase();
      return supportedExtensions.includes(ext);
    });

    if (supportedFiles.length === 0) {
      alert('No supported files found. Supported: PDF, TXT, MD, MDX, JPG, PNG, GIF, WebP');
      return;
    }

    // Validate file sizes
    const invalidFiles = [];
    for (const file of supportedFiles) {
      const isImage = file.type.startsWith('image/');
      const maxSize = isImage ? MAX_IMAGE_SIZE : MAX_FILE_SIZE;
      if (file.size > maxSize) {
        invalidFiles.push({
          name: file.name,
          size: file.size,
          maxSize,
          isImage,
        });
      }
    }

    if (invalidFiles.length > 0) {
      const messages = invalidFiles.map(
        (f) => `"${f.name}" (${formatFileSize(f.size)}) exceeds ${f.isImage ? 'image' : 'file'} limit of ${formatFileSize(f.maxSize)}`
      );
      alert(`File size limit exceeded:\n\n${messages.join('\n')}`);
      return;
    }

    setIsUploading(true);
    try {
      for (const file of supportedFiles) {
        const result = await onUploadFile(file);
        setAttachments((prev) => [...prev, result]);
      }
    } catch (error) {
      console.error('File drop upload failed:', error);
      alert(`Failed to upload file: ${error.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  if (!conversation) {
    return (
      <div className="chat-interface">
        <div className="empty-state">
          <h2>Welcome to LLM-TTCC-TEAM-PRO</h2>
          <p>Create a new conversation to get started</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`chat-interface ${isDragOver ? 'drag-over' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {isDragOver && (
        <div className="drag-overlay">
          <div className="drag-overlay-content">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="17 8 12 3 7 8"/>
              <line x1="12" y1="3" x2="12" y2="15"/>
            </svg>
            <span>Drop files here</span>
            <span className="drag-hint">PDF, TXT, MD, MDX, JPG, PNG, GIF, WebP</span>
          </div>
        </div>
      )}
      <div className="messages-container">
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult LLM-TTCC-TEAM-PRO</p>
          </div>
        ) : (
          conversation.messages.map((msg, index) => (
            <div key={index} className="message-group">
              {msg.role === 'user' ? (
                <div className="user-message">
                  <div className="message-label">You</div>
                  <div className="message-content">
                    <div className="markdown-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>{msg.content}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="assistant-message">
                  <div className="message-label">LLM-TTCC-TEAM-PRO</div>

                  <SearchContext toolOutputs={msg.metadata?.tool_outputs || msg.tool_outputs} />

                  {/* Stage 1 */}
                  {msg.loading?.stage1 && (
                    <div className="stage-loading">
                      <div className="loading-content">
                        <div className="spinner"></div>
                        <span>Running Stage 1: Collecting individual responses... ({msg.stage1?.length || 0} received)</span>
                      </div>
                      <RealtimeTimer startTime={msg.timings?.stage1?.start} />
                    </div>
                  )}
                  {/* Show Stage1 component even while loading to display streaming responses */}
                  {msg.stage1 && msg.stage1.length > 0 && (
                    <Stage1 responses={msg.stage1} timings={msg.timings?.stage1} isStreaming={msg.loading?.stage1} />
                  )}

                  {/* Stage 2 */}
                  {msg.loading?.stage2 && (
                    <div className="stage-loading">
                      <div className="loading-content">
                        <div className="spinner"></div>
                        <span>Running Stage 2: Peer rankings...</span>
                      </div>
                      <RealtimeTimer startTime={msg.timings?.stage2?.start} />
                    </div>
                  )}
                  {msg.stage2 && (
                    <Stage2
                      rankings={msg.stage2}
                      labelToModel={msg.metadata?.label_to_model}
                      aggregateRankings={msg.metadata?.aggregate_rankings}
                      timings={msg.timings?.stage2}
                    />
                  )}

                  {/* Stage 3 */}
                  {msg.loading?.stage3 && (
                    <div className="stage-loading">
                      <div className="loading-content">
                        <div className="spinner"></div>
                        <span>Running Stage 3: Final synthesis...</span>
                      </div>
                      <RealtimeTimer startTime={msg.timings?.stage3?.start} />
                    </div>
                  )}
                  {msg.stage3 && <Stage3 finalResponse={msg.stage3} timings={msg.timings?.stage3} />}

                  {/* Token Stats - show TOON savings after Stage 3 */}
                  {msg.stage3 && msg.metadata?.token_stats && (
                    <TokenStats tokenStats={msg.metadata.token_stats} />
                  )}

                  {/* Export buttons - show when stage3 is complete */}
                  {msg.stage3 && (
                    <div className="export-actions">
                      <button
                        className="export-button"
                        onClick={() => {
                          // Find the corresponding user message (previous message)
                          const userMsg = conversation.messages[index - 1];
                          const userContent = userMsg?.content || 'Question';
                          const md = exportToMarkdown(userContent, msg);
                          downloadMarkdown(md, generateFilename(index));
                        }}
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                          <polyline points="7 10 12 15 17 10"/>
                          <line x1="12" y1="15" x2="12" y2="3"/>
                        </svg>
                        Export to MD
                      </button>

                      {/* Google Drive upload button */}
                      {driveStatus.configured && (
                        driveUploaded[index] ? (
                          <a
                            href={driveUploaded[index]}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="export-button drive-uploaded"
                          >
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <polyline points="20 6 9 17 4 12"/>
                            </svg>
                            View in Drive
                          </a>
                        ) : (
                          <button
                            className="export-button drive-button"
                            onClick={() => {
                              const userMsg = conversation.messages[index - 1];
                              const userContent = userMsg?.content || 'Question';
                              uploadToDrive(index, userContent, msg);
                            }}
                            disabled={driveUploading[index]}
                          >
                            {driveUploading[index] ? (
                              <>
                                <div className="spinner-small"></div>
                                Uploading...
                              </>
                            ) : (
                              <>
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                  <path d="M12 19V5M5 12l7-7 7 7"/>
                                </svg>
                                Upload to Drive
                              </>
                            )}
                          </button>
                        )
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>Consulting the council...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form className="input-form" onSubmit={handleSubmit}>
          {/* Attachments display */}
          {attachments.length > 0 && (
            <div className="attachments-list">
              {attachments.map((att, index) => (
                <div key={index} className={`attachment-item ${att.file_type === 'image' ? 'attachment-image' : ''}`}>
                  {att.file_type === 'image' ? (
                    <img
                      src={att.content}
                      alt={att.filename}
                      className="attachment-thumbnail"
                    />
                  ) : (
                    <span className="attachment-icon">
                      {att.file_type === 'pdf' ? '📄' : '📝'}
                    </span>
                  )}
                  <span className="attachment-name">{att.filename}</span>
                  <span className="attachment-size">
                    {att.file_type === 'image'
                      ? `(${Math.round((att.byte_size || 0) / 1024)}KB)`
                      : `(${Math.round(att.char_count / 1000)}k chars)`
                    }
                  </span>
                  <button
                    type="button"
                    className="attachment-remove"
                    onClick={() => handleRemoveAttachment(index)}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="input-row">
            {/* Hidden file input */}
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileSelect}
              accept=".pdf,.txt,.md,.mdx,.jpg,.jpeg,.png,.gif,.webp"
              multiple
              style={{ display: 'none' }}
            />

            {/* Attach button */}
            <button
              type="button"
              className="attach-button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isLoading || isUploading}
              title="Attach file (PDF, TXT, MD, MDX, JPG, PNG, GIF, WebP)"
            >
              {isUploading ? (
                <div className="spinner-small"></div>
              ) : (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                </svg>
              )}
            </button>

            <textarea
              ref={textareaRef}
              className="message-input"
              placeholder={conversation.messages.length === 0
                ? "Ask your question... (Shift+Enter for new line, Enter to send)"
                : "Ask a follow-up question... (Shift+Enter for new line, Enter to send)"
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading || isUploading}
              rows={1}
            />
            <button
              type="submit"
              className="send-button"
              disabled={!input.trim() || isLoading || isUploading}
              aria-label={conversation.messages.length === 0 ? 'Send' : 'Send follow-up'}
              title={conversation.messages.length === 0 ? 'Send' : 'Send follow-up'}
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M22 2L11 13" />
                <path d="M22 2L15 22L11 13L2 9L22 2Z" />
              </svg>
            </button>
            {webSearchAvailable && (
              <div className="web-search-dropdown" title="Select web search provider">
                <span className="dropdown-icon">🔍</span>
                <select
                  value={webSearchProvider}
                  onChange={(e) => setWebSearchProvider(e.target.value)}
                  disabled={isLoading || isUploading}
                  className="search-provider-select"
                >
                  <option value="off">Off</option>
                  {duckduckgoEnabled && <option value="duckduckgo">DuckDuckGo</option>}
                  {tavilyEnabled && <option value="tavily">Tavily</option>}
                  {exaEnabled && <option value="exa">Exa AI</option>}
                  {braveEnabled && <option value="brave">Brave</option>}
                </select>
              </div>
            )}
            {onAbort && isLoading && (
              <button
                type="button"
                className="stop-button"
                onClick={onAbort}
                title="Stop / cancel this request"
              >
                Stop
              </button>
            )}
          </div>
        </form>
    </div>
  );
}
