"""Local document ingestion. No OCR service, downloads, or chemical inference."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re

MAX_TEXT = 1_000_000
MAX_BYTES = 20_000_000


def digest(value):
    return sha256(value.encode('utf-8') if isinstance(value, str) else value).hexdigest()


def document_from_bytes(name, data, role='main'):
    if not isinstance(name, str) or not name or len(data) > MAX_BYTES:
        raise ValueError('DOCUMENT_NAME_OR_SIZE_INVALID')
    suffix = Path(name).suffix.lower()
    warnings, pages = [], []
    if suffix == '.pdf':
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError('PDF_DEPENDENCY_MISSING_INSTALL_REQUIREMENTS_LITERATURE') from exc
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise ValueError('ENCRYPTED_PDF_UNSUPPORTED')
            if len(reader.pages) > 300:
                raise ValueError('PDF_PAGE_LIMIT')
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                pages.append({'page': number, 'text': text})
                if len(text.strip()) < 40:
                    warnings.append({'code': 'PAGE_NEEDS_OCR_OR_VISUAL_REVIEW', 'page': number})
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('PDF_READ_FAILED') from exc
        warnings.append({'code': 'PDF_TEXT_ONLY_FIGURES_TABLES_READING_ORDER_UNVERIFIED'})
    elif suffix in ('.txt', '.md', '.markdown'):
        try:
            pages = [{'page': None, 'text': data.decode('utf-8-sig')}]
        except UnicodeDecodeError as exc:
            raise ValueError('UTF8_TEXT_REQUIRED') from exc
    else:
        raise ValueError('SUPPORTED_INPUTS_PDF_MD_TXT')
    result = make_document(name, pages, role)
    result['input_sha256'] = digest(data)
    result['warnings'] = warnings
    return result


def make_document(name, pages, role='main'):
    if role not in ('main', 'supplement', 'reference'):
        raise ValueError('DOCUMENT_ROLE_INVALID')
    if not isinstance(pages, list) or not pages:
        raise ValueError('DOCUMENT_PAGES_REQUIRED')
    text, ranges = '', []
    for page in pages:
        value = page['text']
        if not isinstance(value, str):
            raise ValueError('DOCUMENT_TEXT_REQUIRED')
        start = len(text)
        text += value
        ranges.append({'page': page.get('page'), 'start': start, 'end': len(text)})
        text += '\n'  # Kept in canonical text; never normalize quotes after this.
    if len(text) > MAX_TEXT:
        raise ValueError('DOCUMENT_TEXT_LIMIT')
    doc_id = 'D-' + digest(name + '\0' + role + '\0' + text)[:20]
    return {'id': doc_id, 'name': name, 'role': role, 'text': text,
            'text_sha256': digest(text), 'input_sha256': digest(text),
            'pages': ranges, 'warnings': []}


def prepare_documents(documents, chunk_size=6000):
    """Rebuild trusted offsets; client-provided hashes/chunks are never trusted."""
    if not isinstance(documents, list) or not 1 <= len(documents) <= 20:
        raise ValueError('ONE_TO_TWENTY_DOCUMENTS_REQUIRED')
    output, chunks, seen = [], [], set()
    total = 0
    for item in documents:
        if not isinstance(item, dict) or not isinstance(item.get('text'), str):
            raise ValueError('DOCUMENT_TEXT_REQUIRED')
        name, text, role = item.get('name', 'document.txt'), item['text'], item.get('role', 'main')
        if not isinstance(name, str) or not name.strip() or len(name) > 300:
            raise ValueError('DOCUMENT_NAME_INVALID')
        if role not in ('main', 'supplement', 'reference'):
            raise ValueError('DOCUMENT_ROLE_INVALID')
        total += len(text)
        if total > MAX_TEXT:
            raise ValueError('DOCUMENT_BUNDLE_TEXT_LIMIT')
        doc_id = 'D-' + digest(name + '\0' + role + '\0' + text)[:20]
        if doc_id in seen:
            raise ValueError('DUPLICATE_DOCUMENT')
        seen.add(doc_id)
        pages = item.get('pages') or [{'page': None, 'start': 0, 'end': len(text)}]
        previous = 0
        for p in pages:
            if not (type(p.get('start')) is int and type(p.get('end')) is int
                    and previous <= p['start'] <= p['end'] <= len(text)
                    and not text[previous:p['start']].strip()
                    and (p.get('page') is None or type(p.get('page')) is int)):
                raise ValueError('DOCUMENT_PAGE_SPANS_INVALID')
            previous = p['end']
        if text[previous:].strip():
            raise ValueError('DOCUMENT_UNMAPPED_TEXT')
        doc = {'id': doc_id, 'name': name, 'role': role, 'text': text,
               'text_sha256': digest(text), 'input_sha256': item.get('input_sha256', digest(text)),
               'pages': pages, 'warnings': item.get('warnings', [])}
        from .mineru_integration import approved_metadata
        doc.update(approved_metadata(item))
        output.append(doc)
        section, in_references = '', False
        # Page boundaries and section headings remain explicit. Long blocks split,
        # but the complete canonical text is retained and each split is reported.
        for page in pages:
            page_start, page_end = page['start'], page['end']
            headings = list(re.finditer(r'(?m)^[ \t]*(?:#{1,6}[ \t]+[^\n]+|(?:References|Bibliography|参考文献)[ \t]*$)', text[page_start:page_end], re.I))
            boundaries = sorted({page_start, page_end, *(page_start+h.start() for h in headings)})
            heading_by_start = {page_start+h.start(): h[0] for h in headings}
            for start, end in zip(boundaries, boundaries[1:]):
                if start in heading_by_start:
                    section = heading_by_start[start].strip(' #\t\r\n')
                    in_references = bool(re.fullmatch(r'References|Bibliography|参考文献', section, re.I))
                while start < end:
                    stop = min(start + chunk_size, end)
                    if stop < end:
                        split = text.rfind('\n', start + chunk_size // 2, stop)
                        if split != -1:
                            stop = split + 1
                    chunks.append({'id': f'{doc_id}:C{len(chunks)+1:04d}', 'document_id': doc_id,
                                   'start': start, 'end': stop, 'page': page.get('page'),
                                   'section_hint': section, 'references_hint': in_references,
                                   'text': text[start:stop]})
                    start = stop
    if not any(d['text'].strip() for d in output):
        raise ValueError('NO_EXTRACTABLE_TEXT_OCR_REQUIRED')
    return {'documents': output, 'chunks': chunks,
            'bundle_sha256': digest('\0'.join(d['id'] for d in output))}
