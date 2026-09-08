import { describe, it, expect, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import ChatInterface from './ChatInterface';
vi.mock('../api', () => ({ api: { getDriveStatus: () => Promise.resolve({}) } }));
Element.prototype.scrollIntoView = vi.fn();
const conv = id => ({ id, messages: [] });
describe('conversation drafts', () => {
  it('isolates and restores drafts and late uploads across switches', async () => {
    let finishUpload;
    const upload = vi.fn(() => new Promise(resolve => { finishUpload = resolve; }));
    const props = { onUploadFile: upload, onSendMessage: vi.fn(), isLoading: false };
    const { rerender, container } = render(<ChatInterface {...props} conversation={conv('a')} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'draft A' } });
    fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [new File(['x'], 'a.txt', { type: 'text/plain' })] } });
    rerender(<ChatInterface {...props} conversation={conv('b')} />);
    expect(screen.getByRole('textbox')).toHaveValue('');
    expect(screen.getByRole('textbox')).toBeEnabled();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'draft B' } });
    await act(async () => finishUpload({ filename: 'a.txt', content: 'x', char_count: 1 }));
    expect(screen.queryByText('a.txt')).not.toBeInTheDocument();
    rerender(<ChatInterface {...props} conversation={conv('a')} />);
    expect(screen.getByRole('textbox')).toHaveValue('draft A');
    expect(screen.getByText('a.txt')).toBeInTheDocument();
    rerender(<ChatInterface {...props} conversation={conv('b')} />);
    expect(screen.getByRole('textbox')).toHaveValue('draft B');
  });
});
