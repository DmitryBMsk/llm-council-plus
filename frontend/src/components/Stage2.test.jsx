import { describe, it, expect } from 'vitest';
import { render, fireEvent, screen, within } from '@testing-library/react';
import Stage2 from './Stage2';

describe('Stage2 aggregate without self-votes', () => {
  const labelToModel = { 'Response A': 'org/alpha', 'Response B': 'org/beta', 'Response C': 'org/gamma' };
  const rankings = [
    { model: 'org/alpha', ranking: 'FINAL RANKING:', parsed_ranking: ['Response A', 'Response B', 'Response C'] },
    { model: 'org/beta', ranking: 'FINAL RANKING:', parsed_ranking: ['Response B', 'Response A', 'Response C'] },
    { model: 'org/gamma', ranking: 'No ranking section.', parsed_ranking: [] },
  ];
  const responses = [
    { model: 'org/alpha', response: 'one two three' },
    { model: 'org/beta', response: 'one two' },
    { model: 'org/gamma', error: true, error_type: 'timeout' },
  ];
  const aggregate = (extra) => [
    { model: 'org/alpha', average_rank: 1, rankings_count: 1, ...extra },
    { model: 'org/beta', average_rank: 1, rankings_count: 1, ...extra },
    { model: 'org/gamma', average_rank: 2, rankings_count: 2, ...extra },
  ];
  const cellsOf = (judge) => within(screen.getByRole('row', { name: new RegExp(`^${judge}`) }))
    .getAllByRole('cell').map((cell) => cell.textContent);

  it('shows who ranked whom, with each judge\'s own answer left out', () => {
    render(<Stage2 rankings={rankings} labelToModel={labelToModel} responses={responses}
      aggregateRankings={aggregate({ self_votes_excluded: true })} />);

    expect(screen.getByText(/vote for its own answer is not counted/i)).toBeInTheDocument();
    expect(screen.getByRole('table', { name: /position each judge gave/i })).toBeInTheDocument();
    // Columns: alpha, beta, gamma. Positions are among the other models' answers.
    expect(cellsOf('alpha')).toEqual(['own', '1', '2']);
    expect(cellsOf('beta')).toEqual(['1', 'own', '2']);
    // A judge whose ranking could not be parsed gets an empty row, not a crash.
    expect(cellsOf('gamma')).toEqual(['—', '—', 'own']);
  });

  it('shows the length of each answer next to its rank', () => {
    render(<Stage2 rankings={rankings} labelToModel={labelToModel} responses={responses}
      aggregateRankings={aggregate({ self_votes_excluded: true })} />);

    const item = (model) => screen.getAllByText(model, { selector: '.rank-model' })[0].closest('.aggregate-item');
    expect(item('alpha')).toHaveTextContent('3 words');
    expect(item('beta')).toHaveTextContent('2 words');
    expect(item('gamma')).not.toHaveTextContent('words');
  });

  it('keeps aggregates stored before the change free of the new claims', () => {
    render(<Stage2 rankings={rankings} labelToModel={labelToModel} responses={responses}
      aggregateRankings={aggregate({})} />);

    expect(screen.queryByText(/vote for its own answer is not counted/i)).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
  });
});

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
