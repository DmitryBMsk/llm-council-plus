import { useState, useEffect, useRef, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import ModelSelector from './components/ModelSelector';
import LoginScreen from './components/LoginScreen';
import SetupWizard from './components/SetupWizard';
import SettingsModal from './components/SettingsModal';
import ErrorBoundary from './components/ErrorBoundary';
import { ToastContainer } from './components/Toast';
import { useAuthStore } from './store/authStore';
import { api } from './api';
import { exportToMarkdown, generateFilename } from './utils/exportMarkdown';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showModelSelector, setShowModelSelector] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [driveStatus, setDriveStatus] = useState({ enabled: false, configured: false });
  const [authChecked, setAuthChecked] = useState(false);
  const [authEnabled, setAuthEnabled] = useState(true);
  const [setupRequired, setSetupRequired] = useState(false);
  const [setupChecked, setSetupChecked] = useState(false);
  const [webSearchAvailable, setWebSearchAvailable] = useState(false);
  const [tavilyEnabled, setTavilyEnabled] = useState(false);
  const [exaEnabled, setExaEnabled] = useState(false);
  const [duckduckgoEnabled, setDuckduckgoEnabled] = useState(false);
  const [braveEnabled, setBraveEnabled] = useState(false);
  const [toasts, setToasts] = useState([]);
  const pendingMessageRef = useRef(null);
  const toastIdRef = useRef(0);

  // Store streaming state per conversation to preserve intermediate results
  const streamingStateRef = useRef(new Map()); // Map<conversationId, {messages, isLoading}>
  // Track which conversation is currently streaming (to apply updates correctly)
  const activeStreamingConvIdRef = useRef(null);
  // Track current conversation ID for streaming comparison (ref doesn't cause re-render issues)
  const currentConversationIdRef = useRef(null);
  // Abort/cancel in-flight streaming request
  const streamAbortControllerRef = useRef(null);
  const streamAbortRequestedRef = useRef(false);

  // Helper to update streaming conversation state (handles case when user switched away)
  // FIX: Make ref the single source of truth, then sync React state from ref
  const updateStreamingState = (updater) => {
    const streamingConvId = activeStreamingConvIdRef.current;
    if (!streamingConvId) return;

    // ALWAYS update the ref first (single source of truth)
    const storedState = streamingStateRef.current.get(streamingConvId);
    if (!storedState) return;

    const fakeConv = { messages: storedState.messages };
    const updated = updater(fakeConv);
    const newMessages = updated.messages;

    streamingStateRef.current.set(streamingConvId, {
      ...storedState,
      messages: newMessages
    });

    // If we're still on the streaming conversation, sync React state from ref
    if (streamingConvId === currentConversationIdRef.current) {
      // Use functional update but read from ref to ensure consistency
      setCurrentConversation((prev) => ({
        ...prev,
        messages: newMessages
      }));
    }
  };

  // Toast notification helpers
  const addToast = useCallback((message, type = 'error', duration = 6000) => {
    const id = ++toastIdRef.current;
    setToasts((prev) => [...prev, { id, message, type, duration }]);
  }, []);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Auth state
  const { isSessionValid, login, username } = useAuthStore();
  const isAuthenticated = isSessionValid();

  // Check setup status first - if API key is missing, show wizard
  useEffect(() => {
    api.getSetupStatus()
      .then(({ setup_required, web_search_enabled, tavily_enabled, exa_enabled, duckduckgo_enabled, brave_enabled }) => {
        setSetupRequired(setup_required);
        setWebSearchAvailable(web_search_enabled || false);
        setTavilyEnabled(tavily_enabled || false);
        setExaEnabled(exa_enabled || false);
        setDuckduckgoEnabled(duckduckgo_enabled || false);
        setBraveEnabled(brave_enabled || false);
        setSetupChecked(true);
      })
      .catch((err) => {
        console.error('Failed to check setup status:', err);
        // Assume setup is not required if check fails
        setSetupChecked(true);
      });
  }, []);

  // Check auth status on mount - determine if login is required
  useEffect(() => {
    // Don't check auth until setup is done
    if (!setupChecked || setupRequired) return;

    api.getAuthStatus()
      .then(({ auth_enabled }) => {
        setAuthEnabled(auth_enabled);
        // If auth is disabled, auto-login as guest
        if (!auth_enabled && !isAuthenticated) {
          // Set guest session (no real token needed, backend will accept without auth)
          login('guest', 'no-auth-mode', Date.now() + 365 * 24 * 60 * 60 * 1000);
        }
        setAuthChecked(true);
      })
      .catch((err) => {
        console.error('Failed to check auth status:', err);
        // Default to auth enabled if check fails
        setAuthChecked(true);
      });
  }, [setupChecked, setupRequired, isAuthenticated, login]);

  // Check Google Drive status on mount
  useEffect(() => {
    api.getDriveStatus()
      .then(setDriveStatus)
      .catch((err) => console.log('Drive not configured:', err));
  }, []);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      // Check if we have streaming state for this conversation
      const streamingState = streamingStateRef.current.get(id);
      if (streamingState) {
        // Restore streaming state (has intermediate results)
        const conv = await api.getConversation(id);
        setCurrentConversation({
          ...conv,
          messages: streamingState.messages
        });
        setIsLoading(streamingState.isLoading);
        return;
      }

      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  // Load conversations on mount (only if authenticated)
  useEffect(() => {
    if (!isAuthenticated) return;

    let cancelled = false;
    api.listConversations()
      .then((convs) => {
        if (!cancelled) setConversations(convs);
      })
      .catch((error) => {
        console.error('Failed to load conversations:', error);
      });

    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  // Keep ref in sync with state for use in callbacks
  useEffect(() => {
    currentConversationIdRef.current = currentConversationId;
  }, [currentConversationId]);

  // Load conversation details when selected
  useEffect(() => {
    if (currentConversationId) {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const handleNewConversation = () => {
    // Show model selector modal instead of creating directly
    setShowModelSelector(true);
  };

  const handleModelSelectionConfirm = async ({ models, chairman, executionMode, routerType, systemPrompt }) => {
    try {
      const newConv = await api.createConversation({ models, chairman, executionMode, routerType, username, systemPrompt });
      setConversations([
        {
          id: newConv.id,
          created_at: newConv.created_at,
          title: newConv.title,
          message_count: 0,
          username: newConv.username
        },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
      setShowModelSelector(false);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    // Save current streaming state before switching
    if (currentConversationId && isLoading && currentConversation) {
      streamingStateRef.current.set(currentConversationId, {
        messages: currentConversation.messages,
        isLoading: true
      });
    }
    setCurrentConversationId(id);
  };

  const handleDeleteConversation = async (id) => {
    try {
      await api.deleteConversation(id);
      // If deleted conversation was current, clear it
      if (id === currentConversationId) {
        setCurrentConversationId(null);
        setCurrentConversation(null);
      }
      // Reload conversations list
      loadConversations();
    } catch (error) {
      console.error('Failed to delete conversation:', error);
      alert('Failed to delete conversation');
    }
  };

  const handleDeleteAllConversations = async () => {
    try {
      await api.deleteAllConversations();
      setCurrentConversationId(null);
      setCurrentConversation(null);
      loadConversations();
    } catch (error) {
      console.error('Failed to delete all conversations:', error);
      alert('Failed to delete all conversations');
    }
  };

  // Feature 5: Update conversation title
  const handleUpdateTitle = async (conversationId, newTitle) => {
    try {
      await api.updateConversationTitle(conversationId, newTitle);
      // Update local state
      setConversations(prevConvs =>
        prevConvs.map(conv =>
          conv.id === conversationId ? { ...conv, title: newTitle } : conv
        )
      );
      // Update current conversation if it's the one being edited
      if (currentConversation?.id === conversationId) {
        setCurrentConversation(prev => ({ ...prev, title: newTitle }));
      }
    } catch (error) {
      console.error('Failed to update title:', error);
      alert('Failed to update conversation title');
    }
  };

  const handleSendMessage = async (content, attachments = null, webSearchProvider = 'off') => {
    if (!currentConversationId) return;

    setIsLoading(true);
    streamAbortRequestedRef.current = false;
    streamAbortControllerRef.current = new AbortController();
    // Store user content for auto-upload
    pendingMessageRef.current = content;
    // Track which conversation is streaming
    activeStreamingConvIdRef.current = currentConversationId;

    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        timings: {
          stage1: { start: null, end: null, duration: null },
          stage2: { start: null, end: null, duration: null },
          stage3: { start: null, end: null, duration: null },
        },
        loading: {
          stage1: false,
          stage2: false,
          stage3: false,
        },
      };

      // Add the partial assistant message
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));

      // Initialize streaming state for this conversation
      streamingStateRef.current.set(currentConversationId, {
        messages: [...currentConversation.messages, userMessage, assistantMessage],
        isLoading: true
      });

      // Send message with streaming (pass attachments if any)
      await api.sendMessageStream(currentConversationId, content, (eventType, event) => {
        switch (eventType) {
          case 'tool_outputs':
            updateStreamingState((prev) => {
              const lastIdx = prev.messages.length - 1;
              const lastMsg = prev.messages[lastIdx];
              if (!lastMsg || lastMsg.role !== 'assistant') return prev;
              const currentMetadata = lastMsg.metadata || {};
              const newLastMsg = {
                ...lastMsg,
                metadata: {
                  ...currentMetadata,
                  tool_outputs: event.data || [],
                },
              };
              return { ...prev, messages: [...prev.messages.slice(0, -1), newLastMsg] };
            });
            break;

          case 'stage1_start':
            updateStreamingState((prev) => {
              const lastIdx = prev.messages.length - 1;
              const lastMsg = prev.messages[lastIdx];
              const currentTimings = lastMsg.timings || {};
              const currentLoading = lastMsg.loading || {};
              // Create NEW message object (immutable update)
              const newLastMsg = {
                ...lastMsg,
                stage1: [],
                loading: { ...currentLoading, stage1: true },
                timings: {
                  ...currentTimings,
                  stage1: { ...(currentTimings.stage1 || {}), start: event.timestamp || Date.now() / 1000 }
                }
              };
              return { ...prev, messages: [...prev.messages.slice(0, -1), newLastMsg] };
            });
            break;

          case 'stage1_model_response':
            // Add individual model response to stage1 array as it arrives
            // Guard against malformed events
            if (!event?.data?.model) {
              console.warn('Received stage1_model_response without model data:', event);
              break;
            }
            // Show toast notification for errors (timeout, rate limit, etc.)
            if (event.data.error) {
              const modelName = event.data.model.split('/')[1] || event.data.model;
              const errorType = event.data.error_type || 'unknown';
              const errorMessages = {
                timeout: `${modelName}: Request timed out`,
                stage_timeout: `${modelName}: Stage timeout (too slow)`,
                rate_limit: `${modelName}: Rate limited`,
                auth: `${modelName}: Authentication error`,
                connection: `${modelName}: Connection error`,
                empty: `${modelName}: Empty response`,
              };
              addToast(errorMessages[errorType] || `${modelName}: ${event.data.error_message || 'Error'}`, 'warning');
            }
            updateStreamingState((prev) => {
              const lastIdx = prev.messages.length - 1;
              const lastMsg = prev.messages[lastIdx];
              // Check if this model already exists (prevent duplicates)
              const existingModels = (lastMsg.stage1 || []).map(r => r.model);
              if (existingModels.includes(event.data.model)) {
                return prev; // No change needed
              }
              // Create NEW message object (immutable update)
              const newLastMsg = {
                ...lastMsg,
                stage1: [...(lastMsg.stage1 || []), event.data]
              };
              return { ...prev, messages: [...prev.messages.slice(0, -1), newLastMsg] };
            });
            break;

          case 'stage1_complete':
            updateStreamingState((prev) => {
              const lastIdx = prev.messages.length - 1;
              const lastMsg = prev.messages[lastIdx];
              const currentTimings = lastMsg.timings || {};
              const currentLoading = lastMsg.loading || {};
              const stage1Timings = currentTimings.stage1 || {};
              // Create NEW message object (immutable update)
              const newLastMsg = {
                ...lastMsg,
                stage1: event.data,
                loading: { ...currentLoading, stage1: false },
                timings: {
                  ...currentTimings,
                  stage1: {
                    ...stage1Timings,
                    end: event.timestamp || stage1Timings.end,
                    duration: event.duration !== undefined ? event.duration : stage1Timings.duration
                  }
                }
              };
              return { ...prev, messages: [...prev.messages.slice(0, -1), newLastMsg] };
            });
            break;

          case 'stage2_start':
            updateStreamingState((prev) => {
              const lastIdx = prev.messages.length - 1;
              const lastMsg = prev.messages[lastIdx];
              const currentTimings = lastMsg.timings || {};
              const currentLoading = lastMsg.loading || {};
              // Create NEW message object (immutable update)
              const newLastMsg = {
                ...lastMsg,
                loading: { ...currentLoading, stage2: true },
                timings: {
                  ...currentTimings,
                  stage2: { ...(currentTimings.stage2 || {}), start: event.timestamp || Date.now() / 1000 }
                }
              };
              return { ...prev, messages: [...prev.messages.slice(0, -1), newLastMsg] };
            });
            break;

          case 'stage2_complete':
            updateStreamingState((prev) => {
              const lastIdx = prev.messages.length - 1;
              const lastMsg = prev.messages[lastIdx];
              const currentTimings = lastMsg.timings || {};
              const currentLoading = lastMsg.loading || {};
              const stage2Timings = currentTimings.stage2 || {};
              // Create NEW message object (immutable update)
              const newLastMsg = {
                ...lastMsg,
                stage2: event.data,
                metadata: event.metadata,
                loading: { ...currentLoading, stage2: false },
                timings: {
                  ...currentTimings,
                  stage2: {
                    ...stage2Timings,
                    end: event.timestamp || stage2Timings.end,
                    duration: event.duration !== undefined ? event.duration : stage2Timings.duration
                  }
                }
              };
              return { ...prev, messages: [...prev.messages.slice(0, -1), newLastMsg] };
            });
            break;

          case 'stage3_start':
            updateStreamingState((prev) => {
              const lastIdx = prev.messages.length - 1;
              const lastMsg = prev.messages[lastIdx];
              const currentTimings = lastMsg.timings || {};
              const currentLoading = lastMsg.loading || {};
              // Create NEW message object (immutable update)
              const newLastMsg = {
                ...lastMsg,
                loading: { ...currentLoading, stage3: true },
                timings: {
                  ...currentTimings,
                  stage3: { ...(currentTimings.stage3 || {}), start: event.timestamp || Date.now() / 1000 }
                }
              };
              return { ...prev, messages: [...prev.messages.slice(0, -1), newLastMsg] };
            });
            break;

          case 'stage3_complete':
            updateStreamingState((prev) => {
              const lastIdx = prev.messages.length - 1;
              const lastMsg = prev.messages[lastIdx];
              const currentTimings = lastMsg.timings || {};
              const currentLoading = lastMsg.loading || {};
              const stage3Timings = currentTimings.stage3 || {};
              // Create NEW message object (immutable update)
              const newLastMsg = {
                ...lastMsg,
                stage3: event.data,
                loading: { ...currentLoading, stage3: false },
                timings: {
                  ...currentTimings,
                  stage3: {
                    ...stage3Timings,
                    end: event.timestamp || stage3Timings.end,
                    duration: event.duration !== undefined ? event.duration : stage3Timings.duration
                  }
                }
              };

              // Auto-upload to Google Drive if configured
              if (driveStatus.configured && pendingMessageRef.current) {
                const userContent = pendingMessageRef.current;
                const msgIndex = prev.messages.length - 1;
                const md = exportToMarkdown(userContent, newLastMsg);
                api.uploadToDrive(generateFilename(msgIndex), md)
                  .then((result) => {
                    console.log('Auto-uploaded to Drive:', result.file.webViewLink);
                  })
                  .catch((err) => {
                    console.error('Auto-upload to Drive failed:', err);
                  });
              }

              return { ...prev, messages: [...prev.messages.slice(0, -1), newLastMsg] };
            });
            break;

          case 'token_stats':
            // Update metadata with token stats from TOON encoding
            updateStreamingState((prev) => {
              const lastIdx = prev.messages.length - 1;
              const lastMsg = prev.messages[lastIdx];
              const currentMetadata = lastMsg.metadata || {};
              // Create NEW message object (immutable update)
              const newLastMsg = {
                ...lastMsg,
                metadata: { ...currentMetadata, token_stats: event.data }
              };
              return { ...prev, messages: [...prev.messages.slice(0, -1), newLastMsg] };
            });
            break;

          case 'title_complete':
            // Reload conversations to get updated title
            loadConversations();
            break;

          case 'complete': {
            // Stream complete, clear streaming state
            const streamingConvId = activeStreamingConvIdRef.current;
            if (streamingConvId) {
              streamingStateRef.current.delete(streamingConvId);
            }
            activeStreamingConvIdRef.current = null;
            streamAbortControllerRef.current = null;
            // Reload conversations list
            loadConversations();
            setIsLoading(false);
            break;
          }

          case 'error': {
            console.error('Stream error:', event.message);
            addToast(`Stream error: ${event.message || 'Unknown error'}`, 'error');
            // Clear streaming state on error
            const streamingConvId = activeStreamingConvIdRef.current;
            if (streamingConvId) {
              streamingStateRef.current.delete(streamingConvId);
            }
            activeStreamingConvIdRef.current = null;
            streamAbortControllerRef.current = null;
            setIsLoading(false);
            break;
          }

          default:
            console.log('Unknown event type:', eventType);
        }
      }, attachments, webSearchProvider, { signal: streamAbortControllerRef.current.signal });
    } catch (error) {
      // Handle user-initiated abort (Stop button)
      if (error?.name === 'AbortError' || streamAbortRequestedRef.current) {
        addToast('Cancelled', 'warning', 2500);
        updateStreamingState((prev) => {
          const lastIdx = prev.messages.length - 1;
          const lastMsg = prev.messages[lastIdx];
          if (!lastMsg || lastMsg.role !== 'assistant') return prev;
          const currentMetadata = lastMsg.metadata || {};
          const currentLoading = lastMsg.loading || {};
          const newLastMsg = {
            ...lastMsg,
            metadata: { ...currentMetadata, aborted: true },
            loading: { ...currentLoading, stage1: false, stage2: false, stage3: false },
          };
          return { ...prev, messages: [...prev.messages.slice(0, -1), newLastMsg] };
        });
        // Clear streaming state
        const streamingConvId = activeStreamingConvIdRef.current;
        if (streamingConvId) {
          streamingStateRef.current.delete(streamingConvId);
        }
        activeStreamingConvIdRef.current = null;
        streamAbortControllerRef.current = null;
        streamAbortRequestedRef.current = false;
        setIsLoading(false);
        // Reload conversation list (server may have saved partial)
        setTimeout(loadConversations, 400);
        return;
      }

      console.error('Failed to send message:', error);
      // Remove optimistic messages on error
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -2),
      }));
      streamAbortControllerRef.current = null;
      setIsLoading(false);
    }
  };

  const handleAbortStream = () => {
    if (!isLoading) return;
    streamAbortRequestedRef.current = true;
    try {
      streamAbortControllerRef.current?.abort();
    } catch (e) {
      console.error('Failed to abort stream:', e);
    }
  };

  // Show loading while checking setup/auth status
  if (!setupChecked) {
    return (
      <div className="app" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div>Loading...</div>
      </div>
    );
  }

  // Show setup wizard if API key is not configured
  if (setupRequired) {
    return <SetupWizard onComplete={() => window.location.reload()} />;
  }

  // Show loading while checking auth status
  if (!authChecked) {
    return (
      <div className="app" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div>Loading...</div>
      </div>
    );
  }

  // Show login screen if auth is enabled and not authenticated
  if (authEnabled && !isAuthenticated) {
    return <LoginScreen onLogin={login} />;
  }

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onOpenSettings={() => setShowSettings(true)}
        onDeleteConversation={handleDeleteConversation}
        onDeleteAllConversations={handleDeleteAllConversations}
        onUpdateTitle={handleUpdateTitle}
      />
      <ErrorBoundary>
        <ChatInterface
          conversation={currentConversation}
          onSendMessage={handleSendMessage}
          onAbort={handleAbortStream}
          onUploadFile={api.uploadFile}
          isLoading={isLoading}
          webSearchAvailable={webSearchAvailable}
          tavilyEnabled={tavilyEnabled}
          exaEnabled={exaEnabled}
          duckduckgoEnabled={duckduckgoEnabled}
          braveEnabled={braveEnabled}
        />
      </ErrorBoundary>
      <ModelSelector
        isOpen={showModelSelector}
        onClose={() => setShowModelSelector(false)}
        onConfirm={handleModelSelectionConfirm}
      />
      <SettingsModal
        isOpen={showSettings}
        onClose={() => setShowSettings(false)}
      />
      <ToastContainer toasts={toasts} onRemove={removeToast} />
    </div>
  );
}

export default App;
