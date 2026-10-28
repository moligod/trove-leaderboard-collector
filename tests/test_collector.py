import csv
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'collector'))
import collector_core as core
import collector_app
sys.path.insert(0, str(ROOT / 'tools'))
import build_mod

HEADER = '\t'.join(core.ENTRY_COLUMNS)
def batch(board, run, start, names, complete=False):
    end = start + len(names) - 1
    meta = (f'leaderboard={board};run={run};start={start};end={end};entries={len(names)};'
            f'saved={end};expected=2;complete={str(complete).lower()};cleared=false')
    rows = [f'{i}\t{name}\t{100-i}\t0\tScore\tfalse\tfalse' for i, name in enumerate(names, start)]
    return meta + core.BATCH_SEPARATOR + HEADER + '||' + '||'.join(rows)

class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = core.init_db(Path(self.temp.name) / 'test.sqlite3')

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_numbered_multi_board_import_with_regular_batch_and_deduplication(self):
        values = {'leaderboard_batch': batch('1', 'single', 1, ['Alpha'], False),
                  'leaderboard_batch_2': batch('2', 'multi_2', 1, ['Beta'], False),
                  'leaderboard_batch_3': batch('3', 'multi_3', 1, ['Gamma'], False)}
        result = core.import_cfg_values(self.conn, values)
        self.assertEqual(result.imported, 3)
        self.assertEqual(core.import_cfg_values(self.conn, values).skipped, 3)
        for board, name in [('1','Alpha'), ('2','Beta'), ('3','Gamma')]:
            snapshots = core.get_snapshots(self.conn, board)
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(core.get_snapshot_entries(self.conn, snapshots[0]['id'])[0]['player_name'], name)
            self.assertEqual(snapshots[0]['complete'], 0)

    def test_incremental_batches_merge_and_export_complete_snapshot(self):
        first = {'leaderboard_batch': batch('1', 'run1', 1, ['Alpha'])}
        last = {'leaderboard_batch': batch('1', 'run1', 2, ['Beta'], True)}
        self.assertEqual(core.import_cfg_values(self.conn, first).imported, 1)
        self.assertEqual(core.import_cfg_values(self.conn, last).imported, 1)
        snap = core.get_snapshots(self.conn, '1')[0]
        self.assertEqual((snap['entries'],snap['complete']), (2,1))
        path = core.export_snapshot_csv(self.conn, '1', snap['id'], Path(self.temp.name) / 'exports')
        with path.open(encoding='utf-8-sig',newline='') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([row['name'] for row in rows], ['Alpha','Beta'])

    def test_partial_write_is_not_imported(self):
        value = batch('1', 'incomplete', 1, ['Alpha']).replace('entries=1', 'entries=2')
        result = core.import_cfg_values(self.conn, {'leaderboard_batch': value})
        self.assertEqual((result.imported, result.pending), (0,1))
        self.assertEqual(core.get_snapshots(self.conn, '1'), [])

class SecurityAndPackagingTest(unittest.TestCase):
    def test_endpoint_validation(self):
        path = core.SNAPSHOT_UPLOAD_PATH
        self.assertEqual(core.validate_upload_url('https://example.com' + path + '/'), 'https://example.com' + path)
        self.assertEqual(core.validate_upload_url('http://127.0.0.1:8080/api/collector/leaderboard/daily'), 'http://127.0.0.1:8080' + path)
        for url in ('file:///etc/passwd', 'https://user:secret@example.com' + path,
                    'https://example.com' + path + '?token=secret', 'https://example.com/not-the-api'):
            with self.subTest(url=url), self.assertRaises(ValueError): core.validate_upload_url(url)

    def test_upload_does_not_follow_redirect(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(self.path)
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/other')
                self.end_headers()
            def do_GET(self):
                received.append(self.path)
                self.send_response(200); self.end_headers()
            def log_message(self, *args): pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            status, _ = collector_app.CollectorApp.post_upload_payload(None, f'http://127.0.0.1:{server.server_port}/start', {}, 'example-token')
            self.assertEqual(status, 302)
            self.assertEqual(received, ['/start'])
        finally:
            server.shutdown(); thread.join(); server.server_close()

    def test_modified_swf_does_not_contain_legacy_local_http_interface(self):
        import zlib
        swf = (ROOT / 'mod' / 'leaderboard.swf').read_bytes()
        body = zlib.decompress(swf[8:]) if swf[:3] == b'CWS' else swf[8:]
        self.assertNotIn(b'127.0.0.1:17890', body)
        self.assertIn(b'leaderboard_batch', body)
        self.assertIn(b'Collector', body)

    def test_tmod_contains_exact_swf_and_checksum(self):
        import struct, zlib
        swf = (ROOT / 'mod' / 'leaderboard.swf').read_bytes()
        data = (ROOT / 'mod' / 'Redesigned - Leaderboard.tmod').read_bytes()
        self.assertEqual(data, build_mod.build(swf))
        header_size = struct.unpack_from('<Q', data)[0]
        self.assertEqual(zlib.decompressobj().decompress(data[header_size:])[:len(swf)], swf)
        self.assertEqual(build_mod.trove_checksum(b'abcd'), 3967774508)
        self.assertEqual(build_mod.trove_checksum(b'abcde\xff'), 2254699561)

if __name__ == '__main__': unittest.main()
