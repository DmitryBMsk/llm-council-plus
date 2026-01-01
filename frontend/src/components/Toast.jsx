import { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import './Toast.css';

/**
 * Toast notification component for displaying temporary messages.
 * Supports multiple toast types: info, success, warning, error.
 */
export default function Toast({ message, type, duration, onClose }) {
  const [isVisible, setIsVisible] = useState(true);
  const [isLeaving, setIsLeaving] = useState(false);

  const handleClose = useCallback(() => {
    setIsLeaving(true);
    setTimeout(() => {
      setIsVisible(false);
      onClose?.();
    }, 300); // Match CSS animation duration
  }, [onClose]);

  useEffect(() => {
    if (duration > 0) {
      const timer = setTimeout(handleClose, duration);
      return () => clearTimeout(timer);
    }
  }, [duration, handleClose]);

  if (!isVisible) return null;

  const icons = {
    info: '💡',
    success: '✓',
    warning: '⚠',
    error: '✕',
  };

  return (
    <div className={`toast toast-${type} ${isLeaving ? 'toast-leaving' : ''}`}>
      <span className="toast-icon">{icons[type] || icons.info}</span>
      <span className="toast-message">{message}</span>
      <button className="toast-close" onClick={handleClose}>×</button>
    </div>
  );
}

Toast.propTypes = {
  message: PropTypes.string.isRequired,
  type: PropTypes.oneOf(['info', 'success', 'warning', 'error']),
  duration: PropTypes.number,
  onClose: PropTypes.func,
};

Toast.defaultProps = {
  type: 'info',
  duration: 5000,
  onClose: null,
};

/**
 * Toast container component that manages multiple toasts.
 */
export function ToastContainer({ toasts, onRemove }) {
  return (
    <div className="toast-container">
      {toasts.map((toast) => (
        <Toast
          key={toast.id}
          message={toast.message}
          type={toast.type}
          duration={toast.duration}
          onClose={() => onRemove(toast.id)}
        />
      ))}
    </div>
  );
}

ToastContainer.propTypes = {
  toasts: PropTypes.arrayOf(
    PropTypes.shape({
      id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
      message: PropTypes.string.isRequired,
      type: PropTypes.string,
      duration: PropTypes.number,
    })
  ).isRequired,
  onRemove: PropTypes.func.isRequired,
};
