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


if __name__ == "__main__":
    unittest.main()
