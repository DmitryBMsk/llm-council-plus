export const GENERATION_STAGES = ['stage1', 'stage2', 'stage3', 'title', 'continuation'];
export const REASONING_EFFORTS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
export function validateGenerationSettings(stages = {}, models = {}) {
  const object = value => value && typeof value === 'object' && !Array.isArray(value);
  function validate(stageMap) {
    if (!object(stageMap)) throw new Error('Generation limits must be JSON objects');
    for (const [stage, budget] of Object.entries(stageMap)) {
      if (!GENERATION_STAGES.includes(stage) || !object(budget)) throw new Error(`Invalid generation stage: ${stage}`);
      if (Object.keys(budget).some(key => !['max_tokens', 'reasoning_max_tokens', 'reasoning_effort'].includes(key))) throw new Error('Unknown generation limit field');
      const max = budget.max_tokens ?? 8192;
      if (!Number.isInteger(max) || max < 128 || max > 65536) throw new Error('Output limit must be an integer from 128 to 65536');
      const reasoning = budget.reasoning_max_tokens;
      if (reasoning != null && (!Number.isInteger(reasoning) || reasoning < 1024 || reasoning >= max)) throw new Error('Reasoning tokens must be at least 1024 and below output limit');
      if (budget.reasoning_effort != null && !REASONING_EFFORTS.includes(budget.reasoning_effort)) throw new Error('Invalid reasoning effort');
      if (reasoning != null && budget.reasoning_effort != null) throw new Error('Choose reasoning tokens or effort, not both');
    }
  }
  validate(stages);
  if (!object(models)) throw new Error('Model overrides must be a JSON object');
  for (const [model, stageMap] of Object.entries(models)) {
    if (!model.trim()) throw new Error('Model ID cannot be empty');
    validate(stageMap);
  }
}
