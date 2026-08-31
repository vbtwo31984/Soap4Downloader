import hashlib
import re
from pathlib import Path
from typing import List, Dict
from urllib.parse import urljoin
from .config import BASE_URL

import requests
from bs4 import BeautifulSoup

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}


def _browser_headers() -> Dict[str, str]:
    return dict(BROWSER_HEADERS)


def _show_title_from_link(link):
    title_tag = link.find(class_=re.compile(r"\bname\b", re.I))
    if title_tag:
        title = title_tag.get_text(" ", strip=True)
        if title:
            return title

    image = link.find("img")
    if image:
        title = image.get("title") or image.get("alt")
        if title:
            return title.strip()

    badge = link.find("span", class_=re.compile(r"new-badge", re.I))
    if badge is not None:
        badge.extract()
    return link.get_text(" ", strip=True)


def list_shows_with_new(session: requests.Session = None) -> List[Dict]:
    """Return list of shows that have 'С новыми эпизодами' badge.

    Each item: {"title": str, "url": str, "slug": str}
    """
    if session is None:
        session = requests.Session()
    url = BASE_URL + "/sort/my/"
    r = session.get(url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    shows = []

    # Strategy: find all text nodes containing the badge text, then locate the nearest ancestor
    # link pointing to /soap/<slug>/ and extract title and url.
    badge_nodes = soup.find_all(string=re.compile(r"С\s+новыми\s+эпизодами", re.I))
    for node in badge_nodes:
        # find a reasonable container (ancestor) that holds the list of shows for this badge
        container = None
        ancestor = node.parent
        for _ in range(6):
            if ancestor is None or ancestor == soup:
                break
            if ancestor.find("a", href=re.compile(r"^/soap/")):
                container = ancestor
                break
            ancestor = ancestor.parent
        if container is None:
            # fallback: use node's next siblings or the whole document
            container = node.parent
        # find all show links inside the container (or its next siblings)
        anchors = container.find_all("a", href=re.compile(r"^/soap/"))
        if not anchors:
            # try scanning following siblings
            sib = container.next_sibling
            while sib:
                if hasattr(sib, "find_all"):
                    anchors = sib.find_all("a", href=re.compile(r"^/soap/"))
                    if anchors:
                        break
                sib = sib.next_sibling
        for found in anchors:
            href = found.get("href")
            if not href:
                continue
            # Find a local item container for this show link (climb up a few levels)
            item = found
            container = None
            for _ in range(6):
                if not item or item == soup:
                    break
                if item.name in ("li", "div", "article"):
                    container = item
                    break
                item = item.parent
            if container is None:
                container = found.parent

            # Within this container, require a non-empty new-badge marker
            if not _has_nonempty_new_badge(container):
                continue

            title = _show_title_from_link(found)
            full_url = BASE_URL + href if href.startswith("/") else href
            parts = href.strip("/\n\r\t").split("/")
            slug = parts[1] if len(parts) > 1 else parts[0]
            shows.append({"title": title, "url": full_url, "slug": slug})

    # dedupe by slug
    seen = set()
    out = []
    for s in shows:
        if s["slug"] in seen:
            continue
        seen.add(s["slug"])
        out.append(s)
    return out
    return shows


def _has_nonempty_new_badge(element):
    badge = element.find("span", class_=re.compile(r"new-badge", re.I))
    if not badge:
        return False
    if badge.get_text(strip=True):
        return True
    # if badge has nested elements, treat it as non-empty
    return len(badge.find_all()) > 0


def list_seasons_with_new(session: requests.Session, show_slug: str) -> List[Dict]:
    """List seasons for a show that have new episodes.

    Returns list of {"season": int, "url": str, "title": str}
    """
    url = f"{BASE_URL}/soap/{show_slug}/"
    r = session.get(url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    seasons = []
    # look for links to season pages: /soap/<slug>/<number>/
    for a in soup.find_all("a", href=re.compile(rf"^/soap/{re.escape(show_slug)}/\d+/")):
        href = a.get("href")
        if not href:
            continue

        container = a
        for _ in range(6):
            if container is None:
                break
            if container.name in ("li", "div", "article") and container.get("class") and any(cls in ("poster-item", "season-item", "season-card") for cls in container.get("class")):
                break
            container = container.parent

        if container is None:
            container = a.parent

        # Only include seasons that have an explicit non-empty new-episode badge
        if not _has_nonempty_new_badge(container):
            continue

        full = BASE_URL + href if href.startswith("/") else href
        m = re.search(rf"/soap/{re.escape(show_slug)}/(\d+)/", href)
        season_num = int(m.group(1)) if m else None
        # prefer a cleaner season number label if available
        title_tag = a.find(class_=re.compile(r"season-number|season-title", re.I))
        title = title_tag.get_text(strip=True) if title_tag else a.get_text(strip=True)
        seasons.append({"season": season_num, "url": full, "title": title})
    # dedupe by season number
    seen = set()
    out = []
    for s in seasons:
        if s["season"] in seen:
            continue
        seen.add(s["season"])
        out.append(s)
    return out


def _quality_label(quality_value):
    if quality_value is None:
        return ""
    quality_value = str(quality_value).strip().lower()
    if quality_value in ("4", "4k", "uhd"):
        return "4k"
    if quality_value in ("3", "fullhd", "1080", "1080p", "full hd"):
        return "1080p"
    if quality_value in ("2", "hd", "720", "720p"):
        return "720p"
    if quality_value in ("1", "sd", "480", "480p"):
        return "480p"
    return quality_value


def _quality_number_from_classes(classes):
    for class_name in classes or []:
        match = re.fullmatch(r"quality-(\d+)", str(class_name).strip())
        if match:
            return match.group(1)
    return ""


def _quality_rank(quality_value):
    return {"4k": 4, "1080p": 3, "720p": 2, "480p": 1}.get(_quality_label(quality_value).lower(), 0)


def _translate_is_subtitles(translate_value, translate_badge=None):
    classes = translate_badge.get("class", []) if translate_badge is not None else []
    if "translate-sub" in classes:
        return True

    value = str(translate_value or "").strip().lower()
    return value in ("sub", "subs", "subtitle", "subtitles", "субтитры")


def _episode_better(new, old):
    def rank(entry):
        return (
            1 if entry.get("has_subtitles") else 0,
            1 if not entry.get("subtitle_is_russian") else 0,
            1 if entry.get("supports_stream_api") else 0,
            _quality_rank(entry.get("quality", "")),
        )
    return rank(new) > rank(old)


def _get_token_from_page(session: requests.Session, url: str) -> str:
    r = session.get(url, headers=_browser_headers())
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    token_tag = soup.find(id="token")
    if token_tag:
        token = token_tag.get("data:token") or token_tag.get("data-token") or token_tag.get("data_token")
        if token:
            return token

    token_meta = soup.find("meta", attrs={"name": "token"}) or soup.find("meta", attrs={"name": "x-api-token"})
    if token_meta:
        token = token_meta.get("content")
        if token:
            return token

    for cookie_name in ("x-api-token", "token", "api-token"):
        token = session.cookies.get(cookie_name)
        if token:
            return token

    return ""


def _resolve_api_play_links(session: requests.Session, play_eid: str, play_sid: str, play_hash: str, page_url: str = None) -> List[Dict]:
    token = _get_token_from_page(session, page_url or BASE_URL)
    if not token:
        return []
    validation_hash = hashlib.md5(f"{token}{play_eid}{play_sid}{play_hash}".encode("utf-8")).hexdigest()
    payload = {"eid": str(play_eid), "hash": validation_hash}
    headers = {
        "User-Agent": BROWSER_HEADERS["User-Agent"],
        "Accept-Language": BROWSER_HEADERS["Accept-Language"],
        "x-api-token": token,
        "x-user-agent": "browser: public v0.1",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": BASE_URL,
    }
    if page_url:
        headers["Referer"] = page_url
    api_url = urljoin(BASE_URL, f"/api/v2/play/episode/{play_eid}")
    r = session.post(api_url, headers=headers, data=payload)
    if r.status_code != 200:
        return []
    data = r.json()
    if not data.get("ok"):
        return []
    stream_url = data.get("stream")
    if not stream_url:
        return []
    if stream_url.startswith("/"):
        stream_url = urljoin(BASE_URL, stream_url)
    path = stream_url.split("?", 1)[0]
    if path.endswith("/"):
        ext = ".mp4"
    elif ".m3u8" in path.lower():
        ext = ".m3u8"
    else:
        ext = Path(path).suffix or ".mp4"
    return [{"url": stream_url, "quality": "", "ext": ext}]


def list_unplayed_episodes(session: requests.Session, show_slug: str, season_num: int) -> List[Dict]:
    """List unplayed episodes for a given show/season using episode card metadata.

    Returns list of {"episode": int, "title": str, "url": str, "download_url": str, "has_subtitles": bool, "subtitle_is_russian": bool, "qualities": [str], "quality": str, "play_eid": str}
    """
    url = f"{BASE_URL}/soap/{show_slug}/{season_num}/"
    r = session.get(url, headers=_browser_headers())
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    show_title = None
    h1 = soup.find("h1")
    if h1:
        show_title = h1.get_text(strip=True)
    if not show_title:
        title_tag = soup.find("title")
        if title_tag:
            show_title = title_tag.get_text(strip=True).split("|")[0].strip()
    if show_title:
        show_title = re.sub(r"\s*\([^)]*\)\s*$", "", show_title).strip()
    if not show_title:
        show_title = show_slug.replace("_", " ")

    episodes = []
    for card in soup.find_all("div", class_=re.compile(r"episode-card", re.I)):
        ep_num = None
        ep_attr = card.get("data:episode")
        if ep_attr and ep_attr.isdigit():
            ep_num = int(ep_attr)
        else:
            num_tag = card.find("div", class_=re.compile(r"episode-number", re.I))
            if num_tag:
                text = num_tag.get_text(strip=True)
                if text.isdigit():
                    ep_num = int(text)
        if ep_num is None:
            continue

        watched_div = card.select_one(".episode-watched div")
        is_watched = False
        if watched_div is not None:
            data_watched = watched_div.get("data:watched")
            if data_watched is not None:
                is_watched = str(data_watched).strip() in ("1", "true", "yes")
            else:
                is_watched = "yes" in (watched_div.get("class") or [])
        if is_watched:
            continue

        title_tag = card.find(class_=re.compile(r"episode-title(-en)?", re.I))
        title = title_tag.get_text(strip=True) if title_tag else f"Episode {ep_num}"

        quality_value = card.get("data:quality")
        quality_text = _quality_label(quality_value)
        quality_badge = card.find("span", class_=re.compile(r"quality-badge", re.I))
        if quality_badge:
            badge_quality = _quality_number_from_classes(quality_badge.get("class", []))
            quality_text = _quality_label(badge_quality or quality_badge.get_text(strip=True))
        qualities = [quality_text] if quality_text else []

        translate_value = card.get("data:translate") or ""
        translate_badge = card.find("span", class_=re.compile(r"translate-badge", re.I))
        if translate_badge:
            translate_value = translate_badge.get_text(strip=True)
        has_subtitles = _translate_is_subtitles(translate_value, translate_badge)
        subtitle_is_russian = bool(re.search(r"рус|rus|russian", translate_value, re.I))

        download_tag = card.find("a", class_=re.compile(r"episode-download", re.I))
        download_url = None
        if download_tag is not None and download_tag.get("href"):
            download_url = download_tag["href"]
            if download_url.startswith("/"):
                download_url = urljoin(BASE_URL, download_url)

        play_tag = card.find("div", class_=re.compile(r"theme-play", re.I))
        play_eid = play_tag.get("data:eid") if play_tag is not None else None
        play_sid = play_tag.get("data:sid") if play_tag is not None else None
        play_hash = play_tag.get("data:hash") if play_tag is not None else None
        play_episode = play_tag.get("data:episode") if play_tag is not None else None

        supports_stream_api = bool(play_eid and play_sid and play_hash)
        download_source = "stream-api" if supports_stream_api else ("torrent" if download_url else "unknown")

        episode_url = url

        episodes.append({
            "episode": ep_num,
            "title": title,
            "url": episode_url,
            "page_url": url,
            "download_url": download_url,
            "has_subtitles": has_subtitles,
            "subtitle_is_russian": subtitle_is_russian,
            "qualities": qualities,
            "quality": quality_text,
            "play_eid": play_eid,
            "play_sid": play_sid,
            "play_hash": play_hash,
            "play_episode": play_episode,
            "supports_stream_api": supports_stream_api,
            "download_source": download_source,
            "show_title": show_title,
        })

    best_by_episode = {}
    for item in episodes:
        existing = best_by_episode.get(item["episode"])
        if existing is None or _episode_better(item, existing):
            best_by_episode[item["episode"]] = item

    episodes = [best_by_episode[ep] for ep in sorted(best_by_episode.keys())]
    return episodes


def resolve_episode_download_links(session: requests.Session, episode_source) -> List[Dict]:
    """Try to resolve direct download links from an episode page or episode metadata object.

    Returns list of {"url": str, "quality": str, "ext": str}
    """
    if isinstance(episode_source, dict):
        item = episode_source
        if item.get("play_eid") and item.get("play_sid") and item.get("play_hash"):
            links = _resolve_api_play_links(session, item["play_eid"], item["play_sid"], item.get("play_hash", ""), item.get("page_url"))
            if links:
                return links

        if item.get("download_url"):
            url = item["download_url"]
            if url.lower().endswith(".torrent"):
                return []
            ext = Path(url.split("?")[0]).suffix or ".bin"
            return [{"url": url, "quality": item.get("quality", ""), "ext": ext}]

        episode_page_url = item.get("page_url") or item.get("url")
    else:
        episode_page_url = episode_source

    if isinstance(episode_page_url, str) and episode_page_url.lower().endswith(".torrent"):
        return []

    if not episode_page_url:
        return []

    r = session.get(episode_page_url, headers=_browser_headers())
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    links = []

    for video in soup.find_all("video"):
        for src in video.find_all("source"):
            href = src.get("src") or src.get("data-src")
            if not href:
                continue
            ext = href.split("?")[0].split(".")[-1]
            q = ""
            if "2160" in href or "4k" in href.lower():
                q = "4k"
            elif "1080" in href or "1080p" in href.lower():
                q = "1080p"
            links.append({"url": urljoin(BASE_URL, href) if href.startswith("/") else href, "quality": q, "ext": f".{ext}"})

    for a in soup.find_all("a", href=True):
        href = a.get("href")
        if not href:
            continue
        if any(href.lower().endswith(ext) for ext in (".mp4", ".m4v", ".mkv", ".avi", ".mov")) or "download" in a.get_text(strip=True).lower() or "download" in href.lower():
            full_href = urljoin(BASE_URL, href) if href.startswith("/") else href
            ext = full_href.split("?")[0].split(".")[-1]
            q = ""
            text = a.get_text(" ", strip=True).lower()
            if "4k" in text or "2160" in text:
                q = "4k"
            elif "1080" in text or "full hd" in text or "1080p" in text:
                q = "1080p"
            links.append({"url": full_href, "quality": q, "ext": f".{ext}"})

    seen = set()
    out = []
    for l in links:
        if l["url"] in seen:
            continue
        seen.add(l["url"])
        out.append(l)
    return out
