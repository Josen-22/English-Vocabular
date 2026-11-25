import os
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from desktop import load_html, resource_path
from paths import DEFAULT_HOME, default_home


class PackagingTests(unittest.TestCase):
    def test_existing_data_directory_wins(self):
        with patch.object(Path,'exists',return_value=True):
            self.assertEqual(default_home(),DEFAULT_HOME)

    def test_d_drive_preserves_the_requested_default(self):
        with patch.object(Path,'exists',return_value=False),patch.object(Path,'is_dir',return_value=True):
            self.assertEqual(default_home(),DEFAULT_HOME)

    def test_pc_without_d_uses_current_user_data(self):
        with patch.object(Path,'exists',return_value=False),patch.object(Path,'is_dir',return_value=False),patch.dict(os.environ,{'LOCALAPPDATA':'C:/Users/Test/AppData/Local'}):
            self.assertEqual(default_home(),Path('C:/Users/Test/AppData/Local/EnglishVocabular'))

    def test_local_icon_is_embedded_and_has_small_windows_sizes(self):
        html=load_html()
        self.assertIn('src="data:image/png;base64,',html)
        self.assertNotIn('<!--APP_ICON-->',html)
        data=resource_path('assets/vocab-icon.ico').read_bytes()
        reserved,kind,count=struct.unpack_from('<HHH',data)
        self.assertEqual((reserved,kind),(0,1))
        sizes={data[6+16*i] or 256 for i in range(count)}
        self.assertTrue({16,24,32,48,64,128,256}<=sizes)


if __name__=='__main__':
    unittest.main()
