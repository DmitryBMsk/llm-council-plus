import { useState, memo } from 'react';
import PropTypes from 'prop-types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { formatDuration, formatTimestamp } from '../utils/timing';
import './Stage1.css';

// Error type to user-friendly message mapping
const ERROR_MESSAGES = {
  rate_limit: 'Rate limited - too many requests',
  not_found: 'Model not available',
  auth: 'Authentication error',
  timeout: 'Request timed out',
  connection: 'Connection error',
  empty: 'Empty response',
  unknown: 'Unknown error',
};

const Stage1 = memo(function Stage1({ responses, timings, isStreaming }) {
  const [activeTab, setActiveTab] = useState(0);

  if (!responses || responses.length === 0) {
    return null;
  }

  const currentResponse = responses[activeTab];
  const hasError = currentResponse?.error;

  return (
    <div className={`stage stage1 ${isStreaming ? 'streaming' : ''}`}>
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
        <h3 className="stage-title">
          Stage 1: Individual Responses
          {isStreaming && <span className="streaming-badge">streaming...</span>}
        </h3>
      </div>

      <div className="tabs">
        {responses.map((resp, index) => (
          <button
            key={resp.model}
            className={`tab ${activeTab === index ? 'active' : ''} ${resp.error ? 'tab-error' : ''} ${index === responses.length - 1 && isStreaming ? 'new-tab' : ''}`}
            onClick={() => setActiveTab(index)}
            title={resp.error ? resp.error_message : undefined}
          >
            {resp.error && <span className="error-icon">!</span>}
            {resp.model.split('/')[1] || resp.model}
          </button>
        ))}
        {isStreaming && (
          <span className="tab tab-loading">
            <span className="spinner-small"></span>
          </span>
        )}
      </div>

      <div className={`tab-content ${hasError ? 'tab-content-error' : ''}`}>
        <div className="model-name">{currentResponse.model}</div>
        {hasError ? (
          <div className="error-content">
            <div className="error-badge">
              {ERROR_MESSAGES[currentResponse.error_type] || 'Error'}
            </div>
            <div className="error-message">
              {currentResponse.error_message}
            </div>
          </div>
        ) : (
          <div className="response-text markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{currentResponse.response}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
});

Stage1.propTypes = {
  responses: PropTypes.arrayOf(
    PropTypes.shape({
      model: PropTypes.string.isRequired,
      response: PropTypes.string,
      error: PropTypes.bool,
      error_type: PropTypes.string,
      error_message: PropTypes.string,
    })
  ),
  timings: PropTypes.shape({
    start: PropTypes.number,
    end: PropTypes.number,
    duration: PropTypes.number,
  }),
  isStreaming: PropTypes.bool,
};

Stage1.defaultProps = {
  responses: [],
  timings: null,
  isStreaming: false,
};

export default Stage1;
