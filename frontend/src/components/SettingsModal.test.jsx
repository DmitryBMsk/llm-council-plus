import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SettingsModal from './SettingsModal';
import { api } from '../api';

vi.mock('../api', () => ({ api: { getRuntimeSettings: vi.fn() } }));
afterEach(cleanup);

it('shows global settings read-only and disables every mutation for ordinary users', async () => {
  api.getRuntimeSettings.mockResolvedValue({ can_edit: false, stage1_prompt_template: 'prompt' });
  const { container } = render(<SettingsModal isOpen onClose={() => {}} />);
  await screen.findByDisplayValue('prompt');
  expect(screen.getByText(/Only administrators can change global settings/)).toBeTruthy();
  expect(container.querySelector('textarea').disabled).toBe(true);
  fireEvent.click(screen.getByText('Backup'));
  expect(screen.getByText('Import JSON').disabled).toBe(true);
  expect(screen.getByText('Reset to Defaults').disabled).toBe(true);
  expect(screen.getByText('Export JSON').disabled).toBe(false);
});

it('allows administrators to edit settings after loading', async () => {
  api.getRuntimeSettings.mockResolvedValue({ can_edit: true, stage1_prompt_template: 'prompt' });
  const { container } = render(<SettingsModal isOpen onClose={() => {}} />);
  await waitFor(() => expect(container.querySelector('textarea')).toBeTruthy());
  expect(container.querySelector('textarea').disabled).toBe(false);
});
