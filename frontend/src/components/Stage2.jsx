import { useState, memo } from 'react';
import PropTypes from 'prop-types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { formatDuration, formatTimestamp } from '../utils/timing';
import './Stage2.css';

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

function deAnonymizeText(text, labelToModel) {
  if (!labelToModel) return text;

  let result = text;
  // Replace each "Response X" with the actual model name
  // Using split/join instead of RegExp to prevent ReDoS attacks
  Object.entries(labelToModel).forEach(([label, model]) => {
    const modelShortName = model.split('/')[1] || model;
    // Safe string replacement without RegExp (prevents ReDoS)
    result = result.split(label).join(`**${modelShortName}**`);
  });
  return result;
}

const Stage2 = memo(function Stage2({ rankings, labelToModel, aggregateRankings, timings }) {
  const [activeTab, setActiveTab] = useState(0);

  if (!rankings || rankings.length === 0) {
    return null;
  }

  const currentRanking = rankings[activeTab];
  const hasError = currentRanking?.error;

  return (
    <div className="stage stage2">
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
        <h3 className="stage-title">Stage 2: Peer Rankings</h3>
      </div>

      <h4>Raw Evaluations</h4>
      <p className="stage-description">
        Each model evaluated all responses (anonymized as Response A, B, C, etc.) and provided rankings.
        Below, model names are shown in <strong>bold</strong> for readability, but the original evaluation used anonymous labels.
      </p>

      <div className="tabs">
        {rankings.map((rank, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''} ${rank.error ? 'tab-error' : ''}`}
            onClick={() => setActiveTab(index)}
            title={rank.error ? rank.error_message : undefined}
          >
            {rank.error && <span className="error-icon">!</span>}
            {rank.model.split('/')[1] || rank.model}
          </button>
        ))}
      </div>

      <div className={`tab-content ${hasError ? 'tab-content-error' : ''}`}>
        <div className="ranking-model">
          {currentRanking.model}
        </div>
        {hasError ? (
          <div className="error-content">
            <div className="error-badge">
              {ERROR_MESSAGES[currentRanking.error_type] || 'Error'}
            </div>
            <div className="error-message">
              {currentRanking.error_message}
            </div>
          </div>
        ) : (
          <>
            <div className="ranking-content markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml={true}>
                {deAnonymizeText(currentRanking.ranking, labelToModel)}
              </ReactMarkdown>
            </div>

            {currentRanking.parsed_ranking &&
             currentRanking.parsed_ranking.length > 0 && (
              <div className="parsed-ranking">
                <strong>Extracted Ranking:</strong>
                <ol>
                  {currentRanking.parsed_ranking.map((label, i) => (
                    <li key={i}>
                      {labelToModel && labelToModel[label]
                        ? labelToModel[label].split('/')[1] || labelToModel[label]
                        : label}
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </>
        )}
      </div>

      {aggregateRankings && aggregateRankings.length > 0 && (
        <div className="aggregate-rankings">
          <h4>Aggregate Rankings (Street Cred)</h4>
          <p className="stage-description">
            Combined results across all peer evaluations (lower score is better):
          </p>
          <div className="aggregate-list">
            {aggregateRankings.map((agg, index) => (
              <div key={index} className="aggregate-item">
                <span className="rank-position">#{index + 1}</span>
                <span className="rank-model">
                  {agg.model.split('/')[1] || agg.model}
                </span>
                <span className="rank-score">
                  Avg: {agg.average_rank.toFixed(2)}
                </span>
                <span className="rank-count">
                  ({agg.rankings_count} votes)
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
});

Stage2.propTypes = {
  rankings: PropTypes.arrayOf(
    PropTypes.shape({
      model: PropTypes.string.isRequired,
      ranking: PropTypes.string,
      parsed_ranking: PropTypes.arrayOf(PropTypes.string),
      error: PropTypes.bool,
      error_type: PropTypes.string,
      error_message: PropTypes.string,
    })
  ),
  labelToModel: PropTypes.objectOf(PropTypes.string),
  aggregateRankings: PropTypes.arrayOf(
    PropTypes.shape({
      model: PropTypes.string.isRequired,
      average_rank: PropTypes.number.isRequired,
      rankings_count: PropTypes.number.isRequired,
    })
  ),
  timings: PropTypes.shape({
    start: PropTypes.number,
    end: PropTypes.number,
    duration: PropTypes.number,
  }),
};

Stage2.defaultProps = {
  rankings: [],
  labelToModel: null,
  aggregateRankings: [],
  timings: null,
};

export default Stage2;
