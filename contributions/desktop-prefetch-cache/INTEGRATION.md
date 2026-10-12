# 接入契约

本材料需适配私有宿主源码。下列模块保持单一owner：配置归CacheSettings，容量归CacheBudget，调度归EpisodePrefetcher，可播产物归PlayableEpisodeCache，会话输出与当前播放归宿主HlsJobs。

## 目录与设置

`CacheSettings(data_dir, default_root)`的default_root应为实际用户应用数据目录，Windows通常位于`%APPDATA%/<app-id>`，不能写成本机开发配置；本应用使用`default_application_cache_root()`统一取得该默认根，与当前所选缓存目录独立。默认及任意选择位置统一使用专用`video-cache`，内部为`stream-cache`和`playback-sessions`；重复保存专用目录不会再次嵌套。`defaultDirectory`用于恢复默认按钮。

启动时调用`startup_paths(original_work_dir)`，接入原片loader、PlayableEpisodeCache和HlsJobs。会话临时目录有owner和进程标记；正常退出清理自身目录，强制结束后下次仅回收owner合法且PID已退出的旧目录，未知owner或活动进程保留。

`prepare_change(value)`在配置原子提交前创建并核验目标目录/cache，返回只交换已核验引用的apply回调。切换后新请求使用新目录，当前Job保存固定`output_root`，释放时按该根核对UUID子目录；不能按可变HlsJobs.root删除旧Job。新下载捕获自己的目标根，后台转换每个任务固定自己的cache对象；full_cache_ready动态引用当前cache。旧目录不自动搬动或删除。

设置API仅在托管本地桌面挂载`/desktop/cache-settings`、`/choose`、`/clear`；只对这三个精确路径豁免宿主媒体key中间件，router仍校验固定Tauri来源、非简单请求头和POST随机写令牌。CORS仅追加相应头，媒体及账号继续原鉴权。不得把令牌持久化或上报。

## 当前优先的预缓存

`EpisodePrefetcher(source_loader, episode_loader, cache_root, encoder=..., ahead=3, download_loader=..., source_status=..., background_guard=...)`：

- source_loader返回本地Path或渐进源；download_loader仅返回完整原片。剧集loader返回`(details, [{"index": 正整数, "vid": "8至24位数字"}, ...])`。
- 外部`all`通过validate_ahead变成None；API数字最少1，内部0禁用兼容保留。`reconfigure(ahead, optional_new_cache)`热调整有序等待队列，重置容量暂停状态，已开始下载按原路径有界结束。
- 创建Job后、启动worker前调用begin；加载源不占编码槽，HLS编码前调用before_work，finally所有成功/失败/取消路径调用finish。线程启动失败也须取消并finish释放占位。
- 原生模式只下载后续原片；HLS/copy先完成当前整集再串行转换后续。非零seek窗口完成后可补当前整集。copy必须传递video_mode，不静默改h264。暂停不release或close。
- 关闭调用close。渐进源的source_status必须使用宿主共享快照，并保持有界、幂等和线程安全。

## 满额暂停与完整剧集

对每个专用视频缓存根复用一个`CacheBudget(root, limit_bytes_callable)`；limit读取当前设置，默认10×1024³字节。usage计入根内原片、HLS、会话及未知普通文件，不通过删除旧集腾空间。链接或未知类型无法安全计量时拒绝后台预留，保留内容。

下载loader应按实际轨道取得完整字节数，未知尺寸转为PrefetchPaused；先复用已完整发布的原片。新下载调用`cache_complete_episode(budget, output, expected_bytes, fetch, convert)`。fetch按提供maximum限制响应，检查Content-Length和总实际长度，轮询check、取消和总时限；convert完整解密/封装并校验媒体。函数预留三份源大小加64KiB暂存空间，私有`.episode-*`中完成下载和转换，完整/容量检查通过后原子发布。宿主应使用同一媒体写锁，前台不得读取暂存半集。

background_guard(cache, source)为contextmanager，预留后台转换空间并yield容量检查函数；容量不足抛PrefetchPaused。调度器定期检查编码容量，并在完整HLS发布前复查；拒绝后保留有序队列，不记为媒体失败、不忙循环重试。`capacityPaused`用于诊断，用户清理、提高上限或切集/调整窗口后重试。

宿主设置`cache.evict=False`，`quota_bytes`随配置更新，`publish_check=budget.check`；前台仍可正常输出，但总额不足时不复制额外完整HLS缓存。后台store还传before_publish检查。当前播放必需的临时输出可能超额，禁止中断或截断；后台不继续扩充，待释放或手动清理。

PlayableEpisodeCache默认profile读取真实编码及预算模块，缓存键包含内容SHA256、策略及模式，产物逐文件验证SHA256与完整HLS标签。测试用profile_files不能替代生产策略文件。原有独立使用的2GiB/LRU默认兼容保留；本设置接线必须禁用淘汰并接入总容量门禁。

## 手动清理与前端

`clean_video_cache`仅供手动清理，未注册周期自动删除任务。宿主持Job生命周期锁与调度condition，快照当前源、后台源、活跃下载和持写锁路径作为protected；busy期间不驱逐HLS。未知文件、reparse point、含未知子文件的owner目录保留。当前会话输出以extra_bytes计入结果。清理后移除已删原片的sources/pending引用，再reconfigure当前窗口以尝试恢复预缓存。

前端片段的O/b适配React/jsx runtime，ge.validationStatus适配托管backend baseUrl。目录失焦、数字/勾选去抖自动保存，串行写入并以revision拒绝旧结果；导航离开时有效写入仍完成，取消目录选择不保存。归一化后的专用目录写回输入框，恢复默认只重置目录。勾选剩余集数后禁用数字输入，取消恢复指定值，默认3、最少1。

“缓存”标题旁显示单行提示“可先手动清理缓存再切换目录”，窄宽度省略，title保留全文；不在底部重复显示。集数右侧为“剩余集数　指定集数：［输入框］”，勾选后禁用输入。清理量大于0显示已清理X GB，0显示缓存已全部清理；小于0.01GB的正值显示<0.01 GB。反馈放入缓存上限行内的固定空间，移除底部独占的空白行；反馈保持18px单行、nowrap/ellipsis、title保留全文，空闲、非法输入、恢复原值、保存失败和清理结果均不得改变下一区块位置。

## 宿主验收与回滚

除两组公开fixture外，必须验证真实媒体完整解码、满额暂停及不自动淘汰、单集超额不启动、短/超长响应不发布、手动清理后恢复、前台播放不中断、热切旧会话读/释放和新输出目录、账号/媒体鉴权、取消/线程失败/退出释放。真实目录选择包括取消及中文路径。不能用状态或假字节宣称连续像素零黑屏。

回滚私有接线和这些模块，恢复原loader/encoder；仅按owner门禁处理缓存，保留用户原片及未知内容。发行包沿维护者自己的发布流程回滚。
