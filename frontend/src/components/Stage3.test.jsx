import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import Stage3 from './Stage3';

const setClipboard = (value) => Object.defineProperty(navigator, 'clipboard', { value, configurable: true });

afterEach(() => setClipboard(undefined));

describe('Stage3 copy button', () => {
  it('copies the raw final answer and confirms it', async () => {
    const writeText = vi.fn().mockResolvedValue();
    setClipboard({ writeText });
    render(<Stage3 finalResponse={{ model: 'c/chair', response: '**Final** verdict' }} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy answer' }));

    expect(writeText).toHaveBeenCalledWith('**Final** verdict');
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });

  it('says so when the browser gives no clipboard access', async () => {
    render(<Stage3 finalResponse={{ model: 'c/chair', response: 'Final verdict' }} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy answer' }));

    expect(await screen.findByRole('button', { name: 'Copy failed' })).toBeInTheDocument();
  });

  // A token-limited answer whose budget went to reasoning arrives as '' or null
  it.each([' ', null])('is not offered when the answer has no text (%j)', (response) => {
    render(<Stage3 finalResponse={{ model: 'c/chair', response, truncated: true }} />);

    expect(screen.queryByRole('button', { name: 'Copy answer' })).toBeNull();
    expect(screen.getByText('Chairman: chair')).toBeInTheDocument();
  });
});

describe('Stage3 failed synthesis', () => {
  it('is shown as an error, not as a chairman answer', () => {
    render(<Stage3 finalResponse={{
      model: 'c/chair',
      error: true,
      response: "Error: Unable to generate final synthesis. Chairman model 'c/chair' and all 2 fallback models failed to respond.",
      tried_fallbacks: ['a/alpha', 'b/beta'],
    }} />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Final synthesis failed');
    expect(alert).toHaveTextContent("Unable to generate final synthesis. Chairman model 'c/chair'");
    expect(alert).toHaveTextContent('Fallbacks tried: alpha, beta');
    expect(alert).not.toHaveTextContent('Error:');
    expect(screen.queryByText(/^Chairman:/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Copy answer' })).toBeNull();
  });
});
