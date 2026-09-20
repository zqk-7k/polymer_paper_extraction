from concurrent.futures import ThreadPoolExecutor
import threading
import time
from reports import render_extraction_html as renderer


def test_shared_assets_are_copied_once_during_parallel_paper_render(tmp_path, monkeypatch):
    source = tmp_path / 'source'; source.mkdir()
    for name in ('tex-svg.js', 'LICENSE', 'README.md'):
        (source / name).write_text('test shared asset', encoding='utf-8')
    monkeypatch.setattr(renderer, 'MATHJAX_SOURCE_DIR', source)
    original = renderer.shutil.copy2
    state = {'active': 0, 'max_active': 0, 'copies': 0}
    lock = threading.Lock()
    def slow_copy(src, dst):
        with lock:
            state['active'] += 1; state['copies'] += 1
            state['max_active'] = max(state['max_active'], state['active'])
        time.sleep(0.005)
        result = original(src, dst)
        with lock: state['active'] -= 1
        return result
    monkeypatch.setattr(renderer.shutil, 'copy2', slow_copy)
    def render(i):
        ref = f'paper{i}'
        return renderer._copy_mathjax_assets(tmp_path / 'output' / ref / 'report.html', document_id=ref)
    with ThreadPoolExecutor(max_workers=8) as pool:
        links = list(pool.map(render, range(16)))
    assert state['copies'] == 3 and state['max_active'] == 1
    assert len(set(links)) == 1
