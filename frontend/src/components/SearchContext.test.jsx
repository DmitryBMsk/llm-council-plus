import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import SearchContext from './SearchContext';

describe('search failures', () => {
  it.each([
    { tool: 'tavily_search', result: '', status: 'error', error: { status_code: 400, message: 'Bad query' } },
    { tool: 'tavily_search', result: JSON.stringify("HTTPError('400 Bad Request')") },
  ])('shows failure without counting it as a source', (output) => {
    render(<SearchContext toolOutputs={[output]} />);
    expect(screen.getByRole('status')).toHaveTextContent('Tavily: Search unavailable');
    expect(screen.queryByText('1 source')).not.toBeInTheDocument();
  });
});
