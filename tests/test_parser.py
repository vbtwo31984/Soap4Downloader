import unittest

from soap4downloader import parser


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, text):
        self.text = text

    def get(self, url, headers=None):
        return FakeResponse(self.text)


class ParserEpisodeSelectionTest(unittest.TestCase):
    def test_show_titles_do_not_include_new_badge_count(self):
        html = """
        <html>
          <body>
            <h2>С новыми эпизодами</h2>
            <ul>
              <li class="poster-item">
                <a href="/soap/Silo/">
                  <div class="poster-wrapper">
                    <img title="Silo" alt="Silo">
                    <span class="new-badge"><div class="inner">20</div></span>
                  </div>
                  <span class="name">Silo</span>
                </a>
              </li>
            </ul>
          </body>
        </html>
        """

        shows = parser.list_shows_with_new(FakeSession(html))

        self.assertEqual(shows, [{"title": "Silo", "url": "https://soap4.me/soap/Silo/", "slug": "Silo"}])

    def test_prefers_subtitle_episode_with_highest_quality_class(self):
        html = """
        <html>
          <body>
            <h1>Example Show</h1>
            <div class="episode-card" data:episode="1">
              <div class="episode-title">Pilot</div>
              <span class="quality-badge quality-2">HD</span>
              <span class="translate-badge translate-sub"> Субтитры</span>
              <div class="theme-play" data:eid="101" data:sid="1" data:hash="abc" data:episode="1"></div>
            </div>
            <div class="episode-card" data:episode="1">
              <div class="episode-title">Pilot</div>
              <span class="quality-badge quality-4">HD</span>
              <span class="translate-badge translate-sub"> Субтитры</span>
              <div class="theme-play" data:eid="102" data:sid="1" data:hash="abc" data:episode="1"></div>
            </div>
            <div class="episode-card" data:episode="2">
              <div class="episode-title">Dubbed</div>
              <span class="quality-badge quality-4">HD</span>
              <span class="translate-badge translate-voice">Озвучка</span>
              <div class="theme-play" data:eid="201" data:sid="1" data:hash="abc" data:episode="2"></div>
            </div>
            <div class="episode-card" data:episode="2">
              <div class="episode-title">Subtitled</div>
              <span class="quality-badge quality-2">HD</span>
              <span class="translate-badge translate-sub"> Субтитры</span>
              <div class="theme-play" data:eid="202" data:sid="1" data:hash="abc" data:episode="2"></div>
            </div>
          </body>
        </html>
        """

        episodes = parser.list_unplayed_episodes(FakeSession(html), "example_show", 1)

        self.assertEqual([episode["episode"] for episode in episodes], [1, 2])
        self.assertEqual(episodes[0]["quality"], "4k")
        self.assertEqual(episodes[0]["play_eid"], "102")
        self.assertTrue(episodes[0]["has_subtitles"])
        self.assertEqual(episodes[1]["quality"], "720p")
        self.assertEqual(episodes[1]["play_eid"], "202")
        self.assertTrue(episodes[1]["has_subtitles"])


class FakePostResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeCallbackSession:
    """Serves a page carrying the API token and records callback posts."""

    def __init__(self, token="476b619c5b9d1378f8c76c04694a676a7a15d90e", responses=None):
        self.token = token
        self.responses = list(responses or [])
        self.posts = []
        self.get_urls = []

    def get(self, url, headers=None):
        self.get_urls.append(url)
        return FakeResponse(f'<html><body><div id="token" data:token="{self.token}"></div></body></html>')

    def post(self, url, headers=None, data=None):
        self.posts.append({"url": url, "headers": headers or {}, "data": data or {}})
        if self.responses:
            return self.responses.pop(0)
        return FakePostResponse(200, {"ok": True})


class ParserEpisodeIdTest(unittest.TestCase):
    EPISODE_HTML = """
    <html>
      <body>
        <h1>Silo</h1>
        <div class="episode-card" data:episode="3">
          <div class="episode-title">Solo</div>
          <div class="episode-watched"><div data:eid="298895" data:watched="0"></div></div>
          <span class="translate-badge translate-sub">Субтитры</span>
          <div class="theme-play" data:eid="298895" data:sid="42" data:hash="abc" data:episode="3"></div>
        </div>
      </body>
    </html>
    """

    def test_episode_carries_callback_eid(self):
        episodes = parser.list_unplayed_episodes(FakeSession(self.EPISODE_HTML), "Silo", 3)

        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["eid"], "298895")
        self.assertEqual(episodes[0]["page_url"], "https://soap4.me/soap/Silo/3/")

    def test_eid_falls_back_to_play_button(self):
        html = """
        <html>
          <body>
            <h1>Silo</h1>
            <div class="episode-card" data:episode="4">
              <div class="episode-title">Solo</div>
              <span class="translate-badge translate-sub">Субтитры</span>
              <div class="theme-play" data:eid="298896" data:sid="42" data:hash="abc" data:episode="4"></div>
            </div>
          </body>
        </html>
        """

        episodes = parser.list_unplayed_episodes(FakeSession(html), "Silo", 3)

        self.assertEqual(episodes[0]["eid"], "298896")


class ParserMarkWatchedTest(unittest.TestCase):
    EPISODE = {
        "episode": 3,
        "eid": "298895",
        "play_eid": "298895",
        "page_url": "https://soap4.me/soap/Silo/3/",
    }

    def test_posts_mark_watched_callback_for_the_episode(self):
        session = FakeCallbackSession()

        self.assertTrue(parser.mark_episode_watched(session, self.EPISODE))

        self.assertEqual(len(session.posts), 1)
        post = session.posts[0]
        self.assertEqual(post["url"], "https://soap4.me/callback/")
        self.assertEqual(
            post["data"],
            {
                "what": "mark_watched",
                "eid": "298895",
                "token": "476b619c5b9d1378f8c76c04694a676a7a15d90e",
            },
        )
        self.assertEqual(post["headers"]["Referer"], "https://soap4.me/soap/Silo/3/")
        self.assertEqual(post["headers"]["X-Requested-With"], "XMLHttpRequest")

    def test_token_is_fetched_once_per_session(self):
        session = FakeCallbackSession()

        parser.mark_episode_watched(session, self.EPISODE)
        parser.mark_episode_watched(session, dict(self.EPISODE, eid="298896"))

        self.assertEqual(len(session.get_urls), 1)
        self.assertEqual([post["data"]["eid"] for post in session.posts], ["298895", "298896"])

    def test_rejected_callback_reports_failure(self):
        session = FakeCallbackSession(responses=[FakePostResponse(200, {"ok": False})])

        self.assertFalse(parser.mark_episode_watched(session, self.EPISODE))

    def test_episode_without_eid_is_not_marked(self):
        session = FakeCallbackSession()

        self.assertFalse(parser.mark_episode_watched(session, {"episode": 3}))
        self.assertEqual(session.posts, [])


if __name__ == "__main__":
    unittest.main()
