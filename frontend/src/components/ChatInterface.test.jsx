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

it('blocks Ollama images with an actionable warning before upload', async () => {
  const onUploadFile = vi.fn();
  const addToast = vi.fn();
  const { container } = render(<ChatInterface conversation={{ id: 'ollama', router_type: 'ollama', messages: [] }} onUploadFile={onUploadFile} addToast={addToast} />);
  fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [sizedFile('x.png', 'image/png', 10)] } });
  expect(onUploadFile).not.toHaveBeenCalled();
  expect(addToast).toHaveBeenCalledWith(expect.stringContaining('OpenRouter'), 'warning');
});
