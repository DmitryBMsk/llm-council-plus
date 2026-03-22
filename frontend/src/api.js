/**
 * API client for the LLM-TTCC-TEAM-PRO backend.
 * Uses relative paths in production (nginx proxy) or localhost in development.
 */

const API_BASE = import.meta.env.VITE_API_BASE || '';

/**
 * Get the auth token from localStorage (Zustand persisted store).
 * @returns {string|null} The auth token or null if not authenticated
 */
function getAuthToken() {
  try {
    const authData = localStorage.getItem('llm-ttcc-team-pro-auth');
    if (authData) {
      const parsed = JSON.parse(authData);
      if (parsed.state && parsed.state.token) {
        // Check if token is not expired
        if (parsed.state.expiresAt && Date.now() < parsed.state.expiresAt) {
          return parsed.state.token;
        }
      }
    }
  } catch (e) {
    console.error('Failed to get auth token:', e);
  }
  return null;
}

/**
 * Get headers for authenticated requests.
 * @param {Object} additionalHeaders - Additional headers to include
 * @returns {Object} Headers object with Authorization if authenticated
 */
function getAuthHeaders(additionalHeaders = {}) {
  const headers = { ...additionalHeaders };
  const token = getAuthToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Handle 401 response by triggering logout.
 * This clears the auth state and redirects to login.
 */
function handleUnauthorized() {
  // Clear auth state in localStorage
  try {
    localStorage.removeItem('llm-ttcc-team-pro-auth');
  } catch (e) {
    console.error('Failed to clear auth state:', e);
  }
  // Reload the page to trigger login screen
  window.location.reload();
}

/**
 * Make an authenticated fetch request.
 * Handles 401 responses by triggering logout.
 * @param {string} url - The URL to fetch
 * @param {Object} options - Fetch options
 * @returns {Promise<Response>} The fetch response
 */
async function authFetch(url, options = {}) {
  const headers = getAuthHeaders(options.headers || {});
  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    handleUnauthorized();
    throw new Error('Session expired. Please log in again.');
  }

  return response;
}

export const api = {
  /**
   * Get authentication status from backend.
   * Public endpoint - no auth required.
   * @returns {Promise<{auth_enabled: boolean}>}
   */
  async getAuthStatus() {
    const response = await fetch(`${API_BASE}/api/auth/status`);
    if (!response.ok) {
      throw new Error('Failed to get auth status');
    }
    return response.json();
  },

  /**
   * Upload and parse a file. Requires authentication.
   * @param {File} file - The file to upload
   * @returns {Promise<{filename: string, file_type: string, content: string, char_count: number}>}
   */
  async uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    const token = getAuthToken();
    const headers = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}/api/upload`, {
      method: 'POST',
      headers,
      body: formData,
    });

    if (response.status === 401) {
      handleUnauthorized();
      throw new Error('Session expired. Please log in again.');
    }

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to upload file');
    }

    return response.json();
  },

  /**
   * List all conversations. Requires authentication.
   */
  async listConversations() {
    const response = await authFetch(`${API_BASE}/api/conversations`);
    if (!response.ok) {
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  /**
   * Create a new conversation. Requires authentication.
   * @param {Object} options - Optional configuration
   * @param {string[]} options.models - Council model IDs
   * @param {string} options.chairman - Chairman/judge model ID
   * @param {string} options.username - Username who created the conversation
   */
  async createConversation(options = {}) {
    const body = {};
    if (options.models) {
      body.models = options.models;
    }
    if (options.chairman) {
      body.chairman = options.chairman;
    }
    if (options.executionMode) {
      body.execution_mode = options.executionMode;
    }
    if (options.routerType) {
      body.router_type = options.routerType;
    }
    if (options.username) {
      body.username = options.username;
    }
    if (options.systemPrompt) {
      body.system_prompt = options.systemPrompt;
    }

    const response = await authFetch(`${API_BASE}/api/conversations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error('Failed to create conversation');
    }
    return response.json();
  },

  /**
   * Get runtime settings (prompts + temperatures). Requires authentication.
   */
  async getRuntimeSettings() {
    const response = await authFetch(`${API_BASE}/api/settings`);
    if (!response.ok) {
      throw new Error('Failed to get runtime settings');
    }
    return response.json();
  },

  /**
   * Patch runtime settings (prompts + temperatures). Requires authentication.
   * @param {Object} patch - Partial settings payload
   */
  async updateRuntimeSettings(patch) {
    const response = await authFetch(`${API_BASE}/api/settings`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(patch || {}),
    });
    if (!response.ok) {
      throw new Error('Failed to update runtime settings');
    }
    return response.json();
  },

  /**
   * Get default runtime settings. Requires authentication.
   */
  async getRuntimeSettingsDefaults() {
    const response = await authFetch(`${API_BASE}/api/settings/defaults`);
    if (!response.ok) {
      throw new Error('Failed to get runtime settings defaults');
    }
    return response.json();
  },

  /**
   * Reset runtime settings to defaults. Requires authentication.
   */
  async resetRuntimeSettings() {
    const response = await authFetch(`${API_BASE}/api/settings/reset`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw new Error('Failed to reset runtime settings');
    }
    return response.json();
  },

  /**
   * Export runtime settings. Requires authentication.
   */
  async exportRuntimeSettings() {
    const response = await authFetch(`${API_BASE}/api/settings/export`);
    if (!response.ok) {
      throw new Error('Failed to export runtime settings');
    }
    return response.json();
  },

  /**
   * Import runtime settings. Requires authentication.
   * @param {Object} config - Full RuntimeSettings object
   */
  async importRuntimeSettings(config) {
    const response = await authFetch(`${API_BASE}/api/settings/import`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(config || {}),
    });
    if (!response.ok) {
      throw new Error('Failed to import runtime settings');
    }
    return response.json();
  },

  /**
   * Get a specific conversation. Requires authentication.
   */
  async getConversation(conversationId) {
    const response = await authFetch(
      `${API_BASE}/api/conversations/${conversationId}`
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  /**
   * Send a message in a conversation. Requires authentication.
   */
  async sendMessage(conversationId, content) {
    const response = await authFetch(
      `${API_BASE}/api/conversations/${conversationId}/message`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to send message');
    }
    return response.json();
  },

  /**
   * Delete a specific conversation. Requires authentication.
   */
  async deleteConversation(conversationId) {
    const response = await authFetch(
      `${API_BASE}/api/conversations/${conversationId}`,
      {
        method: 'DELETE',
      }
    );
    if (!response.ok) {
      throw new Error('Failed to delete conversation');
    }
    return response.json();
  },

  /**
   * Delete all conversations. Requires authentication.
   */
  async deleteAllConversations() {
    const response = await authFetch(`${API_BASE}/api/conversations`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      throw new Error('Failed to delete all conversations');
    }
    return response.json();
  },

  /**
   * Update conversation title (Feature 5). Requires authentication.
   * @param {string} conversationId - The conversation ID
   * @param {string} title - New title for the conversation
   * @returns {Promise<{success: boolean, message: string, title: string}>}
   */
  async updateConversationTitle(conversationId, title) {
    const response = await authFetch(
      `${API_BASE}/api/conversations/${conversationId}/title`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ title }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to update conversation title');
    }
    return response.json();
  },

  /**
   * Send a message and receive streaming updates. Requires authentication.
   * @param {string} conversationId - The conversation ID
   * @param {string} content - The message content
   * @param {function} onEvent - Callback function for each event: (eventType, data) => void
   * @param {Array} attachments - Optional array of file attachments
   * @param {string} webSearchProvider - Web search provider: 'off', 'duckduckgo', 'tavily', 'exa', or 'brave'
   * @param {Object} options - Optional fetch options (e.g., { signal })
   * @returns {Promise<void>}
   */
  async sendMessageStream(conversationId, content, onEvent, attachments = null, webSearchProvider = 'off', options = {}) {
    const body = { content };
    if (attachments && attachments.length > 0) {
      body.attachments = attachments;
    }
    if (webSearchProvider && webSearchProvider !== 'off') {
      body.web_search_provider = webSearchProvider;
    }

    const response = await authFetch(
      `${API_BASE}/api/conversations/${conversationId}/message/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: options?.signal,
      }
    );

    if (!response.ok) {
      throw new Error('Failed to send message');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');

      // Keep the last incomplete line in the buffer
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          try {
            const event = JSON.parse(data);
            onEvent(event.type, event);
          } catch (e) {
            console.error('Failed to parse SSE event:', e);
          }
        }
      }
    }

    // Process any remaining data in buffer
    if (buffer.startsWith('data: ')) {
      const data = buffer.slice(6);
      try {
        const event = JSON.parse(data);
        onEvent(event.type, event);
      } catch {
        // Ignore incomplete final chunk
      }
    }
  },

  /**
   * Get Google Drive configuration status. (Public endpoint)
   * @returns {Promise<{enabled: boolean, configured: boolean, folder_id: string|null}>}
   */
  async getDriveStatus() {
    const response = await fetch(`${API_BASE}/api/drive/status`);
    if (!response.ok) {
      throw new Error('Failed to get drive status');
    }
    return response.json();
  },

  /**
   * Upload content to Google Drive. Requires authentication.
   * @param {string} filename - Name of the file
   * @param {string} content - Markdown content
   * @returns {Promise<{success: boolean, file: {id: string, name: string, webViewLink: string}}>}
   */
  async uploadToDrive(filename, content) {
    const response = await authFetch(`${API_BASE}/api/drive/upload`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ filename, content }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to upload to Google Drive');
    }
    return response.json();
  },

  /**
   * Get API version. (Public endpoint)
   * @returns {Promise<{version: string}>}
   */
  async getVersion() {
    const response = await fetch(`${API_BASE}/api/version`);
    if (!response.ok) {
      return { version: 'unknown' };
    }
    return response.json();
  },

  /**
   * Get list of valid usernames. (Public endpoint)
   * @returns {Promise<{users: string[]}>}
   */
  async getUsers() {
    const response = await fetch(`${API_BASE}/api/users`);
    if (!response.ok) {
      return { users: [] };
    }
    return response.json();
  },

  /**
   * Get setup status. (Public endpoint)
   * @returns {Promise<{setup_required: boolean, router_type: string, has_api_key: boolean, message: string}>}
   */
  async getSetupStatus() {
    const response = await fetch(`${API_BASE}/api/setup/status`);
    if (!response.ok) {
      throw new Error('Failed to get setup status');
    }
    return response.json();
  },

  /**
   * Get available system prompt presets (e.g., TTCC mode).
   * @returns {Promise<{presets: Array<{id: string, name: string, prompt: string|null}>}>}
   */
  async getSystemPromptPresets() {
    const response = await authFetch(`${API_BASE}/api/system-prompt-presets`);
    if (!response.ok) {
      throw new Error('Failed to get system prompt presets');
    }
    return response.json();
  },

  /**
   * Save setup configuration. (Public endpoint, only works when setup is required)
   * @param {Object} config - Configuration to save
   * @param {string} config.openrouter_api_key - OpenRouter API key
   * @param {string} config.router_type - Router type (openrouter or ollama)
   * @returns {Promise<{success: boolean, message: string, restart_required: boolean}>}
   */
  async saveSetupConfig(config) {
    const response = await fetch(`${API_BASE}/api/setup/config`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(config),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to save configuration');
    }
    return response.json();
  },

  /**
   * Generate a secure secret for JWT or password. (Public endpoint)
   * @param {string} type - 'jwt' for JWT secret or 'password' for user password
   * @returns {Promise<{secret: string, type: string}>}
   */
  async generateSecret(type = 'jwt') {
    const response = await fetch(`${API_BASE}/api/setup/generate-secret?type=${type}`);
    if (!response.ok) {
      throw new Error('Failed to generate secret');
    }
    return response.json();
  },

  /**
   * Get available models from OpenRouter or Ollama. (Public endpoint)
   * @returns {Promise<{models: Array, router_type: string, count: number}>}
   */
  async getModels(options = {}) {
    const params = new URLSearchParams();
    if (options.routerType) {
      params.set('router_type', options.routerType);
    }
    const qs = params.toString();
    const url = `${API_BASE}/api/models${qs ? `?${qs}` : ''}`;

    const response = await fetch(url);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to fetch models');
    }
    return response.json();
  },
};
