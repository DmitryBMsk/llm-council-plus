import { useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import './SearchContext.css';

function safeParseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function parseResultBlock(block) {
  const lines = block.split('\n');
  const titleLine = lines.find((l) => l.startsWith('Title: '));
  const urlLine = lines.find((l) => l.startsWith('URL: '));
  const summaryIdx = lines.findIndex((l) => l.startsWith('Summary: '));
  const contentIdx = lines.findIndex((l) => l.startsWith('Content:'));

  const title = titleLine ? titleLine.replace('Title: ', '').trim() : '';
  const url = urlLine ? urlLine.replace('URL: ', '').trim() : '';

  let kind = '';
  let body = '';
  if (contentIdx >= 0) {
    kind = 'content';
    body = lines.slice(contentIdx + 1).join('\n').trim();
  } else if (summaryIdx >= 0) {
    kind = 'summary';
    body = lines.slice(summaryIdx).join('\n').replace(/^Summary:\s*/, '').trim();
  }

  return { title, url, kind, body };
}

function parseWebSearchText(text) {
  if (!text || typeof text !== 'string') return null;

  // Split blocks on "Result N:" boundaries.
  const blocks = text
    .split(/\n\n(?=Result\s+\d+:)/g)
    .map((b) => b.trim())
    .filter(Boolean);

  const parsed = [];
  for (const block of blocks) {
    if (!block.startsWith('Result ')) continue;
    parsed.push(parseResultBlock(block));
  }

  return parsed.length ? parsed : null;
}

function getDomain(url) {
  if (!url) return '';
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, '');
  } catch {
    // Fallback for non-URL strings
    return url.replace(/^https?:\/\//, '').split('/')[0].replace(/^www\./, '');
  }
}

// Only allow http(s) links. Search results come from external providers, so a
// poisoned result could carry a `javascript:`/`data:` URL — React does not block
// those in href. Returns the URL if safe to render as a link, else null.
function safeHref(url) {
  if (!url || typeof url !== 'string') return null;
  try {
    const u = new URL(url);
    return (u.protocol === 'http:' || u.protocol === 'https:') ? url : null;
  } catch {
    return null;
  }
}

function normalizeToolName(tool) {
  if (!tool) return '';
  // e.g. "web_search:duckduckgo" -> "DuckDuckGo"
  if (tool.startsWith('web_search:')) {
    const p = tool.split(':')[1] || '';
    return p ? `${p[0].toUpperCase()}${p.slice(1)}` : tool;
  }
  if (tool === 'tavily_search') return 'Tavily';
  if (tool === 'exa_search') return 'Exa';
  if (tool === 'web_search') return 'Web Search';
  return tool;
}

export default function SearchContext({ toolOutputs }) {
  const [isOpen, setIsOpen] = useState(false);

  const entries = useMemo(() => {
    const list = Array.isArray(toolOutputs) ? toolOutputs : [];
    return list
      .map((t) => ({
        tool: t.tool,
        label: normalizeToolName(t.tool),
        raw: typeof t.result === 'string' ? t.result : JSON.stringify(t.result, null, 2),
      }))
      .filter((t) => t.raw && t.raw.trim().length > 0);
  }, [toolOutputs]);

  const parsedByTool = useMemo(() => {
    return entries.map((e) => {
      // Try structured parsing first (our formatted DuckDuckGo/Brave output)
      const parsed = parseWebSearchText(e.raw);
      if (parsed) return { ...e, parsed, parsedKind: 'results' };

      // If it looks like JSON (tavily/exa), pretty render raw
      const j = safeParseJson(e.raw);
      if (j) return { ...e, parsed: j, parsedKind: 'json' };

      return { ...e, parsed: null, parsedKind: 'raw' };
    });
  }, [entries]);

  if (!entries.length) return null;

  return (
    <div className="search-context">
      <button
        type="button"
        className="search-context-toggle"
        onClick={() => setIsOpen((v) => !v)}
      >
        <span className="search-context-title">Search context</span>
        <span className="search-context-meta">
          {entries.length} source{entries.length === 1 ? '' : 's'}
        </span>
        <span className="search-context-caret">{isOpen ? '▾' : '▸'}</span>
      </button>

      {isOpen && (
        <div className="search-context-body">
          {parsedByTool.map((e, idx) => (
            <div key={`${e.tool}-${idx}`} className="search-context-block">
              <div className="search-context-block-header">
                <span className="search-context-provider">{e.label}</span>
              </div>

              {e.parsedKind === 'results' && (
                <div className="search-context-results">
                  {e.parsed.map((r, i) => {
                    const domain = getDomain(r.url);
                    const href = safeHref(r.url);
                    return (
                      <details key={i} className="search-context-result">
                        <summary className="search-context-result-summary">
                          <span className="search-context-result-title">
                            {href ? (
                              <a
                                href={href}
                                target="_blank"
                                rel="noreferrer"
                                onClick={(ev) => ev.stopPropagation()}
                              >
                                {r.title || r.url}
                              </a>
                            ) : (
                              <span>{r.title || r.url || 'Untitled result'}</span>
                            )}
                          </span>
                          {domain && <span className="search-context-result-domain">{domain}</span>}
                        </summary>
                        {r.body && (
                          <pre className="search-context-result-body">{r.body}</pre>
                        )}
                      </details>
                    );
                  })}
                </div>
              )}

              {e.parsedKind === 'json' && (
                <pre className="search-context-raw">{JSON.stringify(e.parsed, null, 2)}</pre>
              )}

              {e.parsedKind === 'raw' && (
                <pre className="search-context-raw">{e.raw}</pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

SearchContext.propTypes = {
  toolOutputs: PropTypes.arrayOf(
    PropTypes.shape({
      tool: PropTypes.string,
      result: PropTypes.oneOfType([PropTypes.string, PropTypes.object]),
    })
  ),
};
