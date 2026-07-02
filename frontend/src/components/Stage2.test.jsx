import { describe, it, expect } from 'vitest';
import { render, fireEvent, screen } from '@testing-library/react';
import Stage2 from './Stage2';

const makeRankings = (n) =>
  Array.from({ length: n }, (_, i) => ({
    model: `org/model-${i}`,
    ranking: 'FINAL RANKING:\n1. Response A',
    parsed_ranking: ['Response A'],
  }));

describe('Stage2 tab clamping', () => {
  it('does not crash when rankings shrink below the active tab index', () => {
    const { rerender } = render(<Stage2 rankings={makeRankings(5)} />);

    // Activate the last tab (index 4)
    fireEvent.click(screen.getByRole('button', { name: /model-4/ }));
    expect(screen.getAllByText('org/model-4').length).toBeGreaterThan(0);

    // Same component instance rerenders with only 2 rankings — previously
    // rankings[4] was undefined and .model dereference crashed the chat panel
    expect(() => rerender(<Stage2 rankings={makeRankings(2)} />)).not.toThrow();

    // Clamped to the last available tab
    expect(screen.getAllByText('org/model-1').length).toBeGreaterThan(0);
  });
});
