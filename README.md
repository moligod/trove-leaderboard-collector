# Trove 排行榜 MOD 与采集器使用说明

[English](README.en.md) | [Game Hub 网站](https://github.com/moligod/game-teamup-lobby)

## 功能和目录

本项目包含游戏内 MOD、Windows 采集器源码和使用说明三部分。MOD 在游戏内采集排行榜并写入 Trove 配置文件；采集器读取配置文件、保存本地数据库，可查看快照、导出 CSV，或把完整排行榜上传到自己部署的 Game Hub。采集器界面目前为中文。

- `mod/Redesigned - Leaderboard.tmod`：根据当前 SWF 打包的游戏 MOD。
- `mod/leaderboard.swf`：基于游戏原版界面修改的排行榜文件。
- `mod/Leaderboard.as`：从游戏原版排行榜提取并修改的 ActionScript 类；不是完整的游戏 UI 工程，不能仅凭此文件重建 SWF。重新制作需要对应版本的原始 SWF 和兼容 Flash 工具。
- `collector/collector_app.py`、`collector_core.py`：采集器程序。
- `collector/run-collector.bat`：Windows 启动脚本。
- `tools/build_mod.py`：从现成 SWF 重新生成 `.tmod`；`tools/rebuild_swf.py`：用用户自行提取的对应版本原版 SWF 和 FFDec 重新编译修改类。
- `tests/`：采集器导入、上传安全和打包测试。

## 安装游戏 MOD

已检查 `.tmod` 的容器结构、内部路径 `ui/leaderboard.swf` 和内容与本目录 SWF 一致；**尚未在当前游戏版本中实际启动验证**。本版以本机游戏原版排行榜资源为基础，来源为游戏资源包；原版素材的再发布授权尚未确认。本仓库以当前版本作为初始提交，不包含此前改版排行榜的提交历史。

1. 在 Steam 库中右键 Trove → 属性 → 已安装文件 → 浏览，找到 `Games/Trove/Live`；Glyph 用户打开启动器中的游戏安装目录。默认位置和 MOD 安装说明可参考 [Trovesaurus](https://trovesaurus.com/mods/using)。
2. 关闭游戏，将 `mod/Redesigned - Leaderboard.tmod` 复制到该目录下的 `mods/` 文件夹。不要把它复制到 `Live` 根目录。
3. 若已安装其他替换 `ui/leaderboard.swf` 的排行榜 MOD，先禁用其他同类 MOD；保留原文件备份。
4. 启动游戏，在游戏 MOD 管理界面确认它已启用，打开排行榜，检查右上方是否出现 `Collector` 入口。若冲突或界面异常，禁用该 MOD 并检查游戏版本。
5. 采集器默认使用 `%APPDATA%\Trove\ModCfgs\Redesigned - Leaderboard.cfg`；MOD 文件名与标题不要随意改名。若实际 cfg 不同，可在采集器中手动选择。

更改 ActionScript 后，可使用 [JPEXS FFDec](https://github.com/jindrapetrik/jpexs-decompiler) 和从自己游戏安装中提取的原版 `leaderboard.swf` 重建候选文件；脚本要求该原版的 SHA-256 为 `5e4bc666e3552c16f1317f58ea0d3d56a1f2fe789588ca59e8b55e2e5c35e948`，不匹配时会拒绝编译。自行将下面的路径换成实际路径：

```powershell
python tools/rebuild_swf.py --ffdec 'C:\path\to\ffdec-cli.exe' --original-swf 'C:\path\to\stock-leaderboard.swf' --output 'C:\path\to\new-candidate.swf'
```

检查和测试候选文件后，将其替换到 `mod/leaderboard.swf`，再运行 `python tools/build_mod.py` 生成 `.tmod`。后者只负责打包，不能独立从 ActionScript 编译。

## 准备采集器

1. 使用 Windows，安装 Python 3（建议 3.10 或更高），安装时包含 Tcl/Tk。程序使用 Python 标准库，无需 `pip install`。
2. 解压或下载完整目录。不要把采集器直接放在没有写入权限的位置；它需要在自身目录创建数据库。
3. 双击 `collector/run-collector.bat`。也可在 PowerShell 中进入 `collector` 目录后执行 `py -3 collector_app.py`。如果 `py` 不可用，使用 `python collector_app.py`。
4. 第一次运行后，会在 `collector/leaderboard_collector.sqlite3` 创建数据库。界面底部显示数据库位置。关闭窗口不会删除数据。

## 首次采集：按顺序操作

1. 启动 Trove，启用本项目 MOD，打开游戏原版排行榜。右侧点击 `Collector` 打开采集面板。
2. 点击 `1. Catalog` 写入排行榜目录。在采集器顶部检查“配置文件”路径，默认是 `%APPDATA%\Trove\ModCfgs\Redesigned - Leaderboard.cfg`；路径不同可点击“选择”。
3. 点击采集器“导入目录”，左侧应显示排行榜分类和 ID。
4. 保持采集器开启并勾选“自动导入配置文件变化”。点击面板的 `3. All boards` 依次采集全部榜单；`2. Current board` 仅采集当前选中的榜单。采集期间 MOD 会选择“所有人”，并暂时锁住原版的分类、筛选和翻页按钮。
5. 在采集器观察日志、行数、应有、完成和保存时间，选择榜单和采集时间查看明细。数据按批写入；某批数量不符或请求超时会停止，不会将该批标记为完成。再次点击 `3. All boards` 可尝试从已保存进度续采。
6. `Reset / Stop` 停止并清除 MOD 续采进度，**不删除采集器数据库中的快照**。旧版的搜索框命令和 RANGE 区间采集不在这个原版界面版本中；旧采集器数据仍保留。

游戏内真实运行、续采和完整性仍需测试；不要仅凭本地模拟结果认定榜单完整。如果目录或数据没有出现，请确认所选 cfg 是否写入变化并查看采集器日志。

## 查看、导出和清理

- **查看快照：**左侧选排行榜，右上选采集时间，右侧表格显示该快照的玩家数据。`完成` 表示程序记录的完整状态。
- **导出：**依次选排行榜和采集时间，点击“导出 CSV”。文件写入 `collector/exports/`，弹窗会显示路径。
- **删除单次快照：**在右上的采集时间上点击右键，选择“删除该采集时间”并确认。
- **清空选中 / 清空全部数据：**删除本地采集数据，请先备份 SQLite；界面会要求确认。不要把数据库和 CSV 当作公开示例，里面可能有玩家数据。
- **打开目录：**点击“打开目录”可定位采集器文件夹。数据库、导出和本地密钥默认都在此目录下。

## 上传到自己的 Game Hub（可选）

1. 在网站仓库根目录的 `.env` 中设置独立随机的 `LEADERBOARD_COLLECTOR_TOKEN`，至少 32 个字符；重新创建后端容器使配置生效。仅更改 `.env` 后执行普通 `docker compose restart` 不会更新容器环境变量。可在网站仓库根目录执行 `docker compose up -d backend`。
2. 确认网站已经启动并可从采集器机器访问。打开采集器“上传数据”，填写完整地址，例如本机部署：`http://127.0.0.1:8080/api/collector/leaderboard/snapshots`；远程网站：`https://你的域名/api/collector/leaderboard/snapshots`。生产环境使用 HTTPS。默认地址为空，必须自行填写。
3. 在“采集密钥”填入与网站相同的值，点击“保存配置”。密钥存放在本地 SQLite 中；不要分享数据库。
4. 在上传窗口点击“选中最新数据(全)”，再点击“上传选中”。当前实现要求选择**所有最新完整榜单快照**，不支持仅挑一个完整榜单发布。日期和状态过滤可能隐藏需要的行；如提示缺少数据，清除过滤并重新选择。
5. 程序会先创建服务器快照，再上传各榜单并发布；查看窗口状态和错误信息确认结果。发布会以这次上传的完整榜单集替换网站的当前快照。未完成的采集不能作为完整快照发布。不要把上传密钥发给其他人。上传接口不会跟随重定向；出现 3xx 时填写最终接口地址。

## 常见问题

- **启动后窗口闪退 / 找不到 Python：**从 PowerShell 运行启动命令查看错误；检查 `py -3 --version`、`py -3 -m tkinter`，确认安装 Python 和 Tcl/Tk。脚本会优先使用 `py`，再尝试 `python`。
- **提示找不到 cfg：**先确认 MOD 已加载并点击 `1. Catalog`；用“选择”指定实际 cfg。不同 MOD 名称可能使用不同配置文件。
- **目录为空：**在采集面板重新点击 `1. Catalog`，等文件写入后点击“导入目录”。
- **有目录但没数据：**确认点击了 `3. All boards` 或 `2. Current board`，勾选自动导入，检查日志和 cfg 是否更新；必要时点“刷新”。
- **续采位置不对：**先确认游戏中的续采状态；确需重头开始时使用 `Reset / Stop`，注意它不会删除数据库里的旧快照。
- **无法上传 / 401 或 503：**核对完整接口地址、网站与采集器的密钥是否一致且至少 32 字符，并确认后端已重建以加载新配置。检查 HTTPS、网络和反向代理。上传选择错误时清除过滤并重新选择最新完整数据。
- **旧版 `127.0.0.1:17890`：**原版界面版本已移除该实验接口；采集使用 cfg，上传则使用网站接口。

## 安全和挂机

SQLite 包含采集结果、上传地址和令牌；`.cfg`、CSV、日志及备份也可能包含玩家数据。不要提交或分享这些文件。令牌泄露时请更换网站和采集器两处配置。公开版 Git 忽略规则覆盖 SQLite、`exports/` 和备份，但上传整个文件夹前仍应自行检查。

可将 `◎` 拖到 Trove 窗口后点击“开始挂机”：程序立即发送一次后台 R 键，之后约每 60 秒发送一次；点击“停止挂机”结束。功能依赖 Windows 目标窗口和游戏响应，不保证游戏接受后台按键，使用前请自行确认游戏规则。

## 开发和验证

```powershell
python -m unittest discover -s tests -v
python -m py_compile collector/collector_core.py collector/collector_app.py tools/build_mod.py tools/rebuild_swf.py
```

已用模拟 cfg 验证单榜、分批合并、多榜区间和 CSV 导出；用隔离的 Game Hub 数据库验证上传。模拟测试不等于真实游戏内采集验证。源码、SWF 和 TMOD 基于游戏 UI，原游戏资源的再分发权限尚未确认。本仓库不含此前改版排行榜的 Git 历史。
