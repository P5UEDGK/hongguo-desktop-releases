# 单备用会话与确认交接

让下一集在当前集播放期间正常下载、解码首帧并保持隐藏、暂停、静音。自动续播接管已准备会话；最多一个备用，不重复下载当前源。只有首帧和控制生效后才允许提升、释放父会话。

这是发行仓库的接入材料，依赖#204与#187，依赖HEAD及文件摘要见BASELINES.json。与#205暂停缓存补丁有独立改动，若同时接入须在完整应用源码融合，不能直接连续套用冲突补丁。合并材料仍需维护者接线并发布。

## 接线与生命周期

应用src下三个backend补丁和原生测试适配补丁。原HlsJobs增加on_activate=prefetch.promote，保留on_start=prefetch.begin、before_work=prefetch.before_work、on_finish=prefetch.finish和source_loader=prefetch.load_source。CORS允许请求头加入x-desktop-prewarm-parent，保持回环鉴权与来源白名单。

创建请求带x-desktop-codec-negotiation:1及x-desktop-prewarm-parent:<当前UUID>。服务器验证同剧、紧邻下一集、零偏移、有效父会话与单备用，能力接口standbyPlayback:1。备用继承创建时的预缓存代际，before_work和activate均拒绝已过期代际。

原生outputReady后提交可见控制，后端先等旧音频暂停ACK再提交新控制；失败恢复已接受的父暂停意图。control只表示排队成功，前端还须确认visible/outputReady/revision，再POST /{id}/activate。HLS首帧就绪后POST activate。激活在会话锁内原子比较代际并迁移，过期返回409且保留父关系，不会把新前台任务取消。重复成功激活幂等；失败/取消不会返回虚假成功。

提升复用prepared source，仅异步刷新元数据及未来下载。过时元数据不覆盖新代际，已经结束的任务释放foreground；未结束HLS继续保留原编码槽直到实际完成。释放父会话级联取消未提升子会话，提升后子会话独立。沿用总会话上限、编码信号量、到期回收和shutdown close。

## 验证与回滚

```pwsh
pwsh -NoProfile -Command "python -I contributions/desktop-standby-sessions/tests/run.py --native-package <native-contribution-dir> --prefetch-package <prefetch-contribution-dir>"
```

公开组合144项：143通过、1项可选HEVC样本测试跳过。包含原生资源池、缓存/下载、单处理槽、代际/取消、控制失败恢复和迟到激活。私有融合候选另通过138项及真实Tauri原生/HLS 1x/2x/3x状态检查，不能代替上游实际接入与连续画面验收。

用户已确认上一批本机黑屏消失，本轮继续处理短暂停顿；上游发行版是否解决需接入发布后验证。回滚撤销补丁及on_activate接线，保留用户原片和观看记录。[Issue关闭条件](ISSUES.md)，不自动关闭。
