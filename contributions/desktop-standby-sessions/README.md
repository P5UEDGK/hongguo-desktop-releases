# 单备用会话与确认交接

让下一集在当前集播放期间正常下载、解码首帧并保持隐藏、暂停、静音。自动续播接管已准备会话；最多一个备用，不重复下载当前源。只有首帧和控制生效后才允许提升、释放父会话。

这是发行仓库的接入材料，依赖#204与#187，依赖HEAD及文件摘要见BASELINES.json。与#205暂停缓存补丁有独立改动，若同时接入须在完整应用源码融合，不能直接连续套用冲突补丁。合并材料仍需维护者接线并发布。

## 接线与生命周期

应用src下三个backend补丁和原生测试适配补丁。原HlsJobs增加on_activate=prefetch.promote、standby_source_loader=prefetch.load_standby_source，保留on_start=prefetch.begin、before_work=prefetch.before_work、on_finish=prefetch.finish和source_loader=prefetch.load_source。CORS允许请求头加入x-desktop-prewarm-parent，保持回环鉴权与来源白名单。

创建请求带x-desktop-codec-negotiation:1及x-desktop-prewarm-parent:<当前UUID>。服务器验证同剧、紧邻下一集、零偏移、有效父会话与单备用，能力接口standbyPlayback:1。备用继承创建时的预缓存代际，before_work和activate均拒绝已过期代际。

原生outputReady后提交可见控制，后端先等旧音频暂停ACK再提交新控制；失败恢复已接受的父暂停意图。control只表示排队成功，前端还须确认visible/outputReady/revision，再POST /{id}/activate。HLS首帧就绪后POST activate。激活在会话锁内原子比较代际并迁移，过期返回409且保留父关系，不会把新前台任务取消。重复成功激活幂等；失败/取消不会返回虚假成功。

提升复用prepared source，同步迁移代际后返回延迟启动函数；HlsJobs清除父关系并退出会话锁后才调用它，随后异步刷新元数据及未来下载。不可在promote内提前启动元数据线程。过时元数据不覆盖新代际，已经结束的任务释放foreground；未结束HLS继续保留原编码槽直到实际完成。释放父会话级联取消未提升子会话，提升后子会话独立。沿用总会话上限、编码信号量、到期回收和shutdown close。

## 验证与回滚

```pwsh
pwsh -NoProfile -Command "python -I contributions/desktop-standby-sessions/tests/run.py --native-package <native-contribution-dir> --prefetch-package <prefetch-contribution-dir>"
```

公开组合158项全部通过，已提供自有HEVC夹具完成可选项。包含原生资源池、缓存/下载、单处理槽、代际/取消、控制失败恢复和迟到激活。私有融合候选另通过138项及真实Tauri原生/HLS 1x/2x/3x状态检查，不能代替上游实际接入与连续画面验收。

用户已确认上一批本机黑屏消失，本轮继续处理短暂停顿；上游发行版是否解决需接入发布后验证。回滚撤销补丁及on_activate接线，保留用户原片和观看记录。[Issue关闭条件](ISSUES.md)，不自动关闭。

前序批次补丁基线曾同步#204的d2c86d078695570f0dbd6f9870f3b3bbcd87b8ee及#187的8f28b71bd9c59a6a47e31413f7be3f486d81ab0b，保留异步诊断writer和原生源一致性修复。新增立即完成元数据的确定性回归，证明先解除父关系再完成foreground清理；旧实现失败，当前组合通过。

备用会话补丁同步原生基线 6223e50a7f470065f6cbd5d4dc520690c2e8e516 与prefetch 6b78af10c856f1327ef7f16f9242e6754057b8f4。保留元数据返回后的代际重查；预热在可取消准备锁内保留父会话，使用job绑定的请求窗口。组合167项全部通过，含自有HEVC夹具、新窗口归属及全部prefetch回归。本机安装待完成。


## 本轮二次反馈修复

原生 control 在读取请求体后，将会话有效性检查、提交及 activation revision 更新置于同一 jobs.guard 临界区，避免 DELETE 在父会话已暂停后抢先取消。预缓存依赖同步本轮前台状态与后台 stage 清理修复；保留 promote 的解除父关系后启动行为。确定性双线程回归在旧实现失败。

本机完整候选、安装回读与反馈观察期仍待完成。


## 本轮三次反馈修复

HlsJobs新增可选standby_source_loader=prefetch.load_standby_source。该入口按job的父代际和取消状态检查冷源，不要求current为子集，也不提前提升；旧README接线的冷备用回放失败。推进新前台代际时取消正在编码的warm owner，让编码器按既有cancelled回调退出，实际退出后再释放busy。两个旧回放失败，当前174项全部通过（含自有HEVC）。当前原生及prefetch依赖均读取BASELINES.json对应HEAD，不再使用固定旧提交。

本机候选与安装仍待完成。


本轮审查回归（2026-10-12，第四批）：4242307145：过期冷待机下载在返回前释放本次新建source，借用缓存source不关闭。

修改后公共回归、待机组合180项、Chrome87项和真实libmpv字幕检查通过。暂停预加载实测触及8MiB硬上限并稳定，2x/3x恢复及释放通过。本机候选融合与安装尚未完成，上游PR尚未合并；公共测试通过不等于安装验收通过。


依赖元数据同步到完整缓存时间线校验提交；四个补丁的目标文件摘要保持不变。


本轮第六批审查（2026-10-12）：4242520609/0615/0618：显示前验证当前generation；HLS父到native子跨模式拒绝未经确认音频交接；README依赖同步。

旧实现回放失败，修改后的对应回归通过；公开待机组合192项、浏览器组合88项及本机融合后端295项通过，无跳过。本机真实Tauri原生及HLS含社交交互验收通过，关闭后资源归零；安装验收仍待完成，上游尚未合并发布。

本轮审查修复：4242698571/8574：代际推进撤销已完成待确认备用控制并恢复父意图；拒绝native父到HLS子跨模式提升。

验证：新增反例在旧代码失败，修复后通过；待机组合 201 项、融合后端 308 项无跳过、浏览器组合 88 项通过。真实 libmpv 字幕切换，以及候选 Tauri 原生/HLS 播放和社交交互通过，关闭后资源归零。本机更新安装验收随后执行；上游尚未合并发布。

2026-10-12 第十轮复核：4242836457：重复visible交接不重复推进已持有的父暂停修订号，仍保留后来用户意图。

验证：318 项融合后端测试无跳过，205 项备用组合测试、13 套前端测试和 88 项社交浏览器检查通过；真实 libmpv 字幕检查、1 秒片源 2x/3x 检查及候选 Tauri 原生/HLS、社交交互与关闭释放通过。新增回归同时保留旧实现失败证据。本机安装验收随后执行，上游尚未合并发布。

2026-10-12 第十二轮复核：4243007403/7409：提升回调异常不能返回激活成功；阻塞native控制放入工作线程。

验证：329 项融合后端测试无跳过，211 项备用组合测试、16 套前端测试和 88 项社交浏览器检查通过；真实 libmpv 字幕检查、1 秒片源（range-delay=1、timeout=60）2x/3x 检查及候选 Tauri 原生/HLS、社交交互与关闭释放通过。新增回归同时保留旧实现失败证据。本机安装验收随后执行，上游尚未合并发布。

2026-10-12 第十三轮复核：依赖204新native实现重新生成patch与digest，不改变备用业务行为。

验证：333 项融合后端测试无跳过，215 项备用组合测试、19 套前端测试和 88 项社交浏览器检查通过；真实 libmpv 字幕检查、1 秒片源（range-delay=1、timeout=60）2x/3x 检查及候选 Tauri 原生/HLS、社交交互与关闭释放通过。新增回归同时保留旧实现失败证据。本机安装验收随后执行，上游尚未合并发布。

2026-10-12 第十五轮复核：4243146772/6776/6779：成功activate提交后释放父session引用；淘汰metadata同步移除对应foreground directory；control请求body必须是对象。

验证：344 项融合后端测试无跳过，220 项备用组合测试、19 套前端测试和 88 项社交浏览器检查通过；真实 libmpv 字幕检查、1 秒片源（range-delay=1、timeout=60）2x/3x 检查及候选 Tauri 原生/HLS、社交交互与关闭释放通过。新增回归同时保留旧实现失败证据。本机安装验收随后执行，上游尚未合并发布。
