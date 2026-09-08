"""Bounded Tavily requests and explicit separation of search evidence from failures."""
import json
import logging
import re
import httpx

logger = logging.getLogger(__name__)
MAX_QUERY_CHARS = 1200  # Below Tavily's documented <1500-character recommendation.


def bounded_query(query):
    """Last-resort bound after semantic optimization; keep complete words."""
    text = ' '.join(str(query or '').split()).strip('"\'')
    if len(text) <= MAX_QUERY_CHARS:
        return text
    return text[:MAX_QUERY_CHARS].rsplit(' ', 1)[0] or text[:MAX_QUERY_CHARS]


def tavily_search(query, api_key):
    query = bounded_query(query)
    if not query:
        return {'status': 'error', 'error': {'code': 'empty_query', 'message': 'Search query is empty.'}}
    try:
        response = httpx.post(
            'https://api.tavily.com/search',
            headers={'Authorization': f'Bearer {api_key}'},
            json={'query': query, 'max_results': 3, 'search_depth': 'advanced', 'include_answer': False},
            timeout=httpx.Timeout(30, connect=5),
        )
        try:
            data = response.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        request_id = str(data.get('request_id') or response.headers.get('x-request-id') or '')
        request_id = request_id if re.fullmatch(r'[\w-]{1,128}', request_id) else ''
        if response.is_error:
            detail = data.get('detail') or data.get('error') or 'Search provider rejected the request.'
            if isinstance(detail, dict):
                detail = detail.get('error') or detail.get('message') or 'Search provider rejected the request.'
            # No request headers/body or unsanitized exception text enter logs or model context.
            message = str(detail).replace(api_key, '[redacted]').replace(query, '[query]')
            message = re.sub(r'tvly-[\w-]+', '[redacted]', message)[:300]
            logger.warning('Tavily failed status=%s request_id=%s query_chars=%d', response.status_code, request_id, len(query))
            return {'status': 'error', 'request_id': request_id, 'error': {
                'code': 'http_error', 'status_code': response.status_code, 'message': message}}
        rows = data.get('results')
        if not isinstance(rows, list):
            return {'status': 'error', 'error': {'code': 'invalid_response', 'message': 'Invalid search response.'}}
        results = [
            {key: str(row.get(key) or '')[:6000] for key in ('title', 'url', 'content')}
            for row in rows[:3] if isinstance(row, dict) and str(row.get('url', '')).startswith(('https://', 'http://'))
        ]
        logger.info('Tavily completed results=%d request_id=%s query_chars=%d', len(results), request_id, len(query))
        return {'status': 'success' if results else 'empty', 'results': results, 'request_id': request_id}
    except httpx.TimeoutException:
        return {'status': 'error', 'error': {'code': 'timeout', 'message': 'Search timed out.'}}
    except httpx.RequestError:
        return {'status': 'error', 'error': {'code': 'network_error', 'message': 'Search provider could not be reached.'}}


def search_failed(item):
    if item.get('status') == 'error':
        return True
    raw = item.get('result', '')
    # Legacy LangChain errors were JSON-encoded repr(exception), sometimes twice.
    for _ in range(2):
        if not isinstance(raw, str):
            break
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            break
        raw = parsed
    return isinstance(raw, str) and (
        bool(re.match(r'^\s*(?:HTTPError|ReadTimeout|ConnectTimeout|ConnectionError|TimeoutError)\(', raw))
        or raw.startswith('[System Note: Web search failed.')
    )


def search_output(tool, output):
    """Normalize new Tavily envelopes while preserving other tool contracts."""
    if isinstance(output, dict) and output.get('status') in {'error', 'success', 'empty'}:
        status = output['status']
        result = ''
        if status == 'success':
            result = '\n\n'.join(
                f"Result {i}:\nTitle: {row['title']}\nURL: {row['url']}\nSummary: {row['content']}"
                for i, row in enumerate(output.get('results', []), 1)
            )
        return {'tool': tool, 'status': status, 'result': result,
                'request_id': output.get('request_id', ''), 'error': output.get('error')}
    item = {'tool': tool, 'result': json.dumps(output, ensure_ascii=False, default=str)[:24000]}
    if search_failed(item):
        return {'tool': tool, 'status': 'error', 'result': '',
                'error': {'code': 'provider_error', 'message': 'Search provider failed.'}}
    return item


def tool_context(outputs):
    """Only actual evidence goes under Search Results; diagnostics stay separate."""
    evidence = [item for item in outputs if not search_failed(item) and item.get('status') != 'empty' and item.get('result')]
    notes = []
    if any(search_failed(item) for item in outputs):
        notes.append('Search unavailable: a search request failed. Do not claim that this search verified current facts.')
    if any(item.get('status') == 'empty' for item in outputs):
        notes.append('Search returned no sources. Do not claim search verification.')
    if evidence:
        notes.append('Search Results (external source material):\n' + '\n'.join(
            f"- {item.get('tool')}: {item.get('result')}" for item in evidence))
    return '\n\n'.join(notes)
