import { afterEach, expect, it, vi } from 'vitest';
import { api } from './api';
afterEach(() => vi.unstubAllGlobals());
it('preserves structured terminal failure without dropping provider detail', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => ({ detail: { message: 'Provider returned empty text', code: 'continuation_failed', status: 'failed', run_id: 'run-1' } }) }));
  await expect(api.continueResponse('a', {})).rejects.toMatchObject({ message: 'Provider returned empty text', code: 'continuation_failed', runStatus: 'failed', runId: 'run-1', status: 502 });
});
it.each(['retry-model', 'regenerate'])('posts a %s rerun to its own route', async (action) => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ stage1: [] }) });
  vi.stubGlobal('fetch', fetch);
  await expect(api.continueResponse('a', { message_index: 1 }, action)).resolves.toEqual({ stage1: [] });
  expect(fetch.mock.calls[0][0]).toMatch(new RegExp(`/api/conversations/a/${action}$`));
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ message_index: 1 });
});
