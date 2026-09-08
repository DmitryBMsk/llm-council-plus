import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import GenerationSettings from './GenerationSettings';
describe('generation settings form', () => {
  it('honors readonly settings and explains credit reservation', () => {
    render(<GenerationSettings draft={{}} disabled onChange={() => {}} onValidityChange={() => {}} />);
    expect(screen.getByLabelText('stage1 output limit')).toBeDisabled();
    expect(screen.getByLabelText('Model generation overrides')).toBeDisabled();
    expect(screen.getByText(/reserve more OpenRouter credits/)).toBeVisible();
  });
  it('blocks invalid JSON without replacing valid saved override draft', () => {
    const onChange = vi.fn(); const onValidityChange = vi.fn();
    render(<GenerationSettings draft={{}} onChange={onChange} onValidityChange={onValidityChange} />);
    fireEvent.change(screen.getByLabelText('Model generation overrides'), { target: { value: '{ broken' } });
    expect(screen.getByRole('alert')).toBeVisible();
    expect(onChange).not.toHaveBeenCalled();
    expect(onValidityChange).toHaveBeenLastCalledWith(false);
    fireEvent.change(screen.getByLabelText('Model generation overrides'), { target: { value: '{}' } });
    expect(onValidityChange).toHaveBeenLastCalledWith(true);
    expect(onChange).toHaveBeenCalledWith({ model_generation_limits: {} });
  });
});
