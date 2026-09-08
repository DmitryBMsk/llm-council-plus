import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import TruncationNotice from './TruncationNotice';
describe('TruncationNotice', () => {
  it('warns for empty length-limited result; sends only on click', () => {
    const onContinue = vi.fn();
    render(<TruncationNotice result={{ model: 'anthropic/fable', response: '', finish_reason: 'length' }} onContinue={onContinue} />);
    expect(screen.getByText('Response truncated by token limit')).toBeInTheDocument();
    expect(onContinue).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /additional paid request/ }));
    expect(onContinue).toHaveBeenCalledWith('anthropic/fable');
  });
  it('distinguishes legacy inference and disables actions while busy', () => {
    render(<TruncationNotice result={{ model: 'a', usage: { completion_tokens: 8192 } }} onContinue={() => {}} busy />);
    expect(screen.getByText('May be truncated (legacy token limit)')).toBeInTheDocument();
    expect(screen.getByRole('button')).toBeDisabled();
  });
  it('does not infer when provider explicitly returned stop', () => {
    const { container } = render(<TruncationNotice result={{ model: 'a', finish_reason: 'stop', usage: { completion_tokens: 8192 } }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
