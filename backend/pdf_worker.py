"""Disposable PDF parser. JSON-only output, finite input/pages/text/CPU/memory.

Linux enforces RLIMIT_AS. macOS/Windows rely on page/output/wall limits; no
cross-platform memory-limit guarantee is made. Invoked by absolute script path.
"""
import json
import math
import os
import sys

MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_CHARS = 50_000


def extract():
    timeout = float(os.environ.get('PDF_PARSE_TIMEOUT_SECONDS', '20'))
    if os.name != 'nt':
        import resource
        cpu = max(1, math.ceil(timeout))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        if sys.platform.startswith('linux'):
            resource.setrlimit(resource.RLIMIT_AS, (1024 ** 3, 1024 ** 3))
    import pymupdf
    import pymupdf4llm

    data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError('PDF exceeds input limit (10 MiB)')
    max_pages = int(os.environ.get('PDF_MAX_PAGES', '100'))
    if not 1 <= max_pages <= 1000:
        raise ValueError('Invalid PDF page limit configuration')
    with pymupdf.open(stream=data, filetype='pdf') as document:
        if document.needs_pass:
            raise ValueError('Password-protected PDFs are not supported')
        if document.page_count > max_pages:
            raise ValueError(f'PDF exceeds page limit ({max_pages})')
        chunks = []
        remaining = MAX_OUTPUT_CHARS
        for number in range(document.page_count):
            text = pymupdf4llm.to_markdown(document, pages=[number], show_progress=False)
            chunks.append(text[:remaining])
            remaining -= len(chunks[-1])
            if remaining == 0:
                break
        text = ''.join(chunks)
        if remaining == 0:
            marker = '\n[PDF text truncated at output limit]'
            text = text[:MAX_OUTPUT_CHARS - len(marker)] + marker
        return text


def main():
    # Native libraries may write directly to fd 1; suppress those too, preserving
    # a private output fd for our bounded JSON response only.
    output_fd = os.dup(sys.stdout.fileno())
    with open(os.devnull, 'w') as sink:
        os.dup2(sink.fileno(), sys.stdout.fileno())
        try:
            result = {'text': extract()}
        except Exception as error:
            result = {'error': f'Unable to parse PDF: {str(error)[:300]}'}
        payload = json.dumps(result, ensure_ascii=True).encode('utf-8')
        with os.fdopen(output_fd, 'wb') as output:
            output.write(payload)


if __name__ == '__main__':
    main()
