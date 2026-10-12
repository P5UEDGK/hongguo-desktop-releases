# HEVC 原生与渐进播放接入代码

HEVC 先实际尝试硬解，失败后只重试一次软解；软解失败或持续跟不上再回退 H.264。网络慢进入缓冲，源不可读提示重试，不把下载失败判断为解码失败。无需等整集下载或转码：libmpv 读取鉴权 Range 输入，H.264 回退也在首批完整 HLS 片段就绪后播放。音频由原生内核解码和变速，使用 Windows 默认设备、WASAPI 共享输出。

这是发行仓库的接入材料，**合并本 PR 不会改变已发布应用**。需要维护者移入私有源码并发布；不附完整应用、EXE、原 bundle、签名/账号协议、真实视频或凭证。与 #187 配合下载后3集；暂停整集预加载由独立补丁提供，基线仍是约12秒预读。

## 模块与接线

`desktop_stream.py` 负责有界 Range、取消、源校验和 CENC 按包解密输入；`desktop_native.py` 负责 Windows 子窗口、默认音频、倍速、硬软解与输入转发；`desktop_native_engine.py` 复用同线程的 mpv、输出设备和子窗口，最多两个资源槽，空闲60秒销毁；`desktop_hls_service.py` 负责鉴权会话和释放；`desktop_codec.py` 描述真实编解码轨道并提供可用时的 HLS 包复制。`desktop_hls.py`/`desktop_hls_budget.py` 是回退编码参考实现，已有编码器可按契约适配；其中 AUTO 解码与 #188 相同，不需要重复打补丁。

宿主只在后台解析媒体，返回已完成本地 Path 或 `ProgressiveSource(url, request=authorized_request, identity=stable_id, key=authorized_content_key)`。本包不实现上游 API 或密钥获取。复用完整原片前必须确认写入已完成；不能把后台正在写的非空文件当缓存，也不要等待旧下载锁才能启动新选的一集。Range 内存16MiB、原生包内存32MiB；第三方临时磁盘缓存由后续暂停补丁开启。

源缺少 ETag 和 Last-Modified 时，不拼接多次 Range 响应：丢弃探测块，从单次完整响应写入临时文件，再供同一源的 reader 读取。文件最多为已校验的输入长度（上限2GiB），取消、短读或超长响应会丢弃未完成文件。这种源需要先完成下载，不能承诺渐进首帧。宿主若长期保留 source，最后一个使用者退出后调用 `source.close()`；共享源仍有 reader/job 时不能提前关闭。

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
pwsh -NoProfile -Command "node contributions/desktop-native-playback/tests/test_native_geometry.cjs"
```

Node覆盖轨道协商、位置/暂停/倍速恢复、只回退一次、旧回执与源失败不误转码。新增真实合成Opus输入转AAC-LC、seek共同时间原点、取消和预算回归；已有AAC继续直拷。新增两个确定性取消竞争测试，防止DELETE后prepare注册残留会话。公开fixture是合成媒体及公开测试密钥，不含提供方视频。硬解失败由受控驱动测试，未人为破坏真实GPU。

先前实际Tauri/WebView2已验证本机硬解dxva2-copy、强制软解、2x/3x、默认音频、首帧早于整片下载、缓冲恢复、暂停seek、切集、EOF连播及一次H.264回退。真实CENC输入的解码帧与已有明文一致。以上是本机接线结果；公开模块测试不能代替维护者私有源码与真实窗口验收。A-V数字来自内核时钟，没有物理声画、跨设备CPU/温度/功耗结论。

`src/libmpv-source.json` 记录测试用DLL的第三方来源；DLL不随本PR分发。当前适配固定SHA256 `34780746a0273a4fcae42dfe262a28984a426a238939474afd3a1561b450bbef`。维护者应核验来源及匹配API，按实际mpv/FFmpeg构建履行第三方许可与对应源码义务；升级后重新验收，不能仅改摘要绕过核验。[mpv手册](https://mpv.io/manual/stable/)说明解码与缓存选项。

[Issue对应关系与关闭条件](ISSUES.md)。回滚时在私有源码revert播放接线和新增模块，恢复原HLS入口；保留用户原片与观看记录，不直接删除未知缓存。材料提交、应用接入、发布与Issue验收分别记录。

复审修复：max_jobs限制总会话数；max_workers只限制copy/H.264实际编码，native准备不占编码槽。HlsJobs在有会话时自行启动回收线程，无后续请求也按idle_seconds清理，宿主shutdown调用jobs.close()。Range连接超时3秒、无数据读超时10秒，Timeout/ConnectionError最多尝试3次；每次重新校验Range/validator并丢弃失败的部分块，取消在读取和退避间检查。协议错误不重试；重试耗尽才报告source-read。[Requests超时说明](https://requests.readthedocs.io/en/stable/user/advanced/#timeouts)。新增真实3.2秒HTTP停顿恢复、重试关闭响应、取消、编码并发和无请求到期回归。

第二轮复审：截断 Range 丢弃后有界重试；弱 ETag 仅比较身份，不发送 If-Range；未出首帧的 EOF 先重试软件解码，再明确失败；EOF 后 seek 清除 ended，恢复播放保留所选目标。

修复最新原生回执：描述与fallback共用AAC-LC资格判定，其余AAC profile转AAC-LC；无首帧EOF软件重试从原请求位置开始；close如线程仍存活返回pending，host/job/output保留，DELETE202，前端有界等待204才启动HLS，取消会话由reaper继续清理。新增真实AAC重编码及生命周期回归。

连续至少2秒丢失不少于期望帧数50%且最近仍增长，视为解码不稳定；阈值随帧率和倍速变化，暂停/缓冲/seek重置。先一次软件尝试，软件仍不稳定才H264。seek中忽略旧EOF，未出帧重试保留最新请求位置。

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

本轮继续修复：宿主 `onReady` 内显式播放生效；copy watchdog 使用本轮解码帧或帧回调，旧画面的尺寸和计数不能证明新视频已显示。无首帧超时重试保留请求位置，协商中向前面的时间点 seek 会释放不覆盖该位置的 HLS 窗口。PCM 等非直拷音频按 AAC 输出码率规划预算，单/双声道布局规范化。copy 与编码输出均由 I/O sink 在每次写盘前限制总预算，包含超大单包及 trailer；失败不产生完整标记。

原生表面通过 `desktopNativeSurfaceRect` 读取实际控制栏位置和可见状态，隐藏后填满媒体区域；观察尺寸、class/style/hidden 与 transitionend，恢复播放或全屏时沿用同一算法。#213 和 #210 的下游补丁需同步适配本轮基线，避免覆盖此几何算法。

本轮公开 Python 61 项均有通过记录（默认全量中1项 HEVC 可选测试另以已有自有素材补测通过），两组 Node 回归通过；五个缺陷输入和前端回归在旧 HEAD 失败。新改动尚待完整下游组合、本机候选和安装验证，不能据此宣称发行版已修复。


本轮窗口与交接复审：前端使用当前 Tauri 窗口的物理客户区坐标，后端只匹配同一宿主 PID 的唯一客户区，支持 owned 播放窗口，不接收任意 HWND；未提供上下文且存在多个候选窗口时拒绝猜测。旧会话慢退出时，新准备在可取消队列等待，关闭会话不占宿主状态锁，也不误报解码失败。首轮 onReady 同步入队的 seek 等待实际控制 revision，期间保留请求位置；静音、音量、倍速和 seek 先于解除暂停，软件重试沿用相同顺序。冷启动在已知时长后检查保存的片尾进度，越界时先释放旧 job，再创建零起点会话，保留协商期间的新 seek。


未知时长续播与窗口快照回退：保存位置为非零，但容器时长未知、越界或准备失败码为 start-position 时，先释放该会话，再用零起点重建，保留协商期间用户另行提交的 seek。窗口在物理坐标查询后移动或缩放造成 native mode 返回400时，改走既有 HLS 协商路径。三个旧回放均失败；当前全部前端回归通过，Python 模块本轮未改。完整待机174项、Chrome84项及实际libmpv字幕检查通过；本机候选与安装仍待完成。


本轮审查回归（2026-10-12，第四批）：4242306703/6707：连续无输出单独计时并ready重置；协商期间发生新seek时未知时长旧job仍归零重建，保留新意图。

完整缓存恢复可返回 windowOrigin=0。窗口HLS宿主的 status 起点守卫须调用 desktopAcceptWindowOrigin(status, requestedStart)，替代单独 origin<requestedStart 的拒绝；连续窗口的 origin 不变检查仍保留。只有 complete、playlistReady 且 playableRange 精确覆盖 [0,duration] 的零起点响应才能例外通过。


本轮第六批审查（2026-10-12）：4242527452/7457/7461：copy要求smooth，曾就绪后的输出丢失不被持续读取掩盖，预算按磁盘extent而非累计清单重写收费；保留未提交真实origin helper回归。

2026-10-12 追加复核：4242725623/5627：无原生DLL的未知时长续播也先验证零起点，保留待应用seek；首帧前play控制包含当前倍速、音量和静音。

2026-10-12 第十一轮复核：4242926461/6467/6470/6473：未知时长copy与迟发native解码失败从零降级并保留seek；退出等待持续捕获currentTime，瞬态DELETE错误在原截止内重试。

2026-10-12 第十三轮复核：4243068989/8994/8999/9007/9015：弱或无效validator固定完整响应；AAC转码固定码率预算；END_FILE首帧前重试保留起点；排除VO倍速丢帧；初始native POST有界且可取消。

2026-10-12 第十六轮复核：4243213170/3173/3176：几何IPC失败降级；创建请求取消回收含先取消后创建；奇数尺寸编码保持显示比例。

2026-10-12 第十七轮复核：依赖#187：Job提供owner绑定source_loader，源线程优先调用该callback；保留原普通source_loader契约。

2026-10-12 第十八轮复核：4243361641/1646：VO掉帧按速率折扣仍识别正常速率过载；强制H264降级释放未转移preparation。

2026-10-12 第十九轮复核：4243434997/5002：成功源读取清理过往network_failed；直接HLS未知duration非零续播start-position失败回零并保持pending seek。

2026-10-12 第二十一轮复核：4243502886/2893/2897/2900：输出目录删除失败明确pending；Last-Modified仅在响应日期足够分离时作强校验；掉帧扣除显示刷新容量限制；重新枚举并挂接重建的原生子窗口。 启动预读目标收紧至10秒以覆盖包级预读余量，实测未完成缓存8.5秒；暂停补丁不再在EOF清除历史网络失败。

2026-10-12 第二十二轮复核：4243543195/3198/3202：直接HLS已知无效续播回零丢弃越界seek；原生窗口跟随CSS显隐；未知实际码率不认证copy。

2026-10-12 第二十三轮复核：4243668889/8892：mode响应丢失后回读已提交模式；输入回调读取当前WebView HWND，不保留旧目标；显式seek意图传入HLS续播契约。

2026-10-12 第二十四轮复核：4243750629/0634：codec模式协商限时并回读丢失响应；首次布局恢复同步记忆音量、静音及倍速。

2026-10-12 第二十五轮复核：4243806211/6216/6218：初始协商拦截currentTime写入；packet-copy仅接受安全原sample-entry；保留负child坐标并依赖Win32父客户区裁剪，完全离屏隐藏。

2026-10-12 第二十六轮复核：4243885385/5389/5392/5393/5397：内部恢复seek保留播放意图；缓存命中不能抹去网络失败；直接HLS创建使用token并取消丢失响应任务；未提交模式重试或降级。

验证：410项融合后端无跳过、32套播放器前端、259项公开备用组合和132项暂停补丁检查通过（后两项各1项可选片源跳过）。12项冻结前版反例失败、当前通过；真实长片暂停预加载、6套评论及88项浏览器通过；候选Tauri原生/HLS播放、负坐标裁剪、全离屏暂停及退出释放通过。隐藏activate播放意图增强测试冻结前版亦通过，未改生产逻辑。本机安装验收随后执行，上游尚未合并发布。
