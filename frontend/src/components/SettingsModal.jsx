import { useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { api } from '../api';
import './SettingsModal.css';

function clampNumber(value, min, max) {
  const num = Number(value);
  if (Number.isNaN(num)) return min;
  return Math.min(max, Math.max(min, num));
}

function downloadJson(filename, obj) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const RUNTIME_SETTINGS_KEYS = [
  'stage1_prompt_template',
  'stage2_prompt_template',
  'stage3_prompt_template',
  'council_temperature',
  'stage2_temperature',
  'chairman_temperature',
  'web_search_provider',
  'web_max_results',
  'web_full_content_results',
];

function sanitizeRuntimeSettingsJson(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid settings file: expected a JSON object');
  }

  const droppedKeys = [];
  const sanitized = {};
  for (const [k, v] of Object.entries(value)) {
    if (!RUNTIME_SETTINGS_KEYS.includes(k)) {
      droppedKeys.push(k);
      continue;
    }
    sanitized[k] = v;
  }

  return { sanitized, droppedKeys };
}

export default function SettingsModal({ isOpen, onClose }) {
  const [activeTab, setActiveTab] = useState('prompts'); // prompts | temps | search | backup
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [original, setOriginal] = useState(null);
  const [draft, setDraft] = useState(null);
  const fileInputRef = useRef(null);

  const hasChanges = useMemo(() => {
    if (!original || !draft) return false;
    return JSON.stringify(original) !== JSON.stringify(draft);
  }, [original, draft]);

  const load = async () => {
    setIsLoading(true);
    setError('');
    setSuccess('');
    try {
      const settings = await api.getRuntimeSettings();
      setOriginal(settings);
      setDraft(settings);
    } catch (e) {
      setError(e.message || 'Failed to load settings');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      load();
    } else {
      setError('');
      setSuccess('');
    }
  }, [isOpen]);

  const handleSave = async () => {
    if (!draft || !hasChanges) return;
    setIsSaving(true);
    setError('');
    setSuccess('');
    try {
      const patch = {};
      for (const [k, v] of Object.entries(draft)) {
        if (!original || original[k] !== v) {
          patch[k] = v;
        }
      }
      const updated = await api.updateRuntimeSettings(patch);
      setOriginal(updated);
      setDraft(updated);
      setSuccess('Saved!');
      setTimeout(() => setSuccess(''), 1500);
    } catch (e) {
      setError(e.message || 'Failed to save settings');
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = async () => {
    if (!window.confirm('Reset runtime settings to defaults?')) return;
    setIsSaving(true);
    setError('');
    setSuccess('');
    try {
      const updated = await api.resetRuntimeSettings();
      setOriginal(updated);
      setDraft(updated);
      setSuccess('Reset to defaults');
      setTimeout(() => setSuccess(''), 1500);
    } catch (e) {
      setError(e.message || 'Failed to reset settings');
    } finally {
      setIsSaving(false);
    }
  };

  const handleExport = async () => {
    setError('');
    try {
      const config = await api.exportRuntimeSettings();
      const { sanitized } = sanitizeRuntimeSettingsJson(config);
      downloadJson(`llm-ttcc-team-pro-settings-${new Date().toISOString().slice(0, 10)}.json`, sanitized);
    } catch (e) {
      setError(e.message || 'Failed to export settings');
    }
  };

  const handleImportClick = () => {
    fileInputRef.current?.click();
  };

  const handleImportFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError('');
    setSuccess('');
    try {
      const text = await file.text();
      const json = JSON.parse(text);
      const { sanitized, droppedKeys } = sanitizeRuntimeSettingsJson(json);
      if (droppedKeys.length) {
        setSuccess(`Imported (ignored ${droppedKeys.length} unsupported keys)`);
      }
      const updated = await api.importRuntimeSettings(sanitized);
      setOriginal(updated);
      setDraft(updated);
      if (!droppedKeys.length) setSuccess('Imported');
      setTimeout(() => setSuccess(''), 1500);
    } catch (err) {
      setError(err.message || 'Import failed');
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  if (!isOpen) return null;

  return (
    <div className="settings-modal-overlay" onClick={onClose}>
      <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-modal-header">
          <h2>Settings</h2>
          <button className="settings-close" onClick={onClose} aria-label="Close settings">
            ×
          </button>
        </div>

        <div className="settings-tabs">
          <button
            className={`settings-tab ${activeTab === 'prompts' ? 'active' : ''}`}
            onClick={() => setActiveTab('prompts')}
          >
            Prompts
          </button>
          <button
            className={`settings-tab ${activeTab === 'temps' ? 'active' : ''}`}
            onClick={() => setActiveTab('temps')}
          >
            Temperatures
          </button>
          <button
            className={`settings-tab ${activeTab === 'search' ? 'active' : ''}`}
            onClick={() => setActiveTab('search')}
          >
            Web Search
          </button>
          <button
            className={`settings-tab ${activeTab === 'backup' ? 'active' : ''}`}
            onClick={() => setActiveTab('backup')}
          >
            Backup
          </button>
        </div>

        <div className="settings-modal-body">
          {isLoading && <div className="settings-loading">Loading…</div>}
          {!isLoading && !draft && <div className="settings-loading">No settings loaded</div>}

          {!isLoading && draft && activeTab === 'prompts' && (
            <div className="settings-section">
              <div className="settings-field">
                <label>Stage 1 Prompt Template</label>
                <div className="settings-hint">Available placeholders: {'{user_query}'}, {'{full_query}'}</div>
                <textarea
                  value={draft.stage1_prompt_template || ''}
                  onChange={(e) => setDraft((p) => ({ ...p, stage1_prompt_template: e.target.value }))}
                  rows={6}
                />
              </div>
              <div className="settings-field">
                <label>Stage 2 Prompt Template</label>
                <div className="settings-hint">Available placeholders: {'{user_query}'}, {'{responses_text}'}</div>
                <textarea
                  value={draft.stage2_prompt_template || ''}
                  onChange={(e) => setDraft((p) => ({ ...p, stage2_prompt_template: e.target.value }))}
                  rows={10}
                />
              </div>
              <div className="settings-field">
                <label>Stage 3 Prompt Template</label>
                <div className="settings-hint">
                  Available placeholders: {'{user_query}'}, {'{stage1_text}'}, {'{stage2_text}'}, {'{rankings_block}'}, {'{tools_text}'}
                </div>
                <textarea
                  value={draft.stage3_prompt_template || ''}
                  onChange={(e) => setDraft((p) => ({ ...p, stage3_prompt_template: e.target.value }))}
                  rows={10}
                />
              </div>
            </div>
          )}

          {!isLoading && draft && activeTab === 'temps' && (
            <div className="settings-section">
              <div className="settings-field">
                <label>Council Temperature: <span className="settings-value">{Number(draft.council_temperature).toFixed(2)}</span></label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.05"
                  value={clampNumber(draft.council_temperature, 0, 2)}
                  onChange={(e) => setDraft((p) => ({ ...p, council_temperature: Number(e.target.value) }))}
                />
              </div>
              <div className="settings-field">
                <label>Stage 2 Temperature: <span className="settings-value">{Number(draft.stage2_temperature).toFixed(2)}</span></label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.05"
                  value={clampNumber(draft.stage2_temperature, 0, 2)}
                  onChange={(e) => setDraft((p) => ({ ...p, stage2_temperature: Number(e.target.value) }))}
                />
              </div>
              <div className="settings-field">
                <label>Chairman Temperature: <span className="settings-value">{Number(draft.chairman_temperature).toFixed(2)}</span></label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.05"
                  value={clampNumber(draft.chairman_temperature, 0, 2)}
                  onChange={(e) => setDraft((p) => ({ ...p, chairman_temperature: Number(e.target.value) }))}
                />
              </div>
            </div>
          )}

          {!isLoading && draft && activeTab === 'search' && (
            <div className="settings-section">
              <div className="settings-field">
                <label>Default Provider</label>
                <div className="settings-hint">
                  Provider selection and fetch limits are stored here. API keys are not stored or exported.
                </div>
                <select
                  value={draft.web_search_provider || 'duckduckgo'}
                  onChange={(e) => setDraft((p) => ({ ...p, web_search_provider: e.target.value }))}
                  className="settings-select"
                >
                  <option value="off">Off</option>
                  <option value="duckduckgo">DuckDuckGo (free)</option>
                  <option value="tavily">Tavily</option>
                  <option value="exa">Exa</option>
                  <option value="brave">Brave</option>
                </select>
              </div>

              <div className="settings-field">
                <label>Max Results: <span className="settings-value">{Number(draft.web_max_results ?? 5)}</span></label>
                <input
                  type="range"
                  min="1"
                  max="10"
                  step="1"
                  value={clampNumber(draft.web_max_results ?? 5, 1, 10)}
                  onChange={(e) => setDraft((p) => ({ ...p, web_max_results: Number(e.target.value) }))}
                />
              </div>

              <div className="settings-field">
                <label>
                  Full Article Fetch (Jina Reader): <span className="settings-value">{Number(draft.web_full_content_results ?? 0)}</span>
                </label>
                <div className="settings-hint">
                  Fetch full content for top N results when using DuckDuckGo/Brave. Set 0 to disable.
                </div>
                <input
                  type="range"
                  min="0"
                  max="10"
                  step="1"
                  value={clampNumber(draft.web_full_content_results ?? 0, 0, 10)}
                  onChange={(e) => setDraft((p) => ({ ...p, web_full_content_results: Number(e.target.value) }))}
                />
              </div>
            </div>
          )}

          {!isLoading && draft && activeTab === 'backup' && (
            <div className="settings-section">
              <p className="settings-hint">
                Export/import contains non-secret runtime settings only. API keys and other secrets are not included.
              </p>
              <div className="settings-actions-row">
                <button className="settings-btn" onClick={handleExport}>Export JSON</button>
                <button className="settings-btn" onClick={handleImportClick}>Import JSON</button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="application/json"
                  onChange={handleImportFile}
                  style={{ display: 'none' }}
                />
              </div>
              <div className="settings-divider" />
              <button className="settings-btn danger" onClick={handleReset}>
                Reset to Defaults
              </button>
            </div>
          )}
        </div>

        <div className="settings-modal-footer">
          <div className="settings-status">
            {error && <span className="settings-error">{error}</span>}
            {!error && success && <span className="settings-success">{success}</span>}
          </div>
          <div className="settings-footer-actions">
            <button className="settings-btn secondary" onClick={load} disabled={isLoading || isSaving}>
              Reload
            </button>
            <button className="settings-btn primary" onClick={handleSave} disabled={!hasChanges || isSaving || isLoading}>
              {isSaving ? 'Saving…' : (hasChanges ? 'Save' : 'Saved')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

SettingsModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
};
