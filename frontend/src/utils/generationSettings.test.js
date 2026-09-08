import { describe, it, expect } from 'vitest';
import { validateGenerationSettings } from './generationSettings';
describe('generation settings validation', () => {
  it('accepts stage budgets and exact-model overrides', () => {
    expect(() => validateGenerationSettings({ stage1: { max_tokens: 8192 } }, { 'anthropic/fable': { continuation: { max_tokens: 16384, reasoning_max_tokens: 2048 } } })).not.toThrow();
  });
  it.each([{ max_tokens: 1 }, { max_tokens: 1.5 }, { max_tokens: 2048, reasoning_max_tokens: 2048 }, { reasoning_max_tokens: 2048, reasoning_effort: 'high' }, { reasoning_effort: 'bogus' }])('rejects invalid budget %j', budget => {
    expect(() => validateGenerationSettings({ stage1: budget })).toThrow();
  });
});
