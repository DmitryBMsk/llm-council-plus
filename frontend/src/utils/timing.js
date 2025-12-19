/**
 * Timing utilities for formatting durations and timestamps.
 * Shared across Stage1, Stage2, Stage3, and ChatInterface components.
 */

/**
 * Format a duration in seconds to a human-readable string.
 * @param {number} seconds - Duration in seconds
 * @returns {string|null} Formatted duration or null if invalid
 */
export function formatDuration(seconds) {
  if (!seconds) return null;
  if (seconds < 1) {
    return `${Math.round(seconds * 1000)}ms`;
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
}

/**
 * Format a Unix timestamp to a time string (HH:mm:ss.S).
 * @param {number} timestamp - Unix timestamp in seconds
 * @returns {string|null} Formatted time or null if invalid
 */
export function formatTimestamp(timestamp) {
  if (!timestamp) return null;
  const date = new Date(timestamp * 1000);
  // 24-hour format: HH:mm:ss.S
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  const seconds = String(date.getSeconds()).padStart(2, '0');
  const milliseconds = String(Math.floor(date.getMilliseconds() / 100)).padStart(1, '0');
  return `${hours}:${minutes}:${seconds}.${milliseconds}`;
}
