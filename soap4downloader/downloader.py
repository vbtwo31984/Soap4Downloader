import os
from pathlib import Path
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

DEFAULT_CHUNK_SIZE = 1024 * 1024


def _download_one(url, dest_path, session=None, retries=3, chunk_size=DEFAULT_CHUNK_SIZE):
    session = session or requests.Session()
    for attempt in range(retries):
        try:
            with session.get(url, stream=True, timeout=(10, 120)) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f, tqdm(total=total, unit="B", unit_scale=True, desc=dest_path.name, mininterval=0.5) as pbar:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))
            return True
        except Exception as e:
            last_exc = e
    raise last_exc

def download_files(urls, dest_paths, concurrency=3, chunk_size=DEFAULT_CHUNK_SIZE, on_success=None, on_failure=None):
    """Download `urls` to `dest_paths` concurrently.

    `on_success(index, url, dest_path)` is called as soon as a file finishes, and
    `on_failure(index, url, dest_path, error)` when one fails for good; both are
    called from the worker thread so follow-up work (such as marking an episode
    watched) happens per episode rather than after the whole batch.
    """
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {
            ex.submit(_download_one, u, p, None, 3, chunk_size): (i, u, p)
            for i, (u, p) in enumerate(zip(urls, dest_paths))
        }
        for fut in as_completed(futures):
            i, u, p = futures[fut]
            try:
                fut.result()
                results.append((u, p, True))
                if on_success is not None:
                    try:
                        on_success(i, u, p)
                    except Exception:
                        pass
            except Exception as e:
                results.append((u, p, False, str(e)))
                if on_failure is not None:
                    try:
                        on_failure(i, u, p, e)
                    except Exception:
                        pass
    return results
