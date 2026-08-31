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

def download_files(urls, dest_paths, concurrency=3, chunk_size=DEFAULT_CHUNK_SIZE):
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {ex.submit(_download_one, u, p, None, 3, chunk_size): (u, p) for u, p in zip(urls, dest_paths)}
        for fut in as_completed(futures):
            u, p = futures[fut]
            try:
                fut.result()
                results.append((u, p, True))
            except Exception as e:
                results.append((u, p, False, str(e)))
    return results
