import { useState } from 'react';
import { api } from '../api';
import './SetupWizard.css';

export default function SetupWizard({ onComplete }) {
  const [routerType, setRouterType] = useState('openrouter');
  const [apiKey, setApiKey] = useState('');
  const [tavilyKey, setTavilyKey] = useState('');
  const [exaKey, setExaKey] = useState('');
  const [braveKey, setBraveKey] = useState('');
  // Authentication state
  const [authEnabled, setAuthEnabled] = useState(false);
  const [jwtSecret, setJwtSecret] = useState('');
  const [users, setUsers] = useState([{ username: '', password: '' }]);
  // UI state
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [copiedField, setCopiedField] = useState(null);

  // Generate JWT secret
  const handleGenerateJwt = async () => {
    try {
      const { secret } = await api.generateSecret('jwt');
      setJwtSecret(secret);
    } catch (error) {
      console.error('Failed to generate JWT secret:', error);
      setError('Failed to generate JWT secret');
    }
  };

  // Generate password for a user
  const handleGeneratePassword = async (index) => {
    try {
      const { secret } = await api.generateSecret('password');
      const newUsers = [...users];
      newUsers[index].password = secret;
      setUsers(newUsers);
    } catch (error) {
      console.error('Failed to generate password:', error);
      setError('Failed to generate password');
    }
  };

  // Copy to clipboard
  const copyToClipboard = (text, fieldId) => {
    navigator.clipboard.writeText(text);
    setCopiedField(fieldId);
    setTimeout(() => setCopiedField(null), 2000);
  };

  // Add new user
  const addUser = () => {
    setUsers([...users, { username: '', password: '' }]);
  };

  // Remove user
  const removeUser = (index) => {
    if (users.length > 1) {
      setUsers(users.filter((_, i) => i !== index));
    }
  };

  // Update user field
  const updateUser = (index, field, value) => {
    const newUsers = [...users];
    newUsers[index][field] = value;
    setUsers(newUsers);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (routerType === 'openrouter' && !apiKey) {
      setError('Please enter your OpenRouter API key');
      return;
    }

    // Validate auth if enabled
    if (authEnabled) {
      if (!jwtSecret) {
        setError('Please generate a JWT secret');
        return;
      }
      const validUsers = users.filter(u => u.username && u.password);
      if (validUsers.length === 0) {
        setError('Please add at least one user');
        return;
      }
    }

    setIsLoading(true);

    try {
      const config = { router_type: routerType };
      if (routerType === 'openrouter') {
        config.openrouter_api_key = apiKey;
      }
      // Add Tavily key if provided (optional)
      if (tavilyKey) {
        config.tavily_api_key = tavilyKey;
      }
      // Add Exa key if provided (optional)
      if (exaKey) {
        config.exa_api_key = exaKey;
      }
      // Add Brave key if provided (optional)
      if (braveKey) {
        config.brave_api_key = braveKey;
      }
      // Add auth config if enabled
      config.auth_enabled = authEnabled;
      if (authEnabled) {
        config.jwt_secret = jwtSecret;
        // Convert users array to object
        const usersObj = {};
        users.forEach(u => {
          if (u.username && u.password) {
            usersObj[u.username] = u.password;
          }
        });
        config.auth_users = usersObj;
      }

      await api.saveSetupConfig(config);
      setSuccess(true);

      // Wait a moment then trigger reload
      setTimeout(() => {
        if (typeof onComplete === 'function') {
          onComplete();
          return;
        }
        window.location.reload();
      }, 2000);
    } catch (err) {
      setError(err.message || 'Failed to save configuration');
    } finally {
      setIsLoading(false);
    }
  };

  if (success) {
    return (
      <div className="setup-container">
        <div className="setup-box">
          <div className="setup-success">
            <div className="success-icon">&#10003;</div>
            <h2>Configuration Saved!</h2>
            <p>Reloading application...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="setup-container">
      <div className="setup-box setup-box-wide">
        <div className="setup-header">
          <h1 className="setup-title">Welcome to LLM Council Plus</h1>
          <p className="setup-subtitle">Let's configure your application</p>
        </div>

        <form onSubmit={handleSubmit} className="setup-form">
          {/* Step 1: Choose Router Type */}
          <div className="form-group">
            <label className="form-label">Choose LLM Provider</label>
            <div className="router-options">
              <button
                type="button"
                className={`router-option ${routerType === 'openrouter' ? 'selected' : ''}`}
                onClick={() => setRouterType('openrouter')}
              >
                <div className="router-icon">&#127758;</div>
                <div className="router-name">OpenRouter</div>
                <div className="router-desc">Cloud models (GPT, Claude, Gemini)</div>
              </button>
              <button
                type="button"
                className={`router-option ${routerType === 'ollama' ? 'selected' : ''}`}
                onClick={() => setRouterType('ollama')}
              >
                <div className="router-icon">&#128187;</div>
                <div className="router-name">Ollama</div>
                <div className="router-desc">Local models (no API key)</div>
              </button>
            </div>
          </div>

          {/* Step 2: API Key (only for OpenRouter) */}
          {routerType === 'openrouter' && (
            <div className="form-group">
              <label htmlFor="apiKey" className="form-label">
                OpenRouter API Key
              </label>
              <input
                id="apiKey"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-or-v1-..."
                className="form-input"
                disabled={isLoading}
              />
              <p className="form-hint">
                Get your key at{' '}
                <a href="https://openrouter.ai/keys" target="_blank" rel="noopener noreferrer">
                  openrouter.ai/keys
                </a>
              </p>
            </div>
          )}

          {routerType === 'ollama' && (
            <div className="form-group">
              <div className="ollama-notice">
                <p>
                  <strong>Ollama</strong> must be running locally on port 11434.
                </p>
                <p>
                  Install from{' '}
                  <a href="https://ollama.ai" target="_blank" rel="noopener noreferrer">
                    ollama.ai
                  </a>
                </p>
              </div>
            </div>
          )}

          {/* Optional: Tavily API Key for Web Search */}
          <div className="form-group">
            <label htmlFor="tavilyKey" className="form-label">
              Tavily API Key <span className="optional-badge">Optional</span>
            </label>
            <input
              id="tavilyKey"
              type="password"
              value={tavilyKey}
              onChange={(e) => setTavilyKey(e.target.value)}
              placeholder="tvly-..."
              className="form-input"
              disabled={isLoading}
            />
            <p className="form-hint">
              Enables advanced web search. Get key at{' '}
              <a href="https://tavily.com" target="_blank" rel="noopener noreferrer">
                tavily.com
              </a>
            </p>
          </div>

          {/* Optional: Exa API Key for AI-powered Web Search */}
          <div className="form-group">
            <label htmlFor="exaKey" className="form-label">
              Exa API Key <span className="optional-badge">Optional</span>
            </label>
            <input
              id="exaKey"
              type="password"
              value={exaKey}
              onChange={(e) => setExaKey(e.target.value)}
              placeholder="..."
              className="form-input"
              disabled={isLoading}
            />
            <p className="form-hint">
              AI-powered web search alternative. Get key at{' '}
              <a href="https://exa.ai" target="_blank" rel="noopener noreferrer">
                exa.ai
              </a>
            </p>
          </div>

          {/* Optional: Brave API Key for Web Search */}
          <div className="form-group">
            <label htmlFor="braveKey" className="form-label">
              Brave Search API Key <span className="optional-badge">Optional</span>
            </label>
            <input
              id="braveKey"
              type="password"
              value={braveKey}
              onChange={(e) => setBraveKey(e.target.value)}
              placeholder="..."
              className="form-input"
              disabled={isLoading}
            />
            <p className="form-hint">
              Enables Brave Search. Provide your Brave Search API key.
            </p>
          </div>

          {/* Authentication Section */}
          <div className="form-group">
            <label className="form-label">
              Authentication <span className="optional-badge">Optional</span>
            </label>
            <label className="auth-toggle">
              <input
                type="checkbox"
                checked={authEnabled}
                onChange={(e) => setAuthEnabled(e.target.checked)}
                disabled={isLoading}
              />
              <span className="auth-toggle-label">Enable user authentication</span>
            </label>
          </div>

          {/* Auth Config (shown when enabled) */}
          {authEnabled && (
            <div className="auth-config">
              {/* JWT Secret */}
              <div className="form-group">
                <label htmlFor="jwtSecret" className="form-label">
                  JWT Secret
                </label>
                <div className="input-with-button">
                  <input
                    id="jwtSecret"
                    type="text"
                    value={jwtSecret}
                    onChange={(e) => setJwtSecret(e.target.value)}
                    placeholder="Click Generate to create a secure secret"
                    className="form-input"
                    disabled={isLoading}
                    readOnly
                  />
                  <button
                    type="button"
                    className="generate-btn"
                    onClick={handleGenerateJwt}
                    disabled={isLoading}
                  >
                    Generate
                  </button>
                  {jwtSecret && (
                    <button
                      type="button"
                      className="copy-btn"
                      onClick={() => copyToClipboard(jwtSecret, 'jwt')}
                      disabled={isLoading}
                    >
                      {copiedField === 'jwt' ? '✓' : '📋'}
                    </button>
                  )}
                </div>
              </div>

              {/* Users */}
              <div className="form-group">
                <label className="form-label">Users</label>
                <div className="users-list">
                  {users.map((user, index) => (
                    <div key={index} className="user-row">
                      <input
                        type="text"
                        value={user.username}
                        onChange={(e) => updateUser(index, 'username', e.target.value)}
                        placeholder="Username"
                        className="form-input user-input"
                        disabled={isLoading}
                      />
                      <div className="password-field">
                        <input
                          type="text"
                          value={user.password}
                          onChange={(e) => updateUser(index, 'password', e.target.value)}
                          placeholder="Password"
                          className="form-input user-input"
                          disabled={isLoading}
                        />
                        <button
                          type="button"
                          className="generate-btn small"
                          onClick={() => handleGeneratePassword(index)}
                          disabled={isLoading}
                          title="Generate password"
                        >
                          Gen
                        </button>
                        {user.password && (
                          <button
                            type="button"
                            className="copy-btn small"
                            onClick={() => copyToClipboard(user.password, `pwd-${index}`)}
                            disabled={isLoading}
                            title="Copy password"
                          >
                            {copiedField === `pwd-${index}` ? '✓' : '📋'}
                          </button>
                        )}
                      </div>
                      {users.length > 1 && (
                        <button
                          type="button"
                          className="remove-btn"
                          onClick={() => removeUser(index)}
                          disabled={isLoading}
                          title="Remove user"
                        >
                          ×
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                <button
                  type="button"
                  className="add-user-btn"
                  onClick={addUser}
                  disabled={isLoading}
                >
                  + Add User
                </button>
              </div>
            </div>
          )}

          {error && <div className="error-message">{error}</div>}

          <button
            type="submit"
            disabled={isLoading || (routerType === 'openrouter' && !apiKey)}
            className="submit-button"
          >
            {isLoading ? 'Saving...' : 'Complete Setup'}
          </button>
        </form>

        <p className="setup-footer">
          Configuration will be saved to .env file
        </p>
      </div>
    </div>
  );
}
