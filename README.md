# soap4downloader

CLI tool to download shows from soap4.me. Early scaffold.

Install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run:

```bash
python -m soap4downloader login
python -m soap4downloader list-new
```

Each episode is marked as watched on soap4.me as soon as its download finishes.
Pass `--no-mark-watched` to `download` to skip that.
