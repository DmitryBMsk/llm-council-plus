import { useState } from 'react';
import { GENERATION_STAGES, REASONING_EFFORTS, validateGenerationSettings } from '../utils/generationSettings';
export default function GenerationSettings({ draft, onChange, disabled, onValidityChange }) {
  const [overrides, setOverrides] = useState(() => JSON.stringify(draft.model_generation_limits || {}, null, 2));
  const [error, setError] = useState('');
  function update(stage, field, value) {
    onChange({ ...draft, generation_limits: { ...draft.generation_limits, [stage]: { max_tokens: 8192, ...draft.generation_limits?.[stage], [field]: value } } });
  }
  return <div className="settings-section">
    <p className="settings-hint">Output includes reasoning tokens. Larger limits can reserve more OpenRouter credits, even when the final answer is short. Changes apply to future requests, including explicit continuations. Limits are never increased automatically.</p>
    {GENERATION_STAGES.map(stage => <fieldset key={stage} disabled={disabled} className="settings-field">
      <legend>{stage === 'title' ? 'Conversation title' : stage === 'continuation' ? 'Continuation' : `Stage ${stage.slice(-1)}`}</legend>
      <label>Output limit<input aria-label={`${stage} output limit`} type="number" min="128" max="65536" step="1" value={draft.generation_limits?.[stage]?.max_tokens ?? 8192} onChange={e => update(stage, 'max_tokens', Number(e.target.value))} /></label>
      <label>Reasoning tokens (optional)<input aria-label={`${stage} reasoning tokens`} type="number" min="1024" max="65535" step="1" value={draft.generation_limits?.[stage]?.reasoning_max_tokens ?? ''} onChange={e => update(stage, 'reasoning_max_tokens', e.target.value === '' ? null : Number(e.target.value))} /></label>
      <label>Reasoning effort<select aria-label={`${stage} reasoning effort`} value={draft.generation_limits?.[stage]?.reasoning_effort ?? ''} onChange={e => update(stage, 'reasoning_effort', e.target.value || null)}><option value="">Provider default</option>{REASONING_EFFORTS.map(effort => <option key={effort}>{effort}</option>)}</select></label>
    </fieldset>)}
    <p className="settings-hint">Choose reasoning tokens or effort, not both. Provider support varies; explicit reasoning controls are not supported by Ollama.</p>
    <label className="settings-field">Model overrides (JSON, exact model IDs)
      <textarea aria-label="Model generation overrides" disabled={disabled} rows={8} value={overrides} onChange={e => {
        setOverrides(e.target.value);
        try {
          const models = JSON.parse(e.target.value);
          validateGenerationSettings({}, models);
          setError(''); onValidityChange(true); onChange({ ...draft, model_generation_limits: models });
        } catch (err) { setError(err.message); onValidityChange(false); }
      }} />
    </label>
    <p className="settings-hint">Example: {JSON.stringify({ 'anthropic/claude-fable-5.1': { stage1: { max_tokens: 16384, reasoning_max_tokens: 2048 } } })}. Each model stage replaces the entire global stage budget; missing stages inherit globals. Use {'{}'} to clear overrides.</p>
    {error && <p role="alert" className="settings-error">{error}</p>}
  </div>;
}
