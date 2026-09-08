import './TruncationNotice.css';

export default function TruncationNotice({ result, onContinue, busy = false }) {
  if (!result) return null;
  const truncated = result.truncated === true || result.finish_reason === 'length'
    || result.native_finish_reason === 'max_tokens';
  const legacy = result.truncated == null && !result.finish_reason && !result.effective_max_tokens
    && Number(result.usage?.completion_tokens) >= 8192;
  if (!truncated && !legacy) return null;
  return (
    <div className="truncation-notice" role="status">
      <strong>{truncated ? 'Response truncated by token limit' : 'May be truncated (legacy token limit)'}</strong>
      <p>{legacy ? 'This older response has no saved finish reason. Its token usage reached the previous limit.' : 'The model reached its output budget. Reasoning also uses this budget; visible text may be incomplete or empty.'}</p>
      {result.effective_max_tokens && <p>Output limit: {result.effective_max_tokens} tokens.</p>}
      {onContinue && <button type="button" disabled={busy} onClick={() => onContinue(result.model)}>Continue response (additional paid request)</button>}
      <p>Continuation asks only this model and adds a separate answer. Previous rankings and synthesis are not rerun.</p>
    </div>
  );
}
