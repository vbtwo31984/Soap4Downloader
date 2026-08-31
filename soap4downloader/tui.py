from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from . import session_manager, parser, downloader, util
from pathlib import Path


def _message(title, text):
    print(f"\n{title}: {text}")


def _confirm(text):
    answer = input(f"{text} [y/N] ").strip().lower()
    return answer in ("y", "yes")


def _selector(title, values, *, multiple=False, page_size=18):
    if not values:
        return [] if multiple else None

    selected_index = 0
    selected_values = set()
    keys = [value for value, _ in values]
    bindings = KeyBindings()

    def move(delta):
        nonlocal selected_index
        selected_index = min(len(values) - 1, max(0, selected_index + delta))

    def render():
        half_page = page_size // 2
        start = max(0, min(selected_index - half_page, len(values) - page_size))
        end = min(len(values), start + page_size)
        fragments = [
            ("class:title", f"{title}\n"),
            ("", "Up/down or j/k to move. "),
        ]
        if multiple:
            fragments.append(("", "Space toggles, a selects/clears all, Enter continues, q cancels.\n\n"))
        else:
            fragments.append(("", "Enter selects, q cancels.\n\n"))

        for idx in range(start, end):
            value, label = values[idx]
            cursor = ">" if idx == selected_index else " "
            if multiple:
                marker = "[x]" if value in selected_values else "[ ]"
                line = f"{cursor} {marker} {label}\n"
            else:
                line = f"{cursor} {label}\n"
            style = "reverse" if idx == selected_index else ""
            fragments.append((style, line))

        if len(values) > page_size:
            fragments.append(("", f"\nShowing {start + 1}-{end} of {len(values)}"))
        return fragments

    @bindings.add("up")
    @bindings.add("k")
    def _up(event):
        move(-1)

    @bindings.add("down")
    @bindings.add("j")
    def _down(event):
        move(1)

    @bindings.add("pageup")
    def _pageup(event):
        move(-page_size)

    @bindings.add("pagedown")
    def _pagedown(event):
        move(page_size)

    @bindings.add("home")
    def _home(event):
        nonlocal selected_index
        selected_index = 0

    @bindings.add("end")
    def _end(event):
        nonlocal selected_index
        selected_index = len(values) - 1

    @bindings.add(" ")
    def _space(event):
        if not multiple:
            return
        value = values[selected_index][0]
        if value in selected_values:
            selected_values.remove(value)
        else:
            selected_values.add(value)

    @bindings.add("a")
    def _toggle_all(event):
        if not multiple:
            return
        if len(selected_values) == len(keys):
            selected_values.clear()
        else:
            selected_values.update(keys)

    @bindings.add("enter")
    def _enter(event):
        if multiple:
            get_app().exit(result=[value for value in keys if value in selected_values])
        else:
            get_app().exit(result=values[selected_index][0])

    @bindings.add("q")
    @bindings.add("escape")
    @bindings.add("c-c")
    def _cancel(event):
        get_app().exit(result=[] if multiple else None)

    control = FormattedTextControl(render, focusable=True)
    app = Application(
        layout=Layout(Window(content=control, dont_extend_height=True)),
        key_bindings=bindings,
        full_screen=False,
        erase_when_done=True,
    )
    return app.run()


def run_tui():
    session = session_manager.create_session()
    # login if needed
    if not session_manager.is_logged_in(session):
        do_login = _confirm("You are not logged in. Login now?")
        if not do_login:
            _message("Abort", "Login required to proceed.")
            return
        username, password = session_manager.login_interactive()
        try:
            session = session_manager.login(username, password, session=session)
            _message("Success", f"Logged in as {username}")
        except Exception as e:
            _message("Login failed", str(e))
            return

    # list shows with new episodes
    shows = parser.list_shows_with_new(session)
    if not shows:
        _message("No shows", "No shows with new episodes found.")
        return

    choices = [(s['slug'], f"{s['title']}") for s in shows]
    sel = _selector("Shows with new episodes", choices)
    if not sel:
        return
    show_slug = sel

    # seasons
    seasons = parser.list_seasons_with_new(session, show_slug)
    if not seasons:
        _message("No seasons", "No seasons with new episodes found.")
        return
    season_choices = [(s['season'], f"Season {s['season']}: {s.get('title')}") for s in seasons]
    ssel = _selector("Seasons with new episodes", season_choices)
    if ssel is None:
        return
    season_num = int(ssel)

    # episodes
    eps = parser.list_unplayed_episodes(session, show_slug, season_num)
    if not eps:
        _message("No episodes", "No unplayed episodes found.")
        return

    # filter episodes: must have the subtitle translation badge
    candidates = [e for e in eps if e.get('has_subtitles') and not e.get('subtitle_is_russian')]
    if not candidates:
        _message("No subtitles", "No unplayed episodes with subtitles found.")
        return

    ep_values = [
        (
            i,
            f"S{season_num:02d}E{e['episode']:02d} {e['title']} [{e.get('download_source','unknown')}]",
        )
        for i, e in enumerate(candidates)
    ]
    sel_eps = _selector("Episodes to download", ep_values, multiple=True)
    if not sel_eps:
        _message("No selection", "No episodes selected.")
        return

    to_download = [candidates[i] for i in sel_eps]

    # destination
    base_dir = Path.cwd() / "downloads"
    print(f"\nDestination: {base_dir}")

    # resolve links and download
    urls = []
    dest_paths = []
    for e in to_download:
        links = parser.resolve_episode_download_links(session, e)
        if not links:
            _message("No links", f"No direct links found for {e['title']}")
            continue
        # pick best quality
        pref = ["4k", "1080p", "720p", "480p", ""]
        chosen = None
        for p in pref:
            for l in links:
                if p and p == l.get('quality'):
                    chosen = l
                    break
            if chosen:
                break
        if not chosen:
            chosen = links[0]

        show_title = next((s['title'] for s in shows if s['slug'] == show_slug), show_slug.replace('_', ' '))
        path = util.episode_dest_path(base_dir, show_title, season_num, e['episode'], chosen.get('ext') or '.mp4')
        path.parent.mkdir(parents=True, exist_ok=True)
        urls.append(chosen['url'])
        dest_paths.append(path)

    if not urls:
        _message("Nothing to download", "No files to download.")
        return

    concurrency = _selector(
        "Download concurrency",
        [
            (3, "3 - balanced"),
            (5, "5 - faster"),
            (1, "1 - most stable"),
            (8, "8 - aggressive"),
        ],
    )
    if concurrency is None:
        return

    print(f"\nStarting {len(urls)} downloads (concurrency={concurrency}).")
    downloader.download_files(urls, dest_paths, concurrency=concurrency)
    _message("Done", "Downloads finished.")
