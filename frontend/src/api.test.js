import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api } from './api'

// ── helpers ──────────────────────────────────────────────────────────

/** Build a mock Response that resolves to `body` as JSON. */
function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  }
}

/** Build a ReadableStream from an array of string chunks. */
function makeReadableStream(chunks) {
  const encoder = new TextEncoder()
  let index = 0
  return {
    getReader() {
      return {
        read() {
          if (index < chunks.length) {
            return Promise.resolve({ done: false, value: encoder.encode(chunks[index++]) })
          }
          return Promise.resolve({ done: true, value: undefined })
        },
      }
    },
  }
}

// ── setup / teardown ─────────────────────────────────────────────────

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
  localStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ── Auth token management ────────────────────────────────────────────

describe('auth token via localStorage', () => {
  it('sends Authorization header when a valid token exists', async () => {
    const futureMs = Date.now() + 60_000
    localStorage.setItem(
      'llm-council-plus-auth',
      JSON.stringify({ state: { token: 'tok123', expiresAt: futureMs } })
    )

    fetch.mockResolvedValueOnce(jsonResponse([]))

    await api.listConversations()

    const [, opts] = fetch.mock.calls[0]
    expect(opts.headers['Authorization']).toBe('Bearer tok123')
  })

  it('omits Authorization header when token is expired', async () => {
    const pastMs = Date.now() - 60_000
    localStorage.setItem(
      'llm-council-plus-auth',
      JSON.stringify({ state: { token: 'old', expiresAt: pastMs } })
    )

    fetch.mockResolvedValueOnce(jsonResponse([]))

    await api.listConversations()

    const [, opts] = fetch.mock.calls[0]
    expect(opts.headers['Authorization']).toBeUndefined()
  })

  it('omits Authorization header when no token stored', async () => {
    fetch.mockResolvedValueOnce(jsonResponse([]))

    await api.listConversations()

    const [, opts] = fetch.mock.calls[0]
    expect(opts.headers['Authorization']).toBeUndefined()
  })
})

// ── Simple API calls ─────────────────────────────────────────────────

describe('api.getAuthStatus', () => {
  it('returns parsed JSON on success', async () => {
    fetch.mockResolvedValueOnce(jsonResponse({ auth_enabled: true }))

    const result = await api.getAuthStatus()
    expect(result).toEqual({ auth_enabled: true })
    expect(fetch).toHaveBeenCalledWith('/api/auth/status')
  })

  it('throws on non-ok response', async () => {
    fetch.mockResolvedValueOnce(jsonResponse({}, 500))

    await expect(api.getAuthStatus()).rejects.toThrow('Failed to get auth status')
  })
})

describe('api.deleteConversation', () => {
  it('calls DELETE with conversation id', async () => {
    fetch.mockResolvedValueOnce(jsonResponse({ success: true }))

    const result = await api.deleteConversation('conv-1')

    expect(result).toEqual({ success: true })
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toBe('/api/conversations/conv-1')
    expect(opts.method).toBe('DELETE')
  })
})

describe('api.sendMessage', () => {
  it('POSTs content and returns JSON', async () => {
    fetch.mockResolvedValueOnce(jsonResponse({ id: 'msg-1' }))

    const result = await api.sendMessage('conv-1', 'hello')

    expect(result).toEqual({ id: 'msg-1' })
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toBe('/api/conversations/conv-1/message')
    expect(opts.method).toBe('POST')
    expect(JSON.parse(opts.body)).toEqual({ content: 'hello' })
  })
})

// ── SSE streaming (sendMessageStream) ────────────────────────────────

describe('api.sendMessageStream', () => {
  it('parses SSE events and invokes onEvent callback', async () => {
    const events = []
    const ssePayload = [
      'data: {"type":"stage1_start","timestamp":1}\n\n',
      'data: {"type":"stage1_complete","data":[{"model":"a","response":"hi"}]}\n\n',
      'data: {"type":"complete"}\n\n',
    ]

    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: makeReadableStream(ssePayload),
    })

    await api.sendMessageStream('conv-1', 'question', (type, event) => {
      events.push({ type, event })
    })

    expect(events).toHaveLength(3)
    expect(events[0].type).toBe('stage1_start')
    expect(events[1].type).toBe('stage1_complete')
    expect(events[2].type).toBe('complete')
  })

  it('handles split chunks gracefully', async () => {
    const events = []
    // Split a single SSE message across two chunks
    const chunks = [
      'data: {"type":"sta',
      'ge1_start","timestamp":1}\n\n',
    ]

    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: makeReadableStream(chunks),
    })

    await api.sendMessageStream('conv-1', 'question', (type, event) => {
      events.push({ type, event })
    })

    expect(events).toHaveLength(1)
    expect(events[0].type).toBe('stage1_start')
  })

  it('throws on non-ok response', async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
    })

    await expect(
      api.sendMessageStream('conv-1', 'question', () => {})
    ).rejects.toThrow('Failed to send message')
  })

  it('includes attachments and web_search_provider in body', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: makeReadableStream(['data: {"type":"complete"}\n\n']),
    })

    const attachments = [{ filename: 'a.txt', content: 'hello' }]
    await api.sendMessageStream('conv-1', 'q', () => {}, attachments, 'tavily')

    const [, opts] = fetch.mock.calls[0]
    const body = JSON.parse(opts.body)
    expect(body.attachments).toEqual(attachments)
    expect(body.web_search_provider).toBe('tavily')
  })
})

// ── Error handling ───────────────────────────────────────────────────

describe('401 handling', () => {
  it('clears localStorage and reloads on 401', async () => {
    localStorage.setItem('llm-council-plus-auth', JSON.stringify({ state: { token: 'x', expiresAt: Date.now() + 60_000 } }))

    // Mock window.location.reload
    const reloadMock = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { reload: reloadMock },
      writable: true,
      configurable: true,
    })

    fetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: () => Promise.resolve({}),
    })

    await expect(api.listConversations()).rejects.toThrow('Session expired')
    expect(localStorage.getItem('llm-council-plus-auth')).toBeNull()
    expect(reloadMock).toHaveBeenCalled()
  })
})
