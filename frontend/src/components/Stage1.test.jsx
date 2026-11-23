import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import Stage1 from './Stage1';

const RETRY = 'Retry model (additional paid request)';
const responses = [
  { model: 'a/alpha', error: true, error_type: 'timeout', error_message: 'Request timed out' },
  { model: 'b/beta', response: 'Beta draft' },
];

describe('Stage1 retry of a failed model', () => {
  it('asks to retry the failed model shown in the error panel', () => {
    const onRetry = vi.fn();
    render(<Stage1 responses={responses} onRetry={onRetry} />);

    fireEvent.click(screen.getByRole('button', { name: RETRY }));

    expect(onRetry).toHaveBeenCalledWith('a/alpha');
  });

  it('is disabled while a run or continuation is busy', () => {
    const onRetry = vi.fn();
    render(<Stage1 responses={responses} onRetry={onRetry} busy />);

    const button = screen.getByRole('button', { name: RETRY });
    fireEvent.click(button);

    expect(button).toBeDisabled();
    expect(onRetry).not.toHaveBeenCalled();
  });

  it('is not offered for a model that answered', () => {
    render(<Stage1 responses={responses} onRetry={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'beta' }));

    expect(screen.getByText('Beta draft')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: RETRY })).toBeNull();
  });
});
