import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import ModelSelector from './ModelSelector';
import { api } from '../api';

vi.mock('../api', () => ({ api: { getModels: vi.fn(), getFreePreset: vi.fn() } }));

const LAST_USED_KEY = 'llm-council-plus-last-selection';
const catalogs = Object.fromEntries(['ollama', 'openrouter'].map((router) => [router, {
  router_type: router,
  max_models: 5,
  models: ['a', 'b'].map((suffix) => ({
    id: `${router}-${suffix}`, name: `${router}-${suffix}`, provider: router,
    contextLength: 32000, context: '32K', tier: 'free', isFree: true,
    inputPrice: 'FREE', outputPrice: 'FREE', inputPriceRaw: 0, outputPriceRaw: 0,
  })),
}]));

function saveSelection(routerType) {
  localStorage.setItem(LAST_USED_KEY, JSON.stringify({
    routerType, models: [`${routerType}-a`, `${routerType}-b`],
    chairman: `${routerType}-b`, executionMode: 'chat_ranking',
  }));
}

function routerSelect(container) {
  return [...container.querySelectorAll('select')].find((select) =>
    [...select.options].some((option) => option.value === 'openrouter'));
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  Element.prototype.scrollIntoView = vi.fn();
  api.getModels.mockImplementation(async ({ routerType }) => catalogs[routerType]);
  api.getFreePreset.mockResolvedValue({ models: [] });
});
afterEach(cleanup);

describe('provider choice and Last Used', () => {
  it.each([['ollama', 'openrouter'], ['openrouter', 'ollama']])(
    'keeps explicit %s to %s switch after models load', async (savedRouter, nextRouter) => {
      saveSelection(savedRouter);
      const { container } = render(<ModelSelector isOpen onClose={vi.fn()} onConfirm={vi.fn()} />);
      await waitFor(() => expect(routerSelect(container)).toHaveValue(savedRouter));
      await screen.findByRole('button', { name: 'Create Council (2 models)' });
      api.getModels.mockClear();

      await act(async () => {
        fireEvent.change(routerSelect(container), { target: { value: nextRouter } });
      });

      expect(routerSelect(container)).toHaveValue(nextRouter);
      expect(api.getModels.mock.calls.map(([args]) => args.routerType)).toEqual([nextRouter]);
      expect(screen.getAllByText(`${nextRouter}-a`).length).toBeGreaterThan(0);
      expect(JSON.parse(localStorage.getItem(LAST_USED_KEY)).routerType).toBe(savedRouter);
    },
  );

  it('restores saved provider and mode when reopened after a cancelled switch', async () => {
    saveSelection('ollama');
    const props = { onClose: vi.fn(), onConfirm: vi.fn() };
    const { container, rerender } = render(<ModelSelector {...props} isOpen />);
    await waitFor(() => expect(routerSelect(container)).toHaveValue('ollama'));
    await screen.findByRole('button', { name: 'Create Council (2 models)' });
    await act(async () => {
      fireEvent.change(routerSelect(container), { target: { value: 'openrouter' } });
    });
    rerender(<ModelSelector {...props} isOpen={false} />);
    rerender(<ModelSelector {...props} isOpen />);
    await waitFor(() => expect(routerSelect(container)).toHaveValue('ollama'));
    expect(container.querySelector('select option[value="chat_ranking"]').parentElement).toHaveValue('chat_ranking');
  });

  it('lets the Last Used button explicitly restore the saved provider', async () => {
    saveSelection('ollama');
    const { container } = render(<ModelSelector isOpen onClose={vi.fn()} onConfirm={vi.fn()} />);
    await waitFor(() => expect(routerSelect(container)).toHaveValue('ollama'));
    await screen.findByRole('button', { name: 'Create Council (2 models)' });
    await act(async () => {
      fireEvent.change(routerSelect(container), { target: { value: 'openrouter' } });
    });
    expect(routerSelect(container)).toHaveValue('openrouter');
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Last Used/ }));
    });
    expect(routerSelect(container)).toHaveValue('ollama');
    expect(screen.getAllByText('ollama-b').length).toBeGreaterThan(0);
  });
});
