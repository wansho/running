import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path


def import_render_module():
    cartopy = types.ModuleType("cartopy")
    cartopy_crs = types.ModuleType("cartopy.crs")
    cartopy_feature = types.ModuleType("cartopy.feature")
    cartopy_io = types.ModuleType("cartopy.io")
    cartopy_shapereader = types.ModuleType("cartopy.io.shapereader")
    cartopy_shapereader.Reader = object

    sys.modules.setdefault("cartopy", cartopy)
    sys.modules.setdefault("cartopy.crs", cartopy_crs)
    sys.modules.setdefault("cartopy.feature", cartopy_feature)
    sys.modules.setdefault("cartopy.io", cartopy_io)
    sys.modules.setdefault("cartopy.io.shapereader", cartopy_shapereader)

    return importlib.import_module("render")


class GetRunningDataTest(unittest.TestCase):
    def test_skips_rows_with_missing_pace(self):
        render = import_render_module()
        csv_content = "\n".join(
            [
                "DT,distance(Km),heart,pace,start_lat,start_lng",
                "2026-06-16 07:00:00,3.00,120,-,31.1,118.1",
                "2026-06-16 08:00:00,5.00,120,5:30,31.2,118.2",
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "running.csv"
            csv_path.write_text(csv_content, encoding="utf-8")
            original_csv_file = render.CSV_FILE
            try:
                render.CSV_FILE = csv_path
                dts, accs, distances, paces, start_lats, start_lngs = render.get_running_data()
            finally:
                render.CSV_FILE = original_csv_file

        self.assertEqual(1, len(dts))
        self.assertEqual([5.0], distances)
        self.assertEqual([330], paces)
        self.assertEqual([5.0], accs)
        self.assertEqual([31.2], start_lats)
        self.assertEqual([118.2], start_lngs)


if __name__ == "__main__":
    unittest.main()
