import unittest
from pathlib import Path

from soap4downloader import util


class UtilPathTest(unittest.TestCase):
    def test_episode_dest_path_matches_requested_layout(self):
        path = util.episode_dest_path(Path("downloads"), "Show Name", 3, 7, ".mp4")

        self.assertEqual(path, Path("downloads") / "Show Name" / "Season 3" / "Show Name - s03e07.mp4")


if __name__ == "__main__":
    unittest.main()
