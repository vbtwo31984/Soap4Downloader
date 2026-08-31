import click
from . import __version__
from . import session_manager
from . import parser


@click.group()
@click.version_option(__version__)
def main():
    """soap4.me downloader CLI"""
    pass


@main.command()
def login():
    """Login to soap4.me and save session cookies locally."""
    username, password = session_manager.login_interactive()
    session = session_manager.create_session()
    try:
        session = session_manager.login(username, password, session=session)
        click.echo(f"Login successful — saved session for {username}")
    except Exception as e:
        click.echo(f"Login failed: {e}")


@main.command("list-new")
def list_new():
    """List shows with new episodes (С новыми эпизодами)."""
    session = session_manager.create_session()
    shows = parser.list_shows_with_new(session)
    if not shows:
        click.echo("No shows with new episodes found.")
        return
    for i, s in enumerate(shows, start=1):
        click.echo(f"{i}. {s['title']} -> {s['url']}")


@main.command("list-seasons")
@click.argument("show_slug")
def list_seasons(show_slug):
    session = session_manager.create_session()
    shows = parser.list_seasons_with_new(session, show_slug)
    if not shows:
        click.echo("No seasons found or no new episodes detected.")
        return
    for s in shows:
        click.echo(f"Season {s['season']}: {s['title']} -> {s['url']}")


@main.command("debug-page")
@click.option("--out", default="soap4_my.html", help="File to save fetched HTML")
def debug_page(out):
    """Fetch /sort/my/ and save HTML; print badge occurrences for debugging."""
    from .config import BASE_URL
    session = session_manager.create_session()
    url = BASE_URL + "/sort/my/"
    r = session.get(url)
    r.raise_for_status()
    with open(out, "w", encoding="utf-8") as f:
        f.write(r.text)
    click.echo(f"Saved HTML to {out}")
    # find badge occurrences
    from bs4 import BeautifulSoup
    import re

    soup = BeautifulSoup(r.text, "html.parser")
    nodes = soup.find_all(string=re.compile(r"С\s+новыми\s+эпизодами", re.I))
    click.echo(f"Found {len(nodes)} badge text node(s)")
    for i, node in enumerate(nodes, start=1):
        parent = node.parent
        snippet = parent.prettify()[:400].replace('\n', ' ')
        click.echo(f"{i}. Context: {snippet}...")


@main.command("list-episodes")
@click.argument("show_slug")
@click.argument("season_num", type=int)
def list_episodes(show_slug, season_num):
    session = session_manager.create_session()
    eps = parser.list_unplayed_episodes(session, show_slug, season_num)
    if not eps:
        click.echo("No episodes found.")
        return
    for e in eps:
        subs = "yes" if e.get("has_subtitles") else "no"
        quals = ",".join(e.get("qualities") or [])
        source = e.get("download_source", "unknown")
        click.echo(f"S{season_num:02d}E{e['episode']:02d} - {e['title']} - source:{source} subs:{subs} quals:{quals} - {e['url']}")


@main.command("download")
@click.argument("show_slug")
@click.argument("season_num", type=int)
@click.option("--all", "download_all", is_flag=True, default=False, help="Download all matching episodes")
@click.option("--concurrency", default=3, help="Maximum concurrent downloads")
@click.option("--dest", default=None, help="Destination base directory")
def download(show_slug, season_num, download_all, concurrency, dest):
    """Select episodes from a show/season, filter for subtitles and download."""
    import os
    from pathlib import Path
    from . import util, downloader

    session = session_manager.create_session()
    eps = parser.list_unplayed_episodes(session, show_slug, season_num)
    if not eps:
        click.echo("No episodes found.")
        return

    # filter: must have the subtitle translation badge
    candidates = [e for e in eps if e.get("has_subtitles") and not e.get("subtitle_is_russian")]
    if not candidates:
        click.echo("No episodes found with subtitles.")
        return

    click.echo("Available episodes (with subtitles):")
    for i, e in enumerate(candidates, start=1):
        quals = ",".join(e.get("qualities") or [])
        click.echo(f"{i}. S{season_num:02d}E{e['episode']:02d} - {e['title']} quals:{quals} - {e['url']}")

    if download_all:
        selection = list(range(1, len(candidates) + 1))
    else:
        sel = input("Enter episode numbers to download (comma separated) or 'all': ")
        if sel.strip().lower() == "all":
            selection = list(range(1, len(candidates) + 1))
        else:
            parts = [s.strip() for s in sel.split(",") if s.strip()]
            selection = []
            for p in parts:
                try:
                    idx = int(p)
                    if 1 <= idx <= len(candidates):
                        selection.append(idx)
                except Exception:
                    pass

    to_download = [candidates[i - 1] for i in selection]
    if not to_download:
        click.echo("No valid selection.")
        return

    base_dir = Path(dest) if dest else Path.cwd() / "downloads"
    urls = []
    dest_paths = []
    for e in to_download:
        click.echo(f"Resolving download links for episode S{season_num:02d}E{e['episode']:02d}...")
        links = parser.resolve_episode_download_links(session, e)
        if not links:
            click.echo(f"  No direct links found for {e['title']}, skipping.")
            continue
        # pick best quality
        pref = ["4k", "1080p", "720p", "480p", ""]
        chosen = None
        for p in pref:
            for l in links:
                if p and p == l.get("quality"):
                    chosen = l
                    break
            if chosen:
                break
        if not chosen:
            chosen = links[0]

        show_title = to_download[0].get('show_title') if to_download else show_slug.replace('_', ' ')
        path = util.episode_dest_path(base_dir, show_title, season_num, e["episode"], chosen.get("ext") or ".mp4")
        path.parent.mkdir(parents=True, exist_ok=True)
        urls.append(chosen["url"])
        dest_paths.append(path)

    if not urls:
        click.echo("No downloadable files found.")
        return

    click.echo(f"Starting downloads ({len(urls)} files) with concurrency={concurrency}...")
    results = downloader.download_files(urls, dest_paths, concurrency=concurrency)
    for r in results:
        if r[2] is True:
            click.echo(f"Downloaded: {r[1]}")
        else:
            click.echo(f"Failed: {r[1]} - {r[3]}")

@main.command("tui")
def tui():
    """Run a simple terminal UI for interactive browsing and downloading."""
    from .tui import run_tui
    run_tui()
