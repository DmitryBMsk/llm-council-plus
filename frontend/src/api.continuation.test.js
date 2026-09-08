import { afterEach, expect, it, vi } from 'vitest';
import { api } from './api';
afterEach(() => vi.unstubAllGlobals());
it('preserves structured terminal failure without dropping provider detail', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => ({ detail: { message: 'Provider returned empty text', code: 'continuation_failed', status: 'failed', run_id: 'run-1' } }) }));
  await expect(api.continueResponse('a', {})).rejects.toMatchObject({ message: 'Provider returned empty text', code: 'continuation_failed', runStatus: 'failed', runId: 'run-1', status: 502 });
});
