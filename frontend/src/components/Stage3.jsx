import TruncationNotice from './TruncationNotice';
import { RowUsage } from './RunUsage';
import { memo, useState } from 'react';
import PropTypes from 'prop-types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { formatDuration, formatTimestamp } from '../utils/timing';
import './Stage3.css';

const shortName = (model) => model.split('/')[1] || model;

async function copyText(text) {
  if (navigator.clipboard) {
    return navigator.clipboard.writeText(text);
  }
  // Plain-HTTP origins other than localhost have no Clipboard API (e.g. the app opened
  // from another machine on the LAN); the deprecated copy command still works there
  const focused = document.activeElement;
  const area = document.createElement('textarea');
  area.value = text;
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  try {
    if (!document.execCommand('copy')) {
      throw new Error('copy command rejected');
    }
  } finally {
    area.remove();
    focused?.focus();
  }
}

const Stage3 = memo(function Stage3({ finalResponse, timings, onContinue, busy }) {
  const [copyState, setCopyState] = useState(null);

  if (!finalResponse) {
    return null;
  }

  const copy = async () => {
    try {
      await copyText(finalResponse.response);
      setCopyState('Copied');
    } catch {
      setCopyState('Copy failed');
    }
    setTimeout(() => setCopyState(null), 2000);
  };

  return (
    <div className="stage stage3">
      {timings && (timings.start || timings.end) && (
        <div className="stage-timing-top-right">
          {timings.start && (
            <span className="timing-start">Started: {formatTimestamp(timings.start)}</span>
          )}
          {timings.end && (
            <span className="timing-end">Ended: {formatTimestamp(timings.end)}</span>
          )}
          {timings.duration !== null && timings.duration !== undefined && (
            <span className="timing-duration">Elapsed: {formatDuration(timings.duration)}</span>
          )}
        </div>
      )}
      <div className="stage-header">
        <h3 className="stage-title">Stage 3: Final Council Answer</h3>
      </div>
      {finalResponse.error ? (
        // The backend stores a failed synthesis as a stage3 object with error: true
        <div className="final-response final-error" role="alert">
          <strong>Final synthesis failed</strong>
          <p>{finalResponse.response?.replace(/^Error:\s*/, '')}</p>
          {finalResponse.tried_fallbacks?.length > 0 && (
            <p>Fallbacks tried: {finalResponse.tried_fallbacks.map(shortName).join(', ')}</p>
          )}
          <p>Individual responses, where available, are shown below.</p>
        </div>
      ) : (
        <div className="final-response">
          <div className="final-response-bar">
            <div className="chairman-label">
              Chairman: {shortName(finalResponse.model)}<RowUsage usage={finalResponse.usage} />
            </div>
            {/* response is '' or null when the token budget went to reasoning */}
            {finalResponse.response?.trim() && (
              <button type="button" className="export-button copy-answer" onClick={copy}>
                <span aria-live="polite">{copyState || 'Copy answer'}</span>
              </button>
            )}
          </div>
          <TruncationNotice result={finalResponse} onContinue={onContinue} busy={busy} />
          <div className="final-text markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>{finalResponse.response}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
});

Stage3.propTypes = {
  onContinue: PropTypes.func,
  busy: PropTypes.bool,
  finalResponse: PropTypes.shape({
    model: PropTypes.string.isRequired,
    response: PropTypes.string,
    error: PropTypes.bool,
    tried_fallbacks: PropTypes.arrayOf(PropTypes.string),
  }),
  timings: PropTypes.shape({
    start: PropTypes.number,
    end: PropTypes.number,
    duration: PropTypes.number,
  }),
};

Stage3.defaultProps = {
  finalResponse: null,
  timings: null,
};

export default Stage3;
