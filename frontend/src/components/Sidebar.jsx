import { useState, useEffect, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import PropTypes from 'prop-types';
import { api } from '../api';
import { useAuthStore } from '../store/authStore';
import { formatRelativeDate } from '../utils/timing';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onOpenSettings,
  onDeleteConversation,
  onDeleteAllConversations,
  onUpdateTitle,
}) {
  const [deletingIds, setDeletingIds] = useState(new Set());
  const [version, setVersion] = useState('');
  const [users, setUsers] = useState(['All']);
  const [userFilter, setUserFilter] = useState('All');
  const [searchQuery, setSearchQuery] = useState('');
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [menuOpenId, setMenuOpenId] = useState(null);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const menuButtonRefs = useRef({});
  const searchInputRef = useRef(null);

  // Auth state
  const { username, logout, isAuthenticated } = useAuthStore();

  // Filter conversations by user and search query
  const filteredConversations = useMemo(() => {
    let result = conversations;

    // Filter by user
    if (userFilter !== 'All') {
      result = result.filter(conv => conv.username === userFilter);
    }

    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase().trim();
      result = result.filter(conv =>
        (conv.title || '').toLowerCase().includes(query)
      );
    }

    return result;
  }, [conversations, userFilter, searchQuery]);

  useEffect(() => {
    api.getVersion().then(({ version }) => setVersion(version));
    api.getUsers().then(({ users: fetchedUsers }) => {
      if (fetchedUsers && fetchedUsers.length > 0) {
        setUsers(['All', ...fetchedUsers]);
      }
    });
  }, []);

  // Feature 5: Title editing handlers
  const handleStartEdit = (e, conv) => {
    e.stopPropagation();
    setMenuOpenId(null);
    setEditingId(conv.id);
    setEditTitle(conv.title || 'New Conversation');
  };

  const handleSaveEdit = async (conversationId) => {
    if (editTitle.trim() && onUpdateTitle) {
      await onUpdateTitle(conversationId, editTitle.trim());
    }
    setEditingId(null);
  };

  const handleKeyPress = (e, conversationId) => {
    if (e.key === 'Enter') {
      handleSaveEdit(conversationId);
    } else if (e.key === 'Escape') {
      setEditingId(null);
    }
  };

  const toggleMenu = (e, conversationId) => {
    e.stopPropagation();
    if (menuOpenId === conversationId) {
      setMenuOpenId(null);
    } else {
      // Calculate position from button
      const button = menuButtonRefs.current[conversationId];
      if (button) {
        const rect = button.getBoundingClientRect();
        setMenuPosition({
          top: rect.bottom + 4,
          left: rect.right - 140, // 140px is min-width of dropdown
        });
      }
      setMenuOpenId(conversationId);
    }
  };

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuOpenId && !e.target.closest('.menu-dropdown-portal') && !e.target.closest('.menu-btn')) {
        setMenuOpenId(null);
      }
    };
    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, [menuOpenId]);

  const handleDeleteClick = async (id, e) => {
    e.stopPropagation();
    if (!window.confirm('Are you sure you want to delete this conversation?')) {
      return;
    }

    // Start deletion animation
    setDeletingIds(prev => new Set(prev).add(id));

    // Wait for animation to complete, then delete
    setTimeout(async () => {
      await onDeleteConversation(id, e);
      setDeletingIds(prev => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, 300); // Match CSS animation duration
  };

  const handleDeleteAllClick = async () => {
    if (!window.confirm('Are you sure you want to delete ALL conversations? This cannot be undone.')) {
      return;
    }

    // Start deletion animation for all items
    const allIds = new Set(conversations.map(conv => conv.id));
    setDeletingIds(allIds);

    // Wait for animation, then delete all
    setTimeout(async () => {
      await onDeleteAllConversations();
      setDeletingIds(new Set());
    }, 300);
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-title-row">
          <svg width="32" height="32" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" className="sidebar-logo-svg">
            <circle cx="60" cy="60" r="20" fill="#4a90e2" />
            <circle cx="60" cy="20" r="10" fill="#6ba3e8" />
            <circle cx="94" cy="40" r="10" fill="#6ba3e8" />
            <circle cx="94" cy="80" r="10" fill="#6ba3e8" />
            <circle cx="60" cy="100" r="10" fill="#6ba3e8" />
            <circle cx="26" cy="80" r="10" fill="#6ba3e8" />
            <circle cx="26" cy="40" r="10" fill="#6ba3e8" />
            <line x1="60" y1="40" x2="60" y2="30" stroke="#4a90e2" strokeWidth="3" />
            <line x1="77" y1="50" x2="87" y2="43" stroke="#4a90e2" strokeWidth="3" />
            <line x1="77" y1="70" x2="87" y2="77" stroke="#4a90e2" strokeWidth="3" />
            <line x1="60" y1="80" x2="60" y2="90" stroke="#4a90e2" strokeWidth="3" />
            <line x1="43" y1="70" x2="33" y2="77" stroke="#4a90e2" strokeWidth="3" />
            <line x1="43" y1="50" x2="33" y2="43" stroke="#4a90e2" strokeWidth="3" />
            <text x="60" y="66" textAnchor="middle" fill="white" fontSize="20" fontWeight="bold">∑</text>
          </svg>
          <span className="sidebar-title-text">LLM Council Plus</span>
        </div>

        <div className="sidebar-actions">
          <button className="new-conversation-btn" onClick={onNewConversation}>
            + New Conversation
          </button>

          <div className="sidebar-actions-row">
            {onOpenSettings && (
              <button
                className="sidebar-action-btn sidebar-action-btn--secondary"
                onClick={onOpenSettings}
                title="Edit prompts and temperatures"
                type="button"
              >
                <span className="sidebar-action-btn__icon" aria-hidden="true">⚙︎</span>
                <span>Settings</span>
              </button>
            )}
          </div>
        </div>

        {/* Search input */}
        <div className="search-container">
          <input
            ref={searchInputRef}
            type="text"
            className="search-input"
            placeholder="Search conversations..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              className="search-clear-btn"
              onClick={() => {
                setSearchQuery('');
                searchInputRef.current?.focus();
              }}
              title="Clear search"
            >
              ×
            </button>
          )}
        </div>

        {/* User filter */}
        <div className="user-filter">
          {users.map((user) => (
            <button
              key={user}
              className={`filter-btn ${userFilter === user ? 'active' : ''}`}
              onClick={() => setUserFilter(user)}
            >
              {user}
            </button>
          ))}
        </div>
      </div>

      <div className="conversation-list">
        {filteredConversations.length === 0 ? (
          <div className="no-conversations">
            {conversations.length === 0
              ? 'No conversations yet'
              : searchQuery
                ? 'No matching conversations'
                : 'No conversations for this user'}
          </div>
        ) : (
          filteredConversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              } ${deletingIds.has(conv.id) ? 'deleting' : ''}`}
              onClick={() => !deletingIds.has(conv.id) && onSelectConversation(conv.id)}
            >
              <div className="conversation-content">
                {editingId === conv.id ? (
                  <input
                    className="edit-title-input"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    onBlur={() => handleSaveEdit(conv.id)}
                    onKeyDown={(e) => handleKeyPress(e, conv.id)}
                    onClick={(e) => e.stopPropagation()}
                    autoFocus
                  />
                ) : (
                  <div className="conversation-title">
                    {conv.title || 'New Conversation'}
                  </div>
                )}
                <div className="conversation-meta">
                  <span className="meta-date">{formatRelativeDate(conv.created_at)}</span>
                  <span className="meta-separator">·</span>
                  <span className="meta-count">{conv.message_count} msgs</span>
                  {conv.username && (
                    <>
                      <span className="meta-separator">·</span>
                      <span className="meta-user">{conv.username}</span>
                    </>
                  )}
                </div>
              </div>

              {/* Feature 5: 3-dot menu */}
              <div className="conversation-actions">
                <button
                  ref={(el) => (menuButtonRefs.current[conv.id] = el)}
                  className="menu-btn"
                  onClick={(e) => toggleMenu(e, conv.id)}
                  title="Options"
                >
                  ⋮
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Portal for dropdown menu - rendered outside scrollable container */}
      {menuOpenId && createPortal(
        <div
          className="menu-dropdown-portal"
          style={{
            position: 'fixed',
            top: menuPosition.top,
            left: menuPosition.left,
            zIndex: 9999,
          }}
        >
          <div className="menu-dropdown">
            <button
              className="menu-item"
              onClick={(e) => {
                const conv = conversations.find(c => c.id === menuOpenId);
                if (conv) handleStartEdit(e, conv);
              }}
            >
              ✏️ Edit title
            </button>
            <button
              className="menu-item delete"
              onClick={(e) => handleDeleteClick(menuOpenId, e)}
            >
              🗑️ Delete
            </button>
          </div>
        </div>,
        document.body
      )}

      <div className="sidebar-footer">
        {isAuthenticated && username && (
          <div className="user-status">
            <span className="user-avatar">{username.charAt(0).toUpperCase()}</span>
            <span className="user-name">{username}</span>
            <button className="logout-btn" onClick={logout} title="Sign out">
              ↪
            </button>
          </div>
        )}

        <div className="sidebar-footer-row">
          {version && <span className="version-badge">v{version}</span>}
          {conversations.length > 0 && (
            <button
              className="sidebar-action-btn sidebar-action-btn--danger sidebar-action-btn--compact"
              onClick={handleDeleteAllClick}
              title="Delete all conversations"
              type="button"
            >
              <span className="sidebar-action-btn__icon" aria-hidden="true">🗑</span>
              <span>Delete All</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

Sidebar.propTypes = {
  conversations: PropTypes.array.isRequired,
  currentConversationId: PropTypes.string,
  onSelectConversation: PropTypes.func.isRequired,
  onNewConversation: PropTypes.func.isRequired,
  onOpenSettings: PropTypes.func,
  onDeleteConversation: PropTypes.func.isRequired,
  onDeleteAllConversations: PropTypes.func.isRequired,
  onUpdateTitle: PropTypes.func,
};

Sidebar.propTypes = {
  conversations: PropTypes.arrayOf(
    PropTypes.shape({
      id: PropTypes.string.isRequired,
      title: PropTypes.string,
      message_count: PropTypes.number,
      username: PropTypes.string,
      created_at: PropTypes.string,
    })
  ).isRequired,
  currentConversationId: PropTypes.string,
  onSelectConversation: PropTypes.func.isRequired,
  onNewConversation: PropTypes.func.isRequired,
  onDeleteConversation: PropTypes.func.isRequired,
  onDeleteAllConversations: PropTypes.func.isRequired,
  onUpdateTitle: PropTypes.func,
};

Sidebar.defaultProps = {
  currentConversationId: null,
  onUpdateTitle: null,
};
