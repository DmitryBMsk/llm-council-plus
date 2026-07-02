import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import App from './App';
import { api } from './api';

vi.mock('./api', () => ({
  api: {
    getSetupStatus: vi.fn(),
    getAuthStatus: vi.fn(),
    getDriveStatus: vi.fn(),
    listConversations: vi.fn(),
    getConversation: vi.fn(),
    sendMessageStream: vi.fn(),
    uploadFile: vi.fn(),
    uploadToDrive: vi.fn(),
  },
}));

vi.mock('./store/authStore', () => ({
  useAuthStore: () => ({
    isSessionValid: () => true,
    login: vi.fn(),
    username: 'guest',
  }),
}));

vi.mock('./components/Sidebar', () => ({
  default: ({ conversations, onSelectConversation }) => (
    <nav>
      {conversations.map((conversation) => (
        <button
          key={conversation.id}
          type="button"
          onClick={() => onSelectConversation(conversation.id)}
        >
          {conversation.title}
        </button>
      ))}
    </nav>
  ),
}));

vi.mock('./components/ChatInterface', () => ({
  default: ({ conversation, onSendMessage, isLoading }) => {
    const messages = conversation?.messages || [];
    const assistantMessage = [...messages].reverse().find((message) => message.role === 'assistant');

    return (
      <main>
        <div data-testid="current-id">{conversation?.id || ''}</div>
        <div data-testid="loading">{String(isLoading)}</div>
        <div data-testid="message-count">{String(messages.length)}</div>
        <pre data-testid="assistant-loading">
          {JSON.stringify(assistantMessage?.loading || null)}
        </pre>
        <pre data-testid="assistant-metadata">
          {JSON.stringify(assistantMessage?.metadata || null)}
        </pre>
        <button type="button" onClick={() => onSendMessage('Question')}>
          Send
        </button>
      </main>
    );
  },
}));

vi.mock('./components/ModelSelector', () => ({
  default: () => null,
}));

vi.mock('./components/LoginScreen', () => ({
  default: () => null,
}));

vi.mock('./components/SetupWizard', () => ({
  default: () => null,
}));

vi.mock('./components/SettingsModal', () => ({
  default: () => null,
}));

vi.mock('./components/ErrorBoundary', () => ({
  default: ({ children }) => children,
}));

vi.mock('./components/Toast', () => ({
  ToastContainer: ({ toasts }) => (
    <div data-testid="toasts">
      {toasts.map((toast) => toast.message).join('|')}
    </div>
  ),
}));

const conversations = [
  { id: 'conv-a', title: 'Conversation A', created_at: '2026-01-01', message_count: 1 },
  { id: 'conv-b', title: 'Conversation B', created_at: '2026-01-02', message_count: 2 },
  { id: 'conv-c', title: 'Conversation C', created_at: '2026-01-03', message_count: 1 },
];

const conversationData = {
  'conv-a': {
    id: 'conv-a',
    messages: [{ role: 'user', content: 'A original' }],
  },
  'conv-b': {
    id: 'conv-b',
    messages: [
      { role: 'user', content: 'B original 1' },
      { role: 'assistant', stage3: { response: 'B original 2' } },
    ],
  },
  'conv-c': {
    id: 'conv-c',
    messages: [{ role: 'user', content: 'C original' }],
  },
};

function cloneConversation(id) {
  return JSON.parse(JSON.stringify(conversationData[id]));
}

function setupApiMocks() {
  api.getSetupStatus.mockResolvedValue({
    setup_required: false,
    web_search_enabled: false,
    tavily_enabled: false,
    exa_enabled: false,
    duckduckgo_enabled: false,
    brave_enabled: false,
  });
  api.getAuthStatus.mockResolvedValue({ auth_enabled: false });
  api.getDriveStatus.mockResolvedValue({ enabled: false, configured: false });
  api.listConversations.mockResolvedValue(conversations);
  api.getConversation.mockImplementation((id) => Promise.resolve(cloneConversation(id)));
}

async function renderReadyApp() {
  render(<App />);
  await screen.findByRole('button', { name: 'Conversation A' });
}

async function selectConversation(title, id) {
  fireEvent.click(screen.getByRole('button', { name: title }));
  await waitFor(() => {
    expect(screen.getByTestId('current-id')).toHaveTextContent(id);
  });
}

function setupPendingStream() {
  let onEvent;
  let resolveStream;
  let rejectStream;
  api.sendMessageStream.mockImplementation((conversationId, content, streamCallback) => {
    onEvent = streamCallback;
    return new Promise((resolve, reject) => {
      resolveStream = resolve;
      rejectStream = reject;
    });
  });

  return {
    emit(type, event = { type }) {
      onEvent(type, event);
    },
    resolve() {
      resolveStream();
    },
    reject(error) {
      rejectStream(error);
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  setupApiMocks();
});

describe('App streaming state isolation', () => {
  it('does not restore stale streaming state saved while leaving a non-active conversation', async () => {
    const stream = setupPendingStream();

    await renderReadyApp();
    await selectConversation('Conversation A', 'conv-a');

    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('true');
    });

    await selectConversation('Conversation B', 'conv-b');
    await selectConversation('Conversation C', 'conv-c');

    await act(async () => {
      stream.emit('complete');
      stream.resolve();
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
    });

    await selectConversation('Conversation B', 'conv-b');

    expect(screen.getByTestId('loading')).toHaveTextContent('false');
    expect(screen.getByTestId('message-count')).toHaveTextContent('2');
  });

  it('keeps displayed conversation messages intact and clears failed stream state on network failure', async () => {
    const stream = setupPendingStream();

    await renderReadyApp();
    await selectConversation('Conversation A', 'conv-a');

    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('true');
    });

    await selectConversation('Conversation B', 'conv-b');

    await act(async () => {
      stream.reject(new Error('network down'));
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
    });

    expect(screen.getByTestId('current-id')).toHaveTextContent('conv-b');
    expect(screen.getByTestId('message-count')).toHaveTextContent('2');
    expect(screen.getByTestId('toasts')).toHaveTextContent('Stream failed: network down');

    await selectConversation('Conversation A', 'conv-a');

    expect(screen.getByTestId('loading')).toHaveTextContent('false');
    expect(screen.getByTestId('message-count')).toHaveTextContent('1');
  });

  it('marks the assistant message errored and clears stage loading on SSE error events', async () => {
    const stream = setupPendingStream();

    await renderReadyApp();
    await selectConversation('Conversation A', 'conv-a');

    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    await act(async () => {
      stream.emit('stage1_start', { type: 'stage1_start', timestamp: 1 });
      await Promise.resolve();
    });
    expect(JSON.parse(screen.getByTestId('assistant-loading').textContent)).toMatchObject({
      stage1: true,
      stage2: false,
      stage3: false,
    });

    await act(async () => {
      stream.emit('error', { type: 'error', message: 'backend failed' });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
    });

    expect(JSON.parse(screen.getByTestId('assistant-loading').textContent)).toEqual({
      stage1: false,
      stage2: false,
      stage3: false,
    });
    expect(JSON.parse(screen.getByTestId('assistant-metadata').textContent)).toMatchObject({
      error: true,
    });
    expect(screen.getByTestId('toasts')).toHaveTextContent('Stream error: backend failed');
  });
});
