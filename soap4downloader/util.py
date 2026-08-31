import re
import unicodedata

def sanitize_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = name.strip()
    # replace non-filesystem chars with underscore
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name


def sanitize_filename(name: str) -> str:
    safe = sanitize_name(name)
    safe = safe.replace(" ", "_")
    safe = safe.lower()
    return safe


def episode_dest_path(base_dir, show_title: str, season_num: int, episode_num: int, ext: str = ".mp4"):
    if not ext:
        ext = ".mp4"
    if not ext.startswith("."):
        ext = f".{ext}"

    safe_show = sanitize_name(show_title)
    season_dir = base_dir / safe_show / f"Season {season_num}"
    filename = f"{safe_show} - s{season_num:02d}e{episode_num:02d}{ext}"
    return season_dir / filename
