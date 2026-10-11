# 暂停后继续加载当前集

原生播放器暂停后约12秒就停止预读，灰条随之停止。本补丁在暂停时顺序读取当前集的原片 Range 块，恢复播放和 seek 复用已存块；没有缓存时继续正常网络读取。只影响当前原生会话，后三集预取仍由 #187 负责。

依赖 #204 的 `BASELINES.json.nativeHead` 所记录提交，各文件 LF 规范化后的补丁前后 SHA256 见 `BASELINES.json`。这是公开接入材料，合并不代表发行版已经修复；不包含 EXE、第三方 DLL、真实视频或账号数据。

## 缓存与生命周期

新增 `src/desktop_range_cache.py`，将原片块保存在已有 UUID 会话目录。写入 owner 在锁内先检查预算再写文件，默认单会话512MiB，物理文件不允许超调。关闭 mpv 的 append-only 磁盘缓存，保留约12秒、32MiB 有界包内存和16MiB Range 内存；达到磁盘预算或磁盘写失败后，后台停止填充，前台继续正常读取，沿用原解码器。

`cacheFileBytes/cacheComplete/preloadLimited/preloadReason` 来自块缓存 owner。只有原片完整时才报告完整范围；不把下载字节比例当作可播进度。退出和切集取消后台并关闭文件，随后由会话 owner 清理目录。非完整原片包含的块不能单独作为离线完整缓存。后台线程因临时读取失败退出后，缓存未完整且未达限时按至少1秒间隔重启；每会话最多一个加载线程。

## 应用与验证

将新增模块加入私有 backend，然后检查、应用 `enable-paused-preload.patch`。补丁覆盖 `desktop_stream.py`、`desktop_hls_service.py` 和 `desktop_native.py`；基线漂移时先适配，不强制覆盖。

```pwsh
pwsh -NoProfile -Command "git apply --check <contribution-dir>/enable-paused-preload.patch"
pwsh -NoProfile -Command "python -I contributions/desktop-paused-preload/tests/test_patch.py --native-package <native-dir> --prefetch-package <prefetch-dir>"
pwsh -NoProfile -Command "git apply <contribution-dir>/enable-paused-preload.patch"
```

测试核对摘要、补丁可应用性与编译，运行原生回归及缓存/验证器测试。覆盖无节流并发写入不超预算、重复与取消写入、完整块复用、磁盘失败，以及依据输入大小和限速计算验证期限。可选真实 HEVC 包一致性用例未配置时明确跳过。

`tests/verify_preload.py` 在 Windows x64 使用经核验的 libmpv、自有 HEVC 媒体、本机鉴权 API 和离屏父窗口；不控制用户播放器。它将自有媒体封装成测试 CENC，测试只放行 input-hook 夹具，不能代替实际鼠标/键盘验收。

```pwsh
pwsh -NoProfile -Command "python -I contributions/desktop-paused-preload/tests/verify_preload.py --native-package <native-dir> --prefetch-package <prefetch-dir> --mpv <verified-libmpv-2.dll> --source <owned-hevc.mp4> --sha <sha256> --run <owned-output-dir>"
```

`--software` 强制软解；`--cache-budget 8388608 --range-delay 0` 验证无节流8MiB硬预算。默认 Range 延迟0.12秒，验证期限随输入块数增长，最多3600秒；可用 `--preload-timeout` 在1至3600秒内显式指定。仅 preloadReason=budget 接受达限分支，缓存打开/写入或线程启动失败会使验证失败。达限后采样3秒，写入字节须接近可计算容量且大于零，最大物理文件大小不得超过预算，末尾1秒必须稳定。报告及媒体不提交。

维护者接入发布前，仍需验证真实前端 #189 灰条、冷缓存、慢网、断网、快速切集、默认音频与倍速恢复。此补丁不提供连续画面录制结论，也不宣称正式版已无黑屏。Related to #23、#181：发布并完成暂停加载/恢复验收后再考虑关闭；#202/#199 仅部分覆盖，不自动关闭。

回滚撤销补丁和新增模块，恢复约12秒预读；保留用户原片与观看记录。

备用集的隐藏暂停也不会启动整集后台填充；提升为当前集后，由用户暂停触发。真实合成源的备用首帧仍按有界预读准备。

适配最新原生音频就绪与已排队控制状态，保留用户暂停才填满缓存及隐藏备用不触发整集下载的边界。

当前公开组合76项全部通过，已提供自有HEVC夹具完成可选项。缓存关闭时可选磁盘flush失败不再中断资源清理。真实自有40秒HEVC+AAC、libmpv及鉴权API复测中，正常填满与无节流8MiB硬预算均通过，验证暂停后确有新增填充、2x/3x恢复、seek及释放。1MiB在启动预读时已达限的输入被验证器明确拒绝；它不能证明暂停加载线程运行，需提高预算重测。新增缓存关闭失败回归在旧实现失败。

暂停预读补丁已同步原生窗口绑定、可取消准备和控制顺序基线 6223e50a7f470065f6cbd5d4dc520690c2e8e516。当前组合82项全部通过，含已有自有HEVC夹具；精确补丁与SHA检查通过。本机安装待完成。


## 本轮二次反馈修复

公开验证器在 release、jobs.close 或 prefetch.close 抛错时仍尝试其余清理，记录失败，并在最外层 finally 通知主线程退出。回归执行实际 scenario 的 finally；旧实现失败，当前8项验证器测试通过。

本机完整候选、安装回读与反馈观察期仍待完成。


## 本轮三次反馈修复

接入依赖以 BASELINES.json 为准，具体 #204 提交读取 nativeHead，本批重新核对补丁摘要并执行组合回归。

本机候选与安装仍待完成。


本轮审查回归（2026-10-12，第四批）：4242235633/5639/4242299666/9671：探针等待bootstrap静稳并验证preload启动；预算至少一块、显式预算必须触顶且不超限；seek目标依时长取值。跨包实测发现暂停命令迁移后user_paused未更新，改在当前暂停/恢复分支同步。

修改后公共回归、待机组合180项、Chrome87项和真实libmpv字幕检查通过。暂停预加载实测触及8MiB硬上限并稳定，2x/3x恢复及释放通过。本机候选融合与安装尚未完成，上游PR尚未合并；公共测试通过不等于安装验收通过。


本轮第六批审查（2026-10-12）：4242516843/6845/6847：README依赖跟随BASELINES，容量基于实际CENC文件，12秒断言随夹具时长取界。

旧实现回放失败，修改后的对应回归通过；公开待机组合192项、浏览器组合88项及本机融合后端295项通过，无跳过。本机真实Tauri原生及HLS含社交交互验收通过，关闭后资源归零；安装验收仍待完成，上游尚未合并发布。

本轮审查修复：4242701917：小片bootstrap已完整作为输入特定结果，全量与预算分支明确区分。

验证：新增反例在旧代码失败，修复后通过；待机组合 201 项、融合后端 308 项无跳过、浏览器组合 88 项通过。真实 libmpv 字幕切换，以及候选 Tauri 原生/HLS 播放和社交交互通过，关闭后资源归零。本机更新安装验收随后执行；上游尚未合并发布。
