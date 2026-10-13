# HEVC 原生与渐进播放接入代码

HEVC 先实际尝试硬解，失败后只重试一次软解；软解失败或持续跟不上再回退 H.264。网络慢进入缓冲，源不可读提示重试，不把下载失败判断为解码失败。无需等整集下载或转码：libmpv 读取鉴权 Range 输入，H.264 回退也在首批完整 HLS 片段就绪后播放。音频由原生内核解码和变速，使用 Windows 默认设备、WASAPI 共享输出。

这是发行仓库的接入材料，**合并本 PR 不会改变已发布应用**。需要维护者移入私有源码并发布；不附完整应用、EXE、原 bundle、签名/账号协议、真实视频或凭证。与 #187 配合下载后3集；暂停整集预加载由独立补丁提供，基线仍是约12秒预读。

## 模块与接线

`desktop_stream.py` 负责有界 Range、取消、源校验和 CENC 按包解密输入；`desktop_native.py` 负责 Windows 子窗口、默认音频、倍速、硬软解与输入转发；`desktop_native_engine.py` 复用同线程的 mpv、输出设备和子窗口，最多两个资源槽，空闲60秒销毁；`desktop_hls_service.py` 负责鉴权会话和释放；`desktop_codec.py` 描述真实编解码轨道并提供可用时的 HLS 包复制。`desktop_hls.py`/`desktop_hls_budget.py` 是回退编码参考实现，已有编码器可按契约适配；其中 AUTO 解码与 #188 相同，不需要重复打补丁。

宿主只在后台解析媒体，返回已完成本地 Path 或 `ProgressiveSource(url, request=authorized_request, identity=stable_id, key=authorized_content_key)`。本包不实现上游 API 或密钥获取。复用完整原片前必须确认写入已完成；不能把后台正在写的非空文件当缓存，也不要等待旧下载锁才能启动新选的一集。Range 内存16MiB、原生包内存32MiB；第三方临时磁盘缓存由后续暂停补丁开启。

用 `NativeHost(parent_pid=owned_desktop_pid, dll_path=verified_dll)` 创建原生宿主，交给 `HlsJobs(..., native=native)`；`make_router` 必须使用宿主会话鉴权并仅监听本机回环。source接口、控制、status、DELETE都属于该job。所有成功、失败、切集、超时和退出路径必须释放原生音频/窗口、Range源及会话目录。不得接收客户端指定进程、HWND、文件、设备、mpv命令或解密密钥。

需共同接入 #187 的两个模块。渐进当前源使用 `source_loader`；后三集使用完整文件 `download_loader`，并传 `source_status=desktop_stream.source_progress`。source加载、描述轨道及native模式选择都发生在编码槽之前；原生播放不占编码槽。只有copy/h264编码前取得槽，finally始终调用finish，取消旧会话先于启动新会话。

前端提供 `desktopNativePlayback` 和 `desktopCodecHls` 两个入口。宿主需提供 `w0(url)`（返回受信回环origin、会话url和key）、`desktopLegacyHls` 与 `ek`（分别为既有普通/窗口HLS控制器，支持注入codecFetch），以及已有media、callbacks和preparation契约。将原React播放入口接到 `desktopNativePlayback`，不直接拼接/覆盖发行EXE。依然保留原按钮、快捷键、全屏、小窗、选集及连播；native故障回退保留位置、暂停、倍速和音量。不要把浏览器HEVC探测结果当机器原生硬解结论。

`frontend-native.js` 持续轮询同一会话，暴露真实buffer范围；配合 #189 更新原灰条，暂停不停止轮询。更新或关闭后忽略旧请求回执。HE-AACv2限制的是HLS包复制资格，不影响已识别HEVC进入原生音视频解码。

原生输入转发同时挂在外层视频容器与渲染子窗口。Windows 命中外层 Static 时，单击仍转到宿主 WebView 的原暂停／继续处理器；重复接入不重复安装 hook，退出时统一恢复。实际窗口验证应先通过 WindowFromPoint 确认鼠标命中目标，避免直接向已知子窗口发送消息而漏掉容器路径。

## 验证

Windows x64、Python3.11、Node18+。安装 `requirements-test.txt`；将 #187 的贡献目录作为明确依赖提供，测试会在临时目录拼装模块，不改安装包。

```pwsh
pwsh -NoProfile -Command "python -I contributions/desktop-native-playback/tests/run.py --prefetch-package <prefetch-contribution-dir>"
pwsh -NoProfile -Command "node contributions/desktop-native-playback/tests/test_frontend.cjs"
```

Node覆盖轨道协商、位置/暂停/倍速恢复、只回退一次、旧回执与源失败不误转码。新增真实合成Opus输入转AAC-LC、seek共同时间原点、取消和预算回归；已有AAC继续直拷。新增两个确定性取消竞争测试，防止DELETE后prepare注册残留会话。公开fixture是合成媒体及公开测试密钥，不含提供方视频。硬解失败由受控驱动测试，未人为破坏真实GPU。

先前实际Tauri/WebView2已验证本机硬解dxva2-copy、强制软解、2x/3x、默认音频、首帧早于整片下载、缓冲恢复、暂停seek、切集、EOF连播及一次H.264回退。真实CENC输入的解码帧与已有明文一致。以上是本机接线结果；公开模块测试不能代替维护者私有源码与真实窗口验收。A-V数字来自内核时钟，没有物理声画、跨设备CPU/温度/功耗结论。

`src/libmpv-source.json` 记录测试用DLL的第三方来源；DLL不随本PR分发。当前适配固定SHA256 `34780746a0273a4fcae42dfe262a28984a426a238939474afd3a1561b450bbef`。维护者应核验来源及匹配API，按实际mpv/FFmpeg构建履行第三方许可与对应源码义务；升级后重新验收，不能仅改摘要绕过核验。[mpv手册](https://mpv.io/manual/stable/)说明解码与缓存选项。

[Issue对应关系与关闭条件](ISSUES.md)。回滚时在私有源码revert播放接线和新增模块，恢复原HLS入口；保留用户原片与观看记录，不直接删除未知缓存。材料提交、应用接入、发布与Issue验收分别记录。

复审修复：max_jobs限制总会话数；max_workers只限制copy/H.264实际编码，native准备不占编码槽。HlsJobs在有会话时自行启动回收线程，无后续请求也按idle_seconds清理，宿主shutdown调用jobs.close()。Range连接超时3秒、无数据读超时10秒，Timeout/ConnectionError最多尝试3次；每次重新校验Range/validator并丢弃失败的部分块，取消在读取和退避间检查。协议错误不重试；重试耗尽才报告source-read。[Requests超时说明](https://requests.readthedocs.io/en/stable/user/advanced/#timeouts)。新增真实3.2秒HTTP停顿恢复、重试关闭响应、取消、编码并发和无请求到期回归。

第二轮复审：截断 Range 丢弃后有界重试；弱 ETag 仅比较身份，不发送 If-Range；未出首帧的 EOF 先重试软件解码，再明确失败；EOF 后 seek 清除 ended，恢复播放保留所选目标。

修复最新原生回执：描述与fallback共用AAC-LC资格判定，其余AAC profile转AAC-LC；无首帧EOF软件重试从原请求位置开始；close如线程仍存活返回pending，host/job/output保留，DELETE202，前端有界等待204才启动HLS，取消会话由reaper继续清理。新增真实AAC重编码及生命周期回归。

显示掉帧与解码掉帧分开统计。显示丢帧不再触发软解，硬解时仅A-V偏差也不单独触发重载。libmpv按连续3帧解码错误回退软件；应用仅保留无首帧/播放停滞的一次软件恢复和软件持续跟不上的最终H264回退。音频/输入输出故障不触发软件重载；seek、倍速、音量与暂停保持。

同一NativeHost内，按codec/profile/level、像素格式、宽高缓存实际出帧的硬解方式（最多64项）；后续同格式直接选择已验证方式，每片仍验证实际首帧。只缓存成功，不永久记录失败；内核自动回退或应用重试时丢弃该选择。重启清空缓存。强制软件测试仍覆盖缓存；D3D11渲染适配器保持自动，不强制独显，不实现超分。

切集时不再逐集创建并销毁 mpv。每次仍重新加载媒体，重置位置、音量、暂停、解密参数和请求头，等待本集首帧；失败的实例退役，退出会等待实际释放。最多两个槽供当前集和备用集使用。

本轮 Python 49 项：48通过、1项可选本地HEVC测试跳过；Node协商/暂停/回退回归通过。隔离真实mpv依次播放HEVC、HEVC、CENC HEVC、不同分辨率无音轨H264、HEVC，五次共用一个实例，后四次初始化耗时为0。单轮合成输入对照中，非首次首帧就绪为141–422ms，逐集新建为1312–1610ms。这是内部首帧就绪时间，不能当成正式版实际画面空档或跨设备性能承诺。

协商中用户暂停会保留到原生或HLS控制器；已经选择copy/h264的会话由既有HLS接管；源读取失败不启动无效转码；shutdown时未结束的原生线程继续由回收器跟踪。

HLS准备中保留暂停与最新倍速；有音轨时首帧ready同时要求已解码音轨和WASAPI输出。记录已接受但未ACK控制供回滚。Python51项50通过1跳过，Node通过。 本次修复对应已收到的审查意见；尚无连续像素证据可证明零黑屏。

HLS准备中的播放器自动暂停不改变用户意图；显式暂停调用仍立即记录，包含媒体本来已经暂停的情况。Node覆盖启动事件内暂停和后续用户暂停。

真实HLS接线复测进一步确认：旧控制器构造及释放时的同步暂停也由内部转换保护，不能覆盖用户意图。对应Node夹具按旧控制器实际调用顺序增加构造时pause。

本次回执修复与验证：native→HLS等待DELETE202释放期间继续追踪显式暂停/播放，交给HLS前移除追踪；HLS准备中显式play覆盖旧pause，控制器内部启动事件仍受保护。Node新增两项回归通过。到期回收测试先准备产物再设置过期时刻，消除负载下夹具提前过期的竞争。Python51项50通过1可选跳过。

真实HLS移动图复测补充：显式ready play清除启动暂停期限，onReady同一调用栈的旧控制器自动play单独标为内部行为；已排队暂停执行前重查最新播放意图。Node在旧HEAD复现失败，新实现通过。

画面单击修复：输入桥同时接管外层 STATIC 与渲染子窗口，外层 WM_NCHITTEST 返回 HTCLIENT，避免默认 HTTRANSPARENT 让真实点击穿透。事件仍转交宿主已有 WebView 播放处理。Python 53 项中 52 通过、1 项可选样例跳过；真实 Windows SendInput 验证暂停、继续及窗口模式通过，桌面社交组合回归 81 项通过。

控制栏自动显隐修复：移除原生激活时强制控制栏永久显示的样式及其节点，沿用宿主已有的鼠标、暂停与键盘聚焦状态。Node 回归通过；候选 WebView2 91 项通过，覆盖真实鼠标移动显示、播放静止后隐藏、暂停显示、键盘聚焦，以及普通和播放窗口的置顶状态。社交布局补丁需使用 #210 同步适配后的版本。


2026-10-13解码策略修复：复用现有[mpv硬解与回退选项](https://mpv.io/manual/stable/#options-hwdec-software-fallback)，没有移植其它播放器代码。参考[VLC的格式与硬件上下文选择](https://github.com/videolan/vlc/blob/master/modules/codec/avcodec/video.c)，按片源格式区分成功选择，不将显示丢帧当硬解失败。公开包Python62项中61通过、1可选样例跳过；新增9项策略回归。安装候选80项中79通过、1跳过。本机离屏HEVC/HE-AACv2在2x/3x回读dxva2-copy，同格式重开命中硬解方式缓存并复用引擎；强制软解也通过。同步结果来自mpv时钟、音频为静音共享WASAPI，未做物理声画测量，也未据此声称所有机器硬解一定更省资源。
