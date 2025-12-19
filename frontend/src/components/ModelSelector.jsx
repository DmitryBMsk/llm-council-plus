import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { api } from '../api';
import './ModelSelector.css';

// LocalStorage keys
const LAST_USED_KEY = 'llm-council-last-selection';
const LAST_CHAIRMAN_KEY = 'llm-council-last-chairman';

// Default max models (can be overridden by backend config)
const DEFAULT_MAX_MODELS = 10;

// Built-in presets (will be merged with dynamic "Last Used")
const BUILT_IN_PRESETS = {
  ultra: {
    name: 'Ultra',
    description: 'Top-tier models for best quality',
    modelPatterns: ['claude-opus', 'gpt-5.1', 'gemini-3-pro', 'gpt-4o'],
    chairmanPattern: 'gemini-3-pro',
  },
  budget: {
    name: 'Budget',
    description: 'Cost-effective models',
    modelPatterns: ['grok-4', 'gpt-5-mini', 'gemini-2.5-flash', 'deepseek'],
    chairmanPattern: 'gemini-2.5-flash',
  },
  free: {
    name: 'Free',
    description: 'No cost - completely free models',
    tierFilter: 'free',
    maxModels: 7,
  },
};

const MIN_MODELS = 3;

// Sort options
const SORT_OPTIONS = [
  { value: 'price-asc', label: 'Price: Low to High' },
  { value: 'price-desc', label: 'Price: High to Low' },
  { value: 'name-asc', label: 'Name: A to Z' },
  { value: 'name-desc', label: 'Name: Z to A' },
  { value: 'context-desc', label: 'Context: Largest First' },
  { value: 'context-asc', label: 'Context: Smallest First' },
];

export default function ModelSelector({ isOpen, onClose, onConfirm }) {
  // State
  const [allModels, setAllModels] = useState([]);
  const [isLoadingModels, setIsLoadingModels] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [selectedModels, setSelectedModels] = useState([]);
  const [chairmanModel, setChairmanModel] = useState('');
  const [activePreset, setActivePreset] = useState(null);
  const [maxModels, setMaxModels] = useState(DEFAULT_MAX_MODELS);

  // Filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [providerFilter, setProviderFilter] = useState('');
  const [tierFilter, setTierFilter] = useState('');
  const [freeOnlyFilter, setFreeOnlyFilter] = useState(false);
  const [sortBy, setSortBy] = useState('price-asc');

  // Refs for auto-scroll
  const modelsGridRef = useRef(null);
  const modelCardRefs = useRef({});

  // Load models when modal opens
  useEffect(() => {
    if (isOpen) {
      loadModels();
    }
  }, [isOpen]);

  // Load last used selection when models are loaded
  useEffect(() => {
    if (allModels.length > 0 && isOpen) {
      loadLastUsedSelection();
    }
  }, [allModels, isOpen]);

  const loadModels = async () => {
    setIsLoadingModels(true);
    setLoadError(null);
    try {
      const data = await api.getModels();
      setAllModels(data.models || []);
      // Get max_models from backend config if provided
      if (data.max_models) {
        setMaxModels(data.max_models);
      }
    } catch (error) {
      console.error('Failed to load models:', error);
      setLoadError(error.message);
    } finally {
      setIsLoadingModels(false);
    }
  };

  const loadLastUsedSelection = () => {
    try {
      const saved = localStorage.getItem(LAST_USED_KEY);
      if (saved) {
        const { models, chairman } = JSON.parse(saved);
        // Verify models still exist
        const validModels = models.filter((m) => allModels.some((am) => am.id === m));
        const validChairman = allModels.some((am) => am.id === chairman) ? chairman : '';

        if (validModels.length >= MIN_MODELS && validChairman) {
          setSelectedModels(validModels);
          setChairmanModel(validChairman);
          setActivePreset('last');
          // Auto-scroll to first selected model
          setTimeout(() => scrollToModel(validModels[0]), 100);
          return;
        }
      }
    } catch (e) {
      console.error('Failed to load last selection:', e);
    }
    // Default to free preset if no valid last selection
    applyPreset('free');
  };

  const saveLastUsedSelection = (models, chairman) => {
    try {
      localStorage.setItem(
        LAST_USED_KEY,
        JSON.stringify({ models, chairman, timestamp: Date.now() })
      );
      // Also save chairman separately for quick access
      if (chairman) {
        localStorage.setItem(LAST_CHAIRMAN_KEY, chairman);
      }
    } catch (e) {
      console.error('Failed to save last selection:', e);
    }
  };

  // Load just the last chairman (for initial default)
  const getLastChairman = useCallback(() => {
    try {
      return localStorage.getItem(LAST_CHAIRMAN_KEY) || '';
    } catch {
      return '';
    }
  }, []);

  // Scroll to a specific model card
  const scrollToModel = useCallback((modelId) => {
    const cardElement = modelCardRefs.current[modelId];
    if (cardElement && modelsGridRef.current) {
      cardElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, []);

  // Extract unique providers from models
  const providers = useMemo(() => {
    const providerSet = new Set(allModels.map((m) => m.provider));
    return Array.from(providerSet).sort();
  }, [allModels]);

  // Filter and sort models
  const filteredModels = useMemo(() => {
    let result = [...allModels];

    // Search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (m) =>
          m.name.toLowerCase().includes(query) ||
          m.id.toLowerCase().includes(query) ||
          m.provider.toLowerCase().includes(query)
      );
    }

    // Provider filter
    if (providerFilter) {
      result = result.filter((m) => m.provider === providerFilter);
    }

    // Tier filter
    if (tierFilter) {
      result = result.filter((m) => m.tier === tierFilter);
    }

    // Free only filter
    if (freeOnlyFilter) {
      result = result.filter((m) => m.isFree);
    }

    // Sort
    const [sortField, sortDir] = sortBy.split('-');
    result.sort((a, b) => {
      let comparison = 0;
      switch (sortField) {
        case 'price':
          comparison = (a.outputPriceRaw || 0) - (b.outputPriceRaw || 0);
          break;
        case 'name':
          comparison = a.name.localeCompare(b.name);
          break;
        case 'context':
          comparison = (a.contextLength || 0) - (b.contextLength || 0);
          break;
        default:
          comparison = 0;
      }
      return sortDir === 'desc' ? -comparison : comparison;
    });

    return result;
  }, [allModels, searchQuery, providerFilter, tierFilter, freeOnlyFilter, sortBy]);

  // Get selected model objects for display
  const selectedModelObjects = useMemo(() => {
    return selectedModels
      .map((id) => allModels.find((m) => m.id === id))
      .filter(Boolean);
  }, [selectedModels, allModels]);

  const applyPreset = (presetKey) => {
    if (presetKey === 'last') {
      // Already handled in loadLastUsedSelection
      return;
    }

    const preset = BUILT_IN_PRESETS[presetKey];
    if (!preset) return;

    let selectedIds = [];
    let chairmanId = '';

    if (preset.tierFilter) {
      // Select by tier (e.g., free models)
      const tierModels = allModels.filter((m) => m.tier === preset.tierFilter);
      const presetMax = Math.min(preset.maxModels || 7, maxModels);
      selectedIds = tierModels.slice(0, presetMax).map((m) => m.id);
      chairmanId = selectedIds[0] || '';
    } else if (preset.modelPatterns) {
      // Select by pattern matching
      for (const pattern of preset.modelPatterns) {
        if (selectedIds.length >= maxModels) break;
        const match = allModels.find(
          (m) => m.id.toLowerCase().includes(pattern.toLowerCase()) && !selectedIds.includes(m.id)
        );
        if (match) {
          selectedIds.push(match.id);
        }
      }
      // Find chairman
      if (preset.chairmanPattern) {
        const chairman = allModels.find((m) =>
          m.id.toLowerCase().includes(preset.chairmanPattern.toLowerCase())
        );
        if (chairman) {
          chairmanId = chairman.id;
          if (!selectedIds.includes(chairmanId) && selectedIds.length < maxModels) {
            selectedIds.push(chairmanId);
          }
        }
      }
    }

    if (selectedIds.length > 0) {
      setSelectedModels(selectedIds);
      setChairmanModel(chairmanId || selectedIds[0]);
      setActivePreset(presetKey);
      // Auto-scroll to first selected model
      setTimeout(() => scrollToModel(selectedIds[0]), 100);
    }
  };

  const toggleModel = (modelId) => {
    setActivePreset(null);
    setSelectedModels((prev) => {
      if (prev.includes(modelId)) {
        if (modelId === chairmanModel) {
          setChairmanModel('');
        }
        return prev.filter((id) => id !== modelId);
      } else {
        // Check max limit
        if (prev.length >= maxModels) {
          return prev; // Don't add more
        }
        return [...prev, modelId];
      }
    });
  };

  const removeSelectedModel = (modelId) => {
    setActivePreset(null);
    if (modelId === chairmanModel) {
      setChairmanModel('');
    }
    setSelectedModels((prev) => prev.filter((id) => id !== modelId));
  };

  const handleChairmanChange = (modelId, event) => {
    if (event) {
      event.stopPropagation();
    }
    setActivePreset(null);
    setChairmanModel(modelId);
    // Auto-select the model if not already selected
    if (modelId && !selectedModels.includes(modelId)) {
      if (selectedModels.length < maxModels) {
        setSelectedModels((prev) => [...prev, modelId]);
      }
    }
  };

  // Get chairman model object for display
  const chairmanModelObject = useMemo(() => {
    return allModels.find((m) => m.id === chairmanModel);
  }, [chairmanModel, allModels]);

  const handleConfirm = () => {
    if (selectedModels.length >= MIN_MODELS && chairmanModel) {
      // Save as last used
      saveLastUsedSelection(selectedModels, chairmanModel);

      onConfirm({
        models: selectedModels,
        chairman: chairmanModel,
      });
      onClose();
    }
  };

  const clearFilters = () => {
    setSearchQuery('');
    setProviderFilter('');
    setTierFilter('');
    setFreeOnlyFilter(false);
    setSortBy('price-asc');
  };

  const isValid = selectedModels.length >= MIN_MODELS && chairmanModel;
  const isMaxReached = selectedModels.length >= maxModels;
  const hasLastUsed = (() => {
    try {
      return !!localStorage.getItem(LAST_USED_KEY);
    } catch {
      return false;
    }
  })();

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="model-selector-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Configure Council</h2>
          <button className="close-button" onClick={onClose}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Presets */}
        <div className="presets-section">
          <h3>Quick Presets</h3>
          <div className="presets-grid">
            {hasLastUsed && (
              <button
                className={`preset-button last-used ${activePreset === 'last' ? 'active' : ''}`}
                onClick={() => loadLastUsedSelection()}
              >
                <span className="preset-name">Last Used</span>
                <span className="preset-description">Your previous selection</span>
              </button>
            )}
            {Object.entries(BUILT_IN_PRESETS).map(([key, preset]) => (
              <button
                key={key}
                className={`preset-button ${activePreset === key ? 'active' : ''}`}
                onClick={() => applyPreset(key)}
                disabled={isLoadingModels}
              >
                <span className="preset-name">{preset.name}</span>
                <span className="preset-description">{preset.description}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Selected Models Summary */}
        {selectedModelObjects.length > 0 && (
          <div className="selected-models-section">
            <h3>
              Selected Models
              <span className="selection-count">
                ({selectedModels.length}/{maxModels})
                {isMaxReached && <span className="max-reached"> - Max reached</span>}
              </span>
            </h3>
            <div className="selected-models-list">
              {selectedModelObjects.map((model, index) => (
                <div
                  key={model.id}
                  className={`selected-model-chip ${model.id === chairmanModel ? 'is-chairman' : ''}`}
                  onClick={() => scrollToModel(model.id)}
                >
                  <button
                    className={`chip-chairman-btn ${model.id === chairmanModel ? 'active' : ''}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleChairmanChange(model.id, e);
                    }}
                    title={model.id === chairmanModel ? 'Current Chairman' : 'Set as Chairman'}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill={model.id === chairmanModel ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2">
                      <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
                    </svg>
                  </button>
                  <span className="chip-index">{index + 1}</span>
                  <span className="chip-name">{model.name}</span>
                  <span className="chip-provider">{model.provider}</span>
                  <button
                    className="chip-remove"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeSelectedModel(model.id);
                    }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="filters-section">
          <div className="filters-row">
            <div className="search-input-wrapper">
              <svg className="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                type="text"
                className="search-input"
                placeholder="Search models..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            <select
              className="filter-select"
              value={providerFilter}
              onChange={(e) => setProviderFilter(e.target.value)}
            >
              <option value="">All Providers</option>
              {providers.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>

            <select
              className="filter-select"
              value={tierFilter}
              onChange={(e) => setTierFilter(e.target.value)}
            >
              <option value="">All Tiers</option>
              <option value="premium">Premium</option>
              <option value="standard">Standard</option>
              <option value="budget">Budget</option>
              <option value="free">Free</option>
            </select>

            <label className="free-only-toggle">
              <input
                type="checkbox"
                checked={freeOnlyFilter}
                onChange={(e) => setFreeOnlyFilter(e.target.checked)}
              />
              <span>Free only</span>
            </label>
          </div>

          <div className="filters-row secondary">
            <select
              className="filter-select sort-select"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            <button className="clear-filters-btn" onClick={clearFilters}>
              Clear Filters
            </button>

            <span className="models-count">
              {filteredModels.length} of {allModels.length} models
            </span>
          </div>
        </div>

        {/* Model Selection */}
        <div className="models-section">
          <h3>
            Select Council Models
            <span className="selection-count">
              ({selectedModels.length} selected, min {MIN_MODELS}, max {maxModels})
            </span>
          </h3>

          {isLoadingModels ? (
            <div className="loading-state">
              <div className="spinner"></div>
              <p>Loading models...</p>
            </div>
          ) : loadError ? (
            <div className="error-state">
              <p>Failed to load models: {loadError}</p>
              <button onClick={loadModels}>Retry</button>
            </div>
          ) : (
            <div className="models-grid" ref={modelsGridRef}>
              {filteredModels.map((model) => {
                const isSelected = selectedModels.includes(model.id);
                const isChairman = model.id === chairmanModel;
                const isDisabled = !isSelected && isMaxReached;
                return (
                  <div
                    key={model.id}
                    ref={(el) => (modelCardRefs.current[model.id] = el)}
                    className={`model-card ${isSelected ? 'selected' : ''} ${isChairman ? 'is-chairman' : ''} ${model.tier} ${isDisabled ? 'disabled' : ''}`}
                    onClick={() => !isDisabled && toggleModel(model.id)}
                    title={isDisabled ? `Maximum ${maxModels} models reached` : model.description}
                  >
                    <div className="model-checkbox">
                      {isSelected && (
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      )}
                    </div>
                    <div className="model-info">
                      <div className="model-name">{model.name}</div>
                      <div className="model-provider">{model.provider}</div>
                      <div className="model-specs">
                        <span className="spec context">{model.context} ctx</span>
                        <span className="spec input">{model.inputPrice} in</span>
                        <span className="spec output">{model.outputPrice} out</span>
                      </div>
                    </div>
                    {model.isFree && <span className="free-badge">FREE</span>}
                    {model.supportsImages && <span className="vision-badge" title="Supports images">V</span>}
                    <button
                      className={`chairman-btn ${isChairman ? 'active' : ''}`}
                      onClick={(e) => handleChairmanChange(model.id, e)}
                      title={isChairman ? 'Current Chairman' : 'Set as Chairman'}
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill={isChairman ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2">
                        <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
                      </svg>
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Chairman Selection */}
        <div className="chairman-section">
          <h3>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1">
              <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
            </svg>
            Chairman (Judge)
          </h3>
          <p className="chairman-hint">
            Click the <span className="star-icon-inline">★</span> star on any model card above to set as Chairman.
            The Chairman synthesizes the final answer from all council responses.
          </p>
          {chairmanModelObject ? (
            <div className="chairman-display">
              <div className="chairman-card">
                <div className="chairman-star">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
                  </svg>
                </div>
                <div className="chairman-info">
                  <div className="chairman-name">{chairmanModelObject.name}</div>
                  <div className="chairman-provider">{chairmanModelObject.provider}</div>
                  <div className="chairman-specs">
                    <span className="spec">{chairmanModelObject.context} ctx</span>
                    <span className="spec">{chairmanModelObject.outputPrice} out</span>
                  </div>
                </div>
                <button
                  className="chairman-scroll-btn"
                  onClick={() => scrollToModel(chairmanModel)}
                  title="Scroll to this model"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                </button>
                <button
                  className="chairman-clear-btn"
                  onClick={() => setChairmanModel('')}
                  title="Clear chairman"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>
            </div>
          ) : (
            <div className="chairman-empty">
              <div className="chairman-empty-icon">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
                </svg>
              </div>
              <p>No chairman selected</p>
              <span>Click the star icon on any model card to select</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="modal-footer">
          <button className="cancel-button" onClick={onClose}>
            Cancel
          </button>
          <button className="confirm-button" onClick={handleConfirm} disabled={!isValid}>
            {isValid
              ? `Create Council (${selectedModels.length} models)`
              : `Select at least ${MIN_MODELS} models and a Chairman`}
          </button>
        </div>
      </div>
    </div>
  );
}

export { BUILT_IN_PRESETS as PRESETS };
