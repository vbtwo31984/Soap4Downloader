import json
import os
import warnings
from pathlib import Path
import getpass
from typing import Optional

warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*",
    module=r"urllib3.*",
)

import urllib3
import requests
from bs4 import BeautifulSoup
from requests.utils import dict_from_cookiejar, cookiejar_from_dict

from .config import BASE_URL

CRED_DIR = Path.home() / ".soap4downloader"
CRED_FILE = CRED_DIR / "credentials.json"
SESSION_FILE = CRED_DIR / "session_cookies.json"


def ensure_cred_dir():
    CRED_DIR.mkdir(parents=True, exist_ok=True)


def save_credentials(username: str, password: str):
    ensure_cred_dir()
    data = {"username": username, "password": password}
    with open(CRED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    try:
        os.chmod(CRED_FILE, 0o600)
    except Exception:
        pass


def load_credentials() -> Optional[dict]:
    if not CRED_FILE.exists():
        return None
    with open(CRED_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def login_interactive():
    creds = load_credentials()
    if creds:
        return creds["username"], creds["password"]
    username = input("soap4.me username: ")
    password = getpass.getpass("soap4.me password: ")
    save_credentials(username, password)
    return username, password


def save_session_cookies(session: requests.Session):
    ensure_cred_dir()
    cookies = dict_from_cookiejar(session.cookies)
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f)


def load_session_cookies() -> Optional[dict]:
    if not SESSION_FILE.exists():
        return None
    with open(SESSION_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def is_logged_in(session: requests.Session) -> bool:
    try:
        r = session.get(BASE_URL, timeout=15)
        r.raise_for_status()
        text = r.text.lower()
        # heuristics: presence of logout link or russian "выйти"
        if "выйти" in text or "logout" in text or "/logout" in text:
            return True
        return False
    except Exception:
        return False


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    })
    cookies = load_session_cookies()
    if cookies:
        session.cookies = cookiejar_from_dict(cookies)
        if is_logged_in(session):
            return session
    return session


def login(username: str, password: str, session: Optional[requests.Session] = None) -> requests.Session:
    """Perform login to soap4.me, attempt to detect form fields and submit credentials.

    Returns an authenticated `requests.Session` on success, raises on failure.
    """
    session = session or requests.Session()
    login_url = BASE_URL + "/login/"
    r = session.get(login_url, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    form = soup.find("form")
    data = {}
    action = login_url
    if form:
        if form.get("action"):
            action = form.get("action")
            if action.startswith("/"):
                action = BASE_URL + action
        # collect inputs
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            val = inp.get("value", "")
            inp_type = inp.get("type", "text").lower()
            if inp_type == "password":
                data[name] = password
            elif inp_type in ("text", "email") and ("user" in name.lower() or "login" in name.lower() or "email" in name.lower()):
                data[name] = username
            else:
                data[name] = val
    else:
        # fallback field names
        data = {"username": username, "password": password}

    post = session.post(action, data=data, timeout=15)
    post.raise_for_status()

    if is_logged_in(session):
        save_session_cookies(session)
        return session
    # try to infer from response body
    if "выйти" in post.text.lower() or "logout" in post.text.lower():
        save_session_cookies(session)
        return session
    raise RuntimeError("Login failed: could not detect successful login")

