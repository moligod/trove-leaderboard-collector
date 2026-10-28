# Trove leaderboard MOD and collector

[中文](README.md) | [Game Hub website](https://github.com/moligod/game-teamup-lobby)

## What this does

The modified in-game leaderboard writes data to a Trove configuration file. The Windows collector reads that file, stores snapshots locally in SQLite, exports CSV and can optionally upload complete snapshots to your own Game Hub. The collector UI is currently in Chinese; labels below include their English meaning.

- `mod/Redesigned - Leaderboard.tmod`: packaged game mod built from the bundled SWF.
- `mod/leaderboard.swf`: modified interface based on the original game leaderboard.
- `mod/Leaderboard.as`: modified ActionScript class extracted from the stock game UI, not a complete game UI project. Rebuilding requires the matching original SWF and compatible Flash tooling.
- `collector/collector_app.py` and `collector_core.py`: collector source.
- `collector/run-collector.bat`: Windows launcher.
- `tools/build_mod.py`: packages the existing SWF; `tools/rebuild_swf.py`: compiles the modified class using your own matching stock SWF and FFDec.
- `tests/`: importer, upload security and packaging tests.

## Install the game mod

The TMOD container, internal path `ui/leaderboard.swf`, checksum and bundled SWF bytes have been checked, but **installation and collection have not been tested in the current game version**. This version is based on the leaderboard SWF extracted from the installed game. Permission to redistribute game assets remains unverified; this repository starts from the current version and does not include the earlier modified UI history.

1. In Steam, right-click Trove → Properties → Installed Files → Browse and locate `Games/Trove/Live`; Glyph users can find the installation directory in the launcher. See [Trovesaurus's installation guide](https://trovesaurus.com/mods/using).
2. Close the game and copy `mod/Redesigned - Leaderboard.tmod` into that directory's `mods/` folder, not the `Live` root.
3. Disable other mods replacing `ui/leaderboard.swf` and keep backups.
4. Start the game, enable the mod in the in-game mod manager, and open the leaderboard. Check for the `Collector` control on the right; disable the mod if it conflicts or does not work with your game version.
5. The collector defaults to `%APPDATA%\Trove\ModCfgs\Redesigned - Leaderboard.cfg`. Keep the packaged mod title and filename; select the actual cfg manually if it differs.

After editing ActionScript, use [JPEXS FFDec](https://github.com/jindrapetrik/jpexs-decompiler) and a stock `leaderboard.swf` extracted from your own game to build a candidate. The script requires stock SHA-256 `5e4bc666e3552c16f1317f58ea0d3d56a1f2fe789588ca59e8b55e2e5c35e948` and refuses other versions. Substitute your own paths:

```powershell
python tools/rebuild_swf.py --ffdec 'C:\path\to\ffdec-cli.exe' --original-swf 'C:\path\to\stock-leaderboard.swf' --output 'C:\path\to\new-candidate.swf'
```

After checking and testing the candidate, replace `mod/leaderboard.swf` and run `python tools/build_mod.py` to package it. The latter only packages an existing SWF; it does not compile ActionScript.

## Set up the collector

1. Use Windows and install Python 3 (3.10 or newer recommended), including Tcl/Tk. The collector uses the Python standard library and does not need `pip install`.
2. Download or extract the complete directory to a writable location. The collector creates its database next to its source files.
3. Double-click `collector/run-collector.bat`. Alternatively, open PowerShell in `collector` and run `py -3 collector_app.py`, or `python collector_app.py` if `py` is unavailable.
4. The first run creates `collector/leaderboard_collector.sqlite3`. The bottom of the window displays the database path. Closing the app does not erase it.

## First collection, step by step

1. Start Trove, enable this mod, open the stock leaderboard and click `Collector` on the right.
2. Click `1. Catalog`. In the collector, check the configuration path: it defaults to `%APPDATA%\Trove\ModCfgs\Redesigned - Leaderboard.cfg`. Use `选择` (Choose) if yours differs.
3. Click `导入目录` (Import catalog); board categories and IDs should appear on the left.
4. Keep the collector open and enable `自动导入配置文件变化`. Click `3. All boards` to collect each board, or `2. Current board` for the selected board. The mod switches the filter to Everyone and temporarily locks the stock board selection, filters and paging while collecting.
5. Watch the collector log, rows, expected count, complete flag and saved time. Data is saved in batches; a timeout or an incomplete response stops collection without marking that batch complete. Click `3. All boards` again to attempt to resume from saved progress.
6. `Reset / Stop` stops collection and clears the mod's resume state, **not the collector database**. Search-box commands and RANGE collection from the previous custom UI are not present in this stock-interface version; previous collector data remains.

Real in-game operation, resumption and completeness remain untested. If no data appears, check that the selected cfg changes and inspect the collector log.

## Inspect, export and delete

- Select a board on the left and a collection time at upper right to view its rows. `完成` indicates the collector's recorded completeness state.
- To export, select a board and snapshot and click `导出 CSV` (Export CSV). Output goes to `collector/exports/`; a dialog displays the path.
- Right-click a collection time and choose `删除该采集时间` to delete that single snapshot.
- `清空选中` and `清空全部数据` delete selected or all local collection data after confirmation. Back up SQLite first. These files may contain player data.
- `打开目录` opens the collector folder. The database, exports and stored upload token are local to this folder.

## Upload to your own Game Hub (optional)

1. Set a unique random `LEADERBOARD_COLLECTOR_TOKEN` of at least 32 characters in the website repository’s root `.env`. Recreate the backend container to apply the changed environment, for example run `docker compose up -d backend` from the website repository root. A plain `docker compose restart` does not reload changed environment values.
2. Ensure the website is reachable from the collector computer. Click `上传数据` (Upload data). In `上传地址` (upload URL), enter the **full** endpoint, e.g. `http://127.0.0.1:8080/api/collector/leaderboard/snapshots` for a local deployment or `https://your-domain.example/api/collector/leaderboard/snapshots` for a remote deployment. Use HTTPS in production. The default URL is empty.
3. Enter the identical token in `采集密钥` (collector token), then click `保存配置` (Save configuration). It is stored in the local SQLite database; do not share that file.
4. Click `选中最新数据(全)` (select latest complete data), then `上传选中` (upload selected). The current implementation requires the set of **all latest complete board snapshots**, rather than an arbitrary single board. Date or status filters can hide required rows; clear them if selection is incomplete.
5. The collector creates a server snapshot, uploads its boards and publishes it. This replaces the website’s current snapshot with the uploaded set. Check the upload status and errors. Incomplete collection cannot be published as a complete snapshot. Redirects are not followed; enter the final endpoint if a 3xx response occurs.

## Troubleshooting

- **Python or Tkinter missing:** run the launcher command in PowerShell and inspect errors; check `py -3 --version` and `py -3 -m tkinter`. The batch script tries `py`, then `python`.
- **cfg missing or catalog empty:** verify the mod is loaded, click `1. Catalog` in the collector panel, wait for the file write, select the actual cfg, then click `导入目录`.
- **No snapshots:** click `3. All boards` or `2. Current board`, enable automatic import, check that the cfg changes, inspect the log and try `刷新`.
- **Unexpected resume position:** check in-game progress; `Reset / Stop` resets MOD progress but keeps old collector snapshots.
- **Upload fails / 401 or 503:** verify the full URL, matching token of at least 32 characters, network and reverse proxy; recreate the backend after editing `.env`. Clear filters and select latest complete data if selection is rejected.
- **Old `127.0.0.1:17890` interface:** removed in the stock-interface version. Collection uses the cfg file; uploads use the website endpoint.

## Privacy and keepalive

SQLite contains collected data, upload URL and token; cfg files, CSV exports, logs and backups can also contain player data. Do not commit or share them. Rotate a leaked token in both website and collector. Ignore rules cover SQLite, `exports/` and backups, but inspect the folder before sharing it.

Optionally drag `◎` onto the Trove window and click `开始挂机` (Start keepalive). The app posts one background R key immediately and about every 60 seconds; click `停止挂机` to stop. This depends on the Windows target handle and game behavior and may not work with the game. Check game rules before using it.

## Development and verification

```powershell
python -m unittest discover -s tests -v
python -m py_compile collector/collector_core.py collector/collector_app.py tools/build_mod.py tools/rebuild_swf.py
```

Synthetic cfg tests cover single boards, merged batches, multi-board ranges and CSV export; upload was tested against an isolated Game Hub database. These tests do not establish current in-game compatibility. The source, SWF and TMOD are based on game UI; permission to redistribute game assets remains unverified. This repository does not include the earlier modified UI history.
