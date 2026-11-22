import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import Stage3 from './Stage3';

const setClipboard = (value) => Object.defineProperty(navigator, 'clipboard', { value, configurable: true });

afterEach(() => {
  setClipboard(undefined);
  delete document.execCommand;
});

describe('Stage3 copy button', () => {
  it('copies the raw final answer and confirms it', async () => {
    const writeText = vi.fn().mockResolvedValue();
    setClipboard({ writeText });
    render(<Stage3 finalResponse={{ model: 'c/chair', response: '**Final** verdict' }} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy answer' }));

    expect(writeText).toHaveBeenCalledWith('**Final** verdict');
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });

  // Opened over plain HTTP from another machine, the page has no navigator.clipboard
  it('copies through the legacy copy command when the Clipboard API is missing', async () => {
    let copied;
    document.execCommand = vi.fn(() => {
      copied = document.querySelector('textarea').value;
      return true;
    });
    render(<Stage3 finalResponse={{ model: 'c/chair', response: '**Final** verdict' }} />);
    const button = screen.getByRole('button', { name: 'Copy answer' });
    button.focus();

    fireEvent.click(button);

    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
    expect(document.execCommand).toHaveBeenCalledWith('copy');
    expect(copied).toBe('**Final** verdict');
    expect(document.querySelector('textarea')).toBeNull();
    expect(button).toHaveFocus();
  });

  it.each([
    ['refuses to copy', () => false],
    ['throws on the copy command', () => { throw new Error('blocked'); }],
  ])('says so and cleans up when the browser %s', async (_case, execCommand) => {
    document.execCommand = vi.fn(execCommand);
    render(<Stage3 finalResponse={{ model: 'c/chair', response: 'Final verdict' }} />);
    const button = screen.getByRole('button', { name: 'Copy answer' });
    button.focus();

    fireEvent.click(button);

    expect(await screen.findByRole('button', { name: 'Copy failed' })).toBeInTheDocument();
    expect(document.querySelector('textarea')).toBeNull();
    expect(button).toHaveFocus();
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
