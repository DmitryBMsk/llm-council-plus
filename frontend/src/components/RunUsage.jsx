import PropTypes from 'prop-types';
import './RunUsage.css';

// Only what the provider reported counts: 0 is a real figure, a missing one is not
const known = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const tokens = (value) => value.toLocaleString('en-US');
// More digits below $1 and below a hundredth of a cent, so a small real cost never reads as zero
const money = (value) => {
  if (value === 0 || value >= 1) return `$${value.toFixed(2)}`;
  return `$${value >= 0.0001 ? value.toFixed(4) : value.toLocaleString('en-US', { maximumSignificantDigits: 2 })}`;
};

// [key in the summary, key in a stage row's usage, label, formatter]
const FIGURES = [
  ['prompt_tokens', 'prompt_tokens', 'Prompt tokens', tokens],
  ['completion_tokens', 'completion_tokens', 'Completion tokens', tokens],
  ['total_tokens', 'total_tokens', 'Total tokens', tokens],
  ['provider_cost', 'cost', 'Cost', money],
];

// Messages saved before #56 have no provider_usage: sum what their stage rows kept.
// This misses the title call and retried attempts, hence the label in the summary.
function fromStageRows(message) {
  const rows = [...(message.stage1 || []), ...(message.stage2 || []), ...(message.stage3 ? [message.stage3] : [])];
  const totals = {};
  const coverage = {};
  for (const [key, rowKey] of FIGURES) {
    const values = rows.map((row) => row.usage?.[rowKey]).filter(known);
    coverage[key] = values.length;
    totals[key] = values.reduce((sum, value) => sum + value, 0);
  }
  return { totals, coverage, attempts: rows.length, scope: 'stage_results_only' };
}

export function RowUsage({ usage }) {
  const parts = [
    known(usage?.prompt_tokens) && `${tokens(usage.prompt_tokens)} prompt tokens`,
    known(usage?.completion_tokens) && `${tokens(usage.completion_tokens)} completion tokens`,
    // Some providers report a total without the split
    !known(usage?.prompt_tokens) && !known(usage?.completion_tokens) && known(usage?.total_tokens) && `${tokens(usage.total_tokens)} tokens`,
    known(usage?.cost) && money(usage.cost),
  ].filter(Boolean);
  return parts.length ? <span className="row-usage">{parts.join(' · ')}</span> : null;
}

RowUsage.propTypes = { usage: PropTypes.object };

export default function RunUsage({ message }) {
  const stored = message.metadata?.provider_usage;
  const { totals, coverage, attempts, scope, complete } = stored?.attempts ? stored : fromStageRows(message);
  const count = (key) => coverage?.[key] || 0;
  const reported = (key) => count(key) > 0 && known(totals?.[key]);
  if (!FIGURES.some(([key]) => reported(key))) return null;

  // The total adds nothing to the split, unless more calls reported it than reported the split
  const shown = FIGURES.filter(
    ([key]) => key !== 'total_tokens' || count(key) > Math.min(count('prompt_tokens'), count('completion_tokens'))
  );
  const toon = message.metadata?.token_stats?.total;
  return (
    <div className="run-usage" role="group" aria-label="Run usage">
      <div className="run-usage-figures">
        {shown.map(([key, , label, format]) => (
          <span key={key}>
            {label} {reported(key) ? format(totals[key]) : 'not reported'}
            {/* An incomplete summary (#56) gives the count for every figure, not only a partly reported one */}
            {reported(key) && (complete === false || count(key) < attempts) && ` (reported by ${count(key)} of ${attempts} calls)`}
          </span>
        ))}
      </div>
      {scope === 'stage_results_only' && (
        <div className="run-usage-note">Stage responses only: title and retried calls are not included.</div>
      )}
      {toon && Math.round(toon.saved_percent) >= 1 && (
        <div className="run-usage-note">
          TOON encoding saved about {Math.round(toon.saved_percent)}% ({tokens(toon.json_tokens)} → {tokens(toon.toon_tokens)} tokens, an estimate, not billing)
        </div>
      )}
    </div>
  );
}

RunUsage.propTypes = {
  message: PropTypes.shape({
    stage1: PropTypes.array,
    stage2: PropTypes.array,
    stage3: PropTypes.object,
    metadata: PropTypes.object,
  }).isRequired,
};
