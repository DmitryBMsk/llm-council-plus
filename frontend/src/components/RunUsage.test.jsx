import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import RunUsage, { RowUsage } from './RunUsage';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';

const providerUsage = (overrides) => ({
  totals: { prompt_tokens: 1200, completion_tokens: 345, total_tokens: 1545, provider_cost: 0.0123 },
  coverage: { prompt_tokens: 3, completion_tokens: 3, total_tokens: 3, provider_cost: 3 },
  attempts: 3,
  complete: true,
  scope: 'observed_provider_attempts',
  ...overrides,
});

const summaryOf = (message) => {
  render(<RunUsage message={message} />);
  return screen.queryByRole('group', { name: 'Run usage' });
};

describe('RunUsage', () => {
  it('shows the token and cost totals of a fully reported run', () => {
    const summary = summaryOf({ metadata: { provider_usage: providerUsage() } });

    expect(summary).toHaveTextContent('Prompt tokens 1,200');
    expect(summary).toHaveTextContent('Completion tokens 345');
    expect(summary).toHaveTextContent('Cost $0.0123');
    expect(summary).not.toHaveTextContent('calls');
    expect(summary).not.toHaveTextContent('Stage responses only');
  });

  it('says how many calls reported a figure and never shows a missing one as zero', () => {
    const summary = summaryOf({
      metadata: {
        provider_usage: providerUsage({
          totals: { prompt_tokens: 800, completion_tokens: 200, total_tokens: 1000, provider_cost: null },
          coverage: { prompt_tokens: 2, completion_tokens: 2, total_tokens: 2, provider_cost: 0 },
          complete: false,
        }),
      },
    });

    expect(summary).toHaveTextContent('Prompt tokens 800 (reported by 2 of 3 calls)');
    expect(summary).toHaveTextContent('Completion tokens 200 (reported by 2 of 3 calls)');
    expect(summary).toHaveTextContent('Cost not reported');
    expect(summary.textContent).not.toMatch(/\$0|\b0 tokens/);
  });

  it('shows tokens and "cost not reported" for an Ollama run', () => {
    const summary = summaryOf({
      metadata: {
        provider_usage: providerUsage({
          totals: { prompt_tokens: 60, completion_tokens: 30, total_tokens: 90, provider_cost: null },
          coverage: { prompt_tokens: 3, completion_tokens: 3, total_tokens: 3, provider_cost: 0 },
          complete: false,
        }),
      },
    });

    expect(summary).toHaveTextContent('Prompt tokens 60');
    expect(summary).toHaveTextContent('Cost not reported');
    expect(summary).not.toHaveTextContent('calls');
  });

  it('shows a cost the provider reported as zero', () => {
    const summary = summaryOf({
      metadata: { provider_usage: providerUsage({ totals: { prompt_tokens: 60, completion_tokens: 30, provider_cost: 0 } }) },
    });

    expect(summary).toHaveTextContent('Cost $0.00');
  });

  it('sums the stage rows of a message saved without a summary and says so', () => {
    const summary = summaryOf({
      stage1: [
        { model: 'a/one', usage: { prompt_tokens: 100, completion_tokens: 50, cost: 0.002 } },
        { model: 'a/two', error: true },
      ],
      stage2: [{ model: 'a/one', usage: { prompt_tokens: 300, completion_tokens: 20 } }],
      stage3: { model: 'c/chair', usage: { prompt_tokens: 400, completion_tokens: 60, cost: 0.003 } },
      metadata: {},
    });

    expect(summary).toHaveTextContent('Prompt tokens 800 (reported by 3 of 4 calls)');
    expect(summary).toHaveTextContent('Completion tokens 130');
    expect(summary).toHaveTextContent('Cost $0.0050 (reported by 2 of 4 calls)');
    expect(summary).toHaveTextContent('Stage responses only');
  });

  it('shows nothing for a message without any usage', () => {
    expect(summaryOf({ stage1: [{ model: 'a/one', response: 'answer' }], metadata: { token_stats: { total: { saved_percent: 30 } } } })).toBeNull();
  });

  it('keeps the TOON saving as a secondary line only from 1%', () => {
    const toon = (saved_percent) => ({ total: { json_tokens: 17000, toon_tokens: 15000, saved_percent } });
    const { rerender } = render(<RunUsage message={{ metadata: { provider_usage: providerUsage(), token_stats: toon(11.8) } }} />);
    expect(screen.getByRole('group', { name: 'Run usage' })).toHaveTextContent('TOON encoding saved about 12% (17,000 → 15,000 tokens, an estimate, not billing)');

    rerender(<RunUsage message={{ metadata: { provider_usage: providerUsage(), token_stats: toon(0.4) } }} />);
    expect(screen.getByRole('group', { name: 'Run usage' })).not.toHaveTextContent('TOON');
  });
});

describe('RowUsage', () => {
  it('shows tokens, and cost only when the provider reported it', () => {
    const { container, rerender } = render(<RowUsage usage={{ prompt_tokens: 2000, completion_tokens: 10 }} />);
    expect(container).toHaveTextContent('2,000 prompt tokens · 10 completion tokens');
    expect(container.textContent).not.toContain('$');

    rerender(<RowUsage usage={{ prompt_tokens: 2000, completion_tokens: 10, cost: 0.00002 }} />);
    expect(container).toHaveTextContent('$0.00002');

    rerender(<RowUsage />);
    expect(container).toBeEmptyDOMElement();
  });

  it('appears in each stage beside the model that produced the row', () => {
    const usage = { prompt_tokens: 20, completion_tokens: 10 };
    const row = '20 prompt tokens · 10 completion tokens';

    const stage1 = render(<Stage1 responses={[{ model: 'a/one', response: 'answer', usage }]} />);
    expect(stage1.container.querySelector('.model-name')).toHaveTextContent(row);
    const stage2 = render(<Stage2 rankings={[{ model: 'a/one', ranking: 'FINAL RANKING:\n1. Response A', usage }]} />);
    expect(stage2.container.querySelector('.ranking-model')).toHaveTextContent(row);
    const stage3 = render(<Stage3 finalResponse={{ model: 'c/chair', response: 'final', usage }} />);
    expect(stage3.container.querySelector('.chairman-label')).toHaveTextContent(row);
  });
});
