import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, waitFor } from '@testing-library/react';
import ChatInterface from './ChatInterface';

vi.mock('../api', () => ({
  api: {
    getDriveStatus: vi.fn().mockResolvedValue({ enabled: false, configured: false }),
    uploadToDrive: vi.fn(),
  },
}));

const MIB = 1024 * 1024;

function sizedFile(name, type, size) {
  const file = new File(['fixture'], name, { type });
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

function renderChat() {
  const props = {
    conversation: { id: 'limit-test', messages: [] },
    onSendMessage: vi.fn(),
    onAbort: vi.fn(),
    onUploadFile: vi.fn(),
    isLoading: false,
    addToast: vi.fn(),
  };
  const rendered = render(<ChatInterface {...props} />);
  return { ...rendered, ...props };
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

describe('attachment size limits', () => {
  it('accepts an exact 20 MiB image selected with the file picker', async () => {
    const { container, onUploadFile } = renderChat();
    const file = sizedFile('exact.png', 'image/png', 20 * MIB);
    onUploadFile.mockResolvedValue({
      filename: file.name,
      file_type: 'image',
      content: 'data:image/png;base64,AA==',
      mime_type: file.type,
      byte_size: file.size,
      char_count: 0,
    });

    fireEvent.change(container.querySelector('input[type="file"]'), {
      target: { files: [file] },
    });

    await waitFor(() => expect(onUploadFile).toHaveBeenCalledWith(file));
  });

  it('accepts an image above the old 5 MiB cap through drag and drop', async () => {
    const { container, onUploadFile } = renderChat();
    const file = sizedFile('six.png', 'image/png', 6 * MIB);
    onUploadFile.mockResolvedValue({
      filename: file.name,
      file_type: 'image',
      content: 'data:image/png;base64,AA==',
      mime_type: file.type,
      byte_size: file.size,
      char_count: 0,
    });

    fireEvent.drop(container.querySelector('.chat-interface'), {
      dataTransfer: { files: [file] },
    });

    await waitFor(() => expect(onUploadFile).toHaveBeenCalledWith(file));
  });

  it('rejects an image one byte over 20 MiB before upload', async () => {
    const { container, onUploadFile, addToast } = renderChat();
    const file = sizedFile('too-large.png', 'image/png', 20 * MIB + 1);

    fireEvent.change(container.querySelector('input[type="file"]'), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(onUploadFile).not.toHaveBeenCalled();
      expect(addToast).toHaveBeenCalledWith(
        expect.stringContaining('image limit of 20.0 MB'),
        'warning',
      );
    });
  });

  it('rejects an ordinary file one byte over 10 MiB on drop', async () => {
    const { container, onUploadFile, addToast } = renderChat();
    const file = sizedFile('too-large.txt', 'text/plain', 10 * MIB + 1);

    fireEvent.drop(container.querySelector('.chat-interface'), {
      dataTransfer: { files: [file] },
    });

    await waitFor(() => {
      expect(onUploadFile).not.toHaveBeenCalled();
      expect(addToast).toHaveBeenCalledWith(
        expect.stringContaining('file limit of 10.0 MB'),
        'warning',
      );
    });
  });
});

describe('answer-first layout', () => {
  const answered = {
    role: 'assistant',
    stage1: [
      { model: 'a/alpha', response: 'Alpha draft' },
      { model: 'b/beta', response: 'Beta draft' },
    ],
    stage2: [{ model: 'a/alpha', ranking: 'FINAL RANKING:\n1. Response B', parsed_ranking: ['Response B'] }],
    stage3: { model: 'c/chair', response: 'Final verdict' },
    metadata: {
      label_to_model: { 'Response A': 'a/alpha', 'Response B': 'b/beta' },
      aggregate_rankings: [{ model: 'b/beta', average_rank: 1, rankings_count: 1 }],
    },
  };
  const renderMessage = (message) => render(
    <ChatInterface conversation={{ id: 'layout', messages: [{ role: 'user', content: 'Q' }, message] }} />,
  );

  it('shows the final answer before the stages and collapses stages 1-2', () => {
    const { getByText } = renderMessage(answered);
    const answer = getByText('Final verdict');
    const draft = getByText('Alpha draft');

    expect(answer).toBeVisible();
    expect(answer.compareDocumentPosition(draft) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(draft).not.toBeVisible();
    expect(getByText('Stage 2: Peer Rankings')).not.toBeVisible();

    fireEvent.click(getByText(/How the council decided/));
    expect(draft).toBeVisible();
  });

  it('counts only the models that answered in the council summary', () => {
    const { getByText } = renderMessage({
      ...answered,
      stage1: [answered.stage1[0], { model: 'b/beta', error: true, error_type: 'timeout', error_message: 'Timed out' }],
    });

    expect(getByText(/How the council decided/)).toHaveTextContent('1 response · top-ranked: beta');
  });

  it('reports a tie instead of naming one top-ranked model', () => {
    const { getByText } = renderMessage({
      ...answered,
      metadata: {
        ...answered.metadata,
        aggregate_rankings: [
          { model: 'b/beta', average_rank: 1, rankings_count: 1 },
          { model: 'a/alpha', average_rank: 1, rankings_count: 1 },
        ],
      },
    });

    expect(getByText(/How the council decided/)).toHaveTextContent('top-ranked: beta, alpha (tie)');
  });

  it('keeps the stages expanded while there is no final answer', () => {
    const { getByText, queryByText } = renderMessage({ ...answered, stage3: null });

    expect(getByText('Alpha draft')).toBeVisible();
    expect(queryByText(/How the council decided/)).not.toBeVisible();
  });

  it('keeps the stages expanded when the final synthesis failed', () => {
    const { getByText, getByRole } = renderMessage({
      ...answered,
      stage3: { model: 'c/chair', error: true, response: 'Error: Unable to generate final synthesis.' },
    });

    expect(getByRole('alert')).toHaveTextContent('Final synthesis failed');
    expect(getByText('Alpha draft')).toBeVisible();
  });

  it.each(['', null])('keeps the stages expanded when the final answer came back empty (%j)', (response) => {
    const { getByText } = renderMessage({
      ...answered,
      stage3: { model: 'c/chair', response, truncated: true, finish_reason: 'length' },
    });

    expect(getByText('Alpha draft')).toBeVisible();
  });

  it('collapses the stages when the answer arrives and keeps the selected tab', () => {
    const conversation = (message) => ({ id: 'layout', messages: [{ role: 'user', content: 'Q' }, message] });
    const { getByText, getByRole, rerender } = render(
      <ChatInterface conversation={conversation({ ...answered, stage3: null })} />,
    );
    fireEvent.click(getByRole('button', { name: 'beta' }));
    expect(getByText('Beta draft')).toBeVisible();

    rerender(<ChatInterface conversation={conversation(answered)} />);

    expect(getByText('Final verdict')).toBeVisible();
    expect(getByText('Beta draft')).not.toBeVisible();
    fireEvent.click(getByText(/How the council decided/));
    expect(getByText('Beta draft')).toBeVisible();
  });

  it('offers no council block on a continuation that has only a final answer', () => {
    const { getByText, queryByText } = renderMessage({ role: 'assistant', stage3: answered.stage3 });

    expect(getByText('Final verdict')).toBeVisible();
    expect(queryByText(/How the council decided/)).not.toBeVisible();
  });
});

it('blocks Ollama images with an actionable warning before upload', async () => {
  const onUploadFile = vi.fn();
  const addToast = vi.fn();
  const { container } = render(<ChatInterface conversation={{ id: 'ollama', router_type: 'ollama', messages: [] }} onUploadFile={onUploadFile} addToast={addToast} />);
  fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [sizedFile('x.png', 'image/png', 10)] } });
  expect(onUploadFile).not.toHaveBeenCalled();
  expect(addToast).toHaveBeenCalledWith(expect.stringContaining('OpenRouter'), 'warning');
});

it('shows the run usage summary only once the message has stopped streaming', () => {
  const message = {
    role: 'assistant',
    stage1: [{ model: 'a/alpha', response: 'Draft', usage: { prompt_tokens: 20, completion_tokens: 10 } }],
    metadata: {},
    loading: { stage1: false, stage2: false, stage3: false }, // set on messages built from a stream
  };
  const conversation = { id: 'usage', messages: [{ role: 'user', content: 'Q' }, message] };
  const { queryByRole, rerender } = render(<ChatInterface conversation={conversation} isLoading />);
  expect(queryByRole('group', { name: 'Run usage' })).toBeNull();

  rerender(<ChatInterface conversation={conversation} />);
  expect(queryByRole('group', { name: 'Run usage' })).toHaveTextContent('Prompt tokens 20');
});
