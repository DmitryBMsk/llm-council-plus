import { useState, useEffect } from 'react';
import { api } from '../api';
import './LoginScreen.css';

export default function LoginScreen({ onLogin }) {
  const [users, setUsers] = useState([]);
  const [selectedUser, setSelectedUser] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingUsers, setIsLoadingUsers] = useState(true);
  const [version, setVersion] = useState('');

  // Fetch users and version from backend API on mount
  useEffect(() => {
    async function fetchData() {
      try {
        const [usersResponse, versionResponse] = await Promise.all([
          api.getUsers(),
          api.getVersion()
        ]);
        setUsers(usersResponse.users || []);
        setVersion(versionResponse.version || '');
      } catch (err) {
        console.error('Failed to fetch data:', err);
        setError('Failed to load data');
      } finally {
        setIsLoadingUsers(false);
      }
    }
    fetchData();
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!selectedUser) {
      setError('Please enter username');
      return;
    }

    if (!password) {
      setError('Please enter password');
      return;
    }

    setIsLoading(true);

    try {
      const apiBase = import.meta.env.VITE_API_BASE || '';
      const response = await fetch(`${apiBase}/api/auth`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username: selectedUser,
          password,
        }),
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        setError(data.error || 'Login failed');
        return;
      }

      onLogin(data.user.username, data.token, data.expiresAt);
    } catch (err) {
      setError(err.message || 'Network error');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-box">
        {/* Logo */}
        <div className="login-header">
          <div className="login-logo">
            <svg width="120" height="120" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" className="login-logo-svg">
              {/* Central node */}
              <circle cx="60" cy="60" r="20" fill="#4a90e2" />
              {/* Surrounding nodes representing council members */}
              <circle cx="60" cy="20" r="12" fill="#6ba3e8" />
              <circle cx="94" cy="40" r="12" fill="#6ba3e8" />
              <circle cx="94" cy="80" r="12" fill="#6ba3e8" />
              <circle cx="60" cy="100" r="12" fill="#6ba3e8" />
              <circle cx="26" cy="80" r="12" fill="#6ba3e8" />
              <circle cx="26" cy="40" r="12" fill="#6ba3e8" />
              {/* Connection lines */}
              <line x1="60" y1="40" x2="60" y2="32" stroke="#4a90e2" strokeWidth="2" />
              <line x1="77" y1="50" x2="85" y2="45" stroke="#4a90e2" strokeWidth="2" />
              <line x1="77" y1="70" x2="85" y2="75" stroke="#4a90e2" strokeWidth="2" />
              <line x1="60" y1="80" x2="60" y2="88" stroke="#4a90e2" strokeWidth="2" />
              <line x1="43" y1="70" x2="35" y2="75" stroke="#4a90e2" strokeWidth="2" />
              <line x1="43" y1="50" x2="35" y2="45" stroke="#4a90e2" strokeWidth="2" />
              {/* Inner symbol - representing synthesis */}
              <text x="60" y="66" textAnchor="middle" fill="white" fontSize="18" fontWeight="bold">∑</text>
            </svg>
          </div>
          <h1 className="login-title">LLM Council Plus</h1>
          <p className="login-subtitle">Please sign in to continue</p>
        </div>

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="login-form">
          {/* User Selection */}
          <div className="form-group">
            <label className="form-label">
              {users.length > 0 ? 'Select User' : 'Username'}
            </label>
            {isLoadingUsers ? (
              <span className="loading-users">Loading...</span>
            ) : users.length === 0 ? (
              /* Production mode: manual username input */
              <input
                id="username"
                type="text"
                value={selectedUser}
                onChange={(e) => setSelectedUser(e.target.value)}
                placeholder="Enter username"
                className="form-input"
                disabled={isLoading}
                autoComplete="username"
              />
            ) : (
              /* Demo mode: user buttons */
              <div className="user-buttons">
                {users.map((user) => (
                  <button
                    key={user}
                    type="button"
                    onClick={() => setSelectedUser(user)}
                    className={`user-button ${selectedUser === user ? 'selected' : ''}`}
                  >
                    {user}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Password Input */}
          <div className="form-group">
            <label htmlFor="password" className="form-label">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              className="form-input"
              autoComplete="current-password"
              disabled={isLoading}
            />
          </div>

          {/* Error Message */}
          {error && (
            <div className="error-message">
              {error}
            </div>
          )}

          {/* Submit Button */}
          <button
            type="submit"
            disabled={isLoading || !selectedUser || !password}
            className="submit-button"
          >
            {isLoading ? (
              <span className="loading-text">
                <svg className="spinner" viewBox="0 0 24 24">
                  <circle className="spinner-bg" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="spinner-fg" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                Signing in...
              </span>
            ) : (
              'Sign In'
            )}
          </button>
        </form>

        {/* Footer */}
        <p className="login-footer">
          Your data is protected and secure
          {version && <span className="version-info">v{version}</span>}
        </p>
      </div>
    </div>
  );
}
