import { memo } from 'react';
import PropTypes from 'prop-types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { formatDuration, formatTimestamp } from '../utils/timing';
import './Stage3.css';

const Stage3 = memo(function Stage3({ finalResponse, timings }) {
  if (!finalResponse) {
    return null;
  }

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
      <div className="final-response">
        <div className="chairman-label">
          Chairman: {finalResponse.model.split('/')[1] || finalResponse.model}
        </div>
        <div className="final-text markdown-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{finalResponse.response}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
});

Stage3.propTypes = {
  finalResponse: PropTypes.shape({
    model: PropTypes.string.isRequired,
    response: PropTypes.string.isRequired,
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
