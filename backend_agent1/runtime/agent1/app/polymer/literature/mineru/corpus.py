"""Content-addressed PDF inventory and verified Markdown/images contract."""
from __future__ import annotations
import contextlib
import hashlib
import json
import os
import re
import stat
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.svg'}
MD_IMAGE = re.compile(r'!\[[^\]]*\]\(\s*(<[^>]*>|[^\s)]+)(?:\s+[^)]*)?\)')
HTML_IMAGE = re.compile(r'(<img\b[^>]*\bsrc\s*=\s*[\"\x27])([^\"\x27]+)([\"\x27])', re.I)
REF_IMAGE = re.compile(r'^([ \t]*\[[^\]]+\]:[ \t]*)(\S+)', re.M)


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def digest_json(value) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(data).hexdigest()

def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.flush()
        os.fsync(out.fileno())
    for attempt in range(12):
        try:
            os.replace(name, path)
            break
        except PermissionError:
            if attempt == 11:
                raise
            # Windows readers/virus scanners may briefly deny atomic replace.
            time.sleep(min(1.0, 0.1 * 2**attempt))


@contextlib.contextmanager
def process_lock(path: Path):
    """Kernel lock releases on crash; a stale lock file is harmless."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('Another process owns this workflow directory') from None
        yield

def inventory(source: Path) -> dict:
    from pypdf import PdfReader
    if not source.is_dir():
        raise FileNotFoundError(f'PDF directory not found: {source}')
    files = sorted((p for p in source.rglob('*') if p.is_file()), key=lambda p: str(p).casefold())
    pdfs = [p for p in files if p.suffix.lower() == '.pdf']
    if not pdfs:
        raise ValueError('No PDF files found')
    documents = {}
    for index, path in enumerate(pdfs, 1):
        checksum = sha256(path)
        doc_id = 'pdf_' + checksum[:20]
        if doc_id in documents:
            if documents[doc_id]['sha256'] != checksum:
                raise ValueError('Document hash collision')
            documents[doc_id]['source_paths'].append(str(path.resolve()))
            continue
        pages, error = None, None
        try:
            with path.open('rb') as stream:
                reader = PdfReader(stream, strict=False)
                if reader.is_encrypted and not reader.decrypt(''):
                    raise ValueError('encrypted PDF needs password')
                pages = len(reader.pages)
            if not pages or pages > 200:
                error = 'Page count outside 1..200; not silently truncated'
        except Exception as exc:
            error = f'PDF preflight: {type(exc).__name__}: {str(exc)[:200]}'
        size = path.stat().st_size
        if size > 200 * 1024 * 1024:
            error = 'PDF exceeds MinerU 200-MB limit'
        documents[doc_id] = dict(doc_id=doc_id, sha256=checksum,
            source_paths=[str(path.resolve())], bytes=size, pages=pages, preflight_error=error)
        if index % 100 == 0:
            print(f'Inventory {index}/{len(pdfs)}', flush=True)
    return dict(source_dir=str(source.resolve()), source_pdf_count=len(pdfs),
        non_pdf_files=[str(p.relative_to(source)) for p in files if p.suffix.lower() != '.pdf'],
        unique_pdf_count=len(documents), duplicate_pdf_count=len(pdfs)-len(documents),
        total_unique_pages=sum(d['pages'] or 0 for d in documents.values()),
        rejected_count=sum(bool(d['preflight_error']) for d in documents.values()), documents=documents)


def image_refs(markdown: str) -> list[str]:
    refs = [m.group(1).strip('<>') for m in MD_IMAGE.finditer(markdown)]
    refs += [m.group(2) for m in HTML_IMAGE.finditer(markdown)]
    labels = set(re.findall(r'!\[[^\]]*\]\[([^\]]+)\]', markdown))
    for line in markdown.splitlines():
        match = re.match(r'\s*\[([^\]]+)\]:\s*(\S+)', line)
        if match and match.group(1) in labels:
            refs.append(match.group(2).strip('<>'))
    return refs


def validate_document(folder: Path, doc_id: str, *, source_sha=None, options_hash=None) -> dict:
    md, proof = folder / f'{doc_id}_main.md', folder / 'provenance.json'
    if not md.is_file() or not proof.is_file() or not (folder / 'images').is_dir():
        raise ValueError('Incomplete Markdown/images/provenance contract')
    text = md.read_text(encoding='utf-8')
    if not text.strip():
        raise ValueError('Empty Markdown')
    provenance = json.loads(proof.read_text(encoding='utf-8'))
    if source_sha and provenance.get('source_sha256') != source_sha:
        raise ValueError('Source hash mismatch')
    if options_hash and provenance.get('options_hash') != options_hash:
        raise ValueError('Parser options mismatch')
    if sha256(md) != provenance.get('markdown_sha256'):
        raise ValueError('Markdown hash mismatch')
    assets = provenance.get('assets', {})
    for rel, checksum in assets.items():
        target = (folder / rel).resolve()
        if not target.is_relative_to(folder.resolve()) or not target.is_file() or sha256(target) != checksum:
            raise ValueError(f'Missing/changed image asset: {rel}')
    for ref in image_refs(text):
        parsed = urlsplit(unquote(ref))
        rel = parsed.path.replace('\\', '/')
        if parsed.scheme or parsed.netloc or rel not in assets:
            raise ValueError(f'Image is not a verified local asset: {ref[:120]}')
    return dict(markdown_path=str(md.resolve()), image_count=len(assets),
        image_reference_count=len(image_refs(text)), markdown_sha256=sha256(md))


def normalize_archive(archive_path: Path, output_root: Path, document: dict,
                      options_hash: str, batch_id: str) -> dict:
    """Only normalized Markdown/images enter the corpus; provenance commits last."""
    doc_id = document['doc_id']
    destination = output_root / doc_id
    (destination / 'images').mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > 20000 or sum(m.file_size for m in members) > 2 * 1024**3:
            raise ValueError('Archive exceeds safe extraction limits')
        names = {}
        for member in members:
            name = member.filename.replace('\\', '/')
            path = PurePosixPath(name)
            mode = member.external_attr >> 16
            if path.is_absolute() or '..' in path.parts or ':' in name or stat.S_ISLNK(mode):
                raise ValueError('Unsafe ZIP member path')
            if name in names:
                raise ValueError('Duplicate ZIP member')
            names[name] = member
        mds = [n for n in names if n.lower().endswith('.md')]
        preferred = [n for n in mds if PurePosixPath(n).name == 'full.md']
        if len(preferred) == 1:
            md_name = preferred[0]
        elif len(mds) == 1:
            md_name = mds[0]
        else:
            raise ValueError('Missing or ambiguous primary Markdown')
        text = archive.read(names[md_name]).decode('utf-8-sig')
        if not text.strip():
            raise ValueError('MinerU returned empty Markdown')
        image_map, assets = {}, {}
        for name, member in names.items():
            suffix = PurePosixPath(name).suffix.lower()
            if member.is_dir() or suffix not in IMAGE_SUFFIXES:
                continue
            content = archive.read(member)
            if not content:
                raise ValueError('MinerU returned an empty image')
            checksum = hashlib.sha256(content).hexdigest()
            rel = f'images/img_{checksum[:24]}{suffix}'
            (destination / rel).write_bytes(content)
            image_map[name], assets[rel] = rel, checksum
        def resolve(ref: str) -> str:
            parsed = urlsplit(unquote(ref.strip('<>')))
            if parsed.scheme or parsed.netloc:
                raise ValueError('Unexpected remote image in MinerU Markdown')
            clean = parsed.path.replace('\\', '/')
            normalized = str(PurePosixPath(PurePosixPath(md_name).parent, clean))
            candidate = normalized if normalized in image_map else clean.removeprefix('./')
            if candidate not in image_map:
                matches = [v for k, v in image_map.items() if PurePosixPath(k).name == PurePosixPath(clean).name]
                if len(set(matches)) != 1:
                    raise ValueError(f'Missing/ambiguous image: {clean[:120]}')
                return matches[0]
            return image_map[candidate]
        text = MD_IMAGE.sub(lambda m: m.group(0)[:m.start(1)-m.start()] + resolve(m.group(1)) + m.group(0)[m.end(1)-m.start():], text)
        text = HTML_IMAGE.sub(lambda m: m.group(1) + resolve(m.group(2)) + m.group(3), text)
        labels = set(re.findall(r'!\[[^\]]*\]\[([^\]]+)\]', text))
        def rewrite_ref(m):
            label = re.search(r'\[([^\]]+)\]', m.group(1)).group(1)
            return m.group(1) + resolve(m.group(2)) if label in labels else m.group(0)
        text = REF_IMAGE.sub(rewrite_ref, text)
        md_path = destination / f'{doc_id}_main.md'
        md_path.write_text(text, encoding='utf-8', newline='\n')
        atomic_json(destination / 'provenance.json', dict(schema_version='mineru_input_v1',
            doc_id=doc_id, source_sha256=document['sha256'], source_paths=document['source_paths'],
            source_pages=document.get('pages'), batch_id=batch_id, options_hash=options_hash,
            markdown_sha256=sha256(md_path), assets=assets, original_markdown=md_name,
            archive_sha256=sha256(archive_path)))
    return validate_document(destination, doc_id, source_sha=document['sha256'], options_hash=options_hash)
