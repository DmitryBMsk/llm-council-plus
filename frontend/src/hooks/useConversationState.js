import { useState } from 'react';

// Setters capture the conversation key that started an action. A late upload
// can therefore finish after navigation without mutating the newly shown draft.
export function useConversationState(conversationId, initialValue) {
  const [values, setValues] = useState({});
  const value = values[conversationId] ?? initialValue;
  const setValue = (update) => {
    if (!conversationId) return;
    setValues(previous => ({
      ...previous,
      [conversationId]: typeof update === 'function'
        ? update(previous[conversationId] ?? initialValue) : update,
    }));
  };
  return [value, setValue];
}
