# 接入契约

先接入#246缓存设置和预缓存模块，再从仓库根应用`patches/cache-settings-library.patch`。补丁只修改已有`desktop_cache_budget.py`和`desktop_cache_settings.py`的责任owner，避免复制第二套容量或清理实现。将本材料的`src/desktop_video_library.py`复制到私有宿主相同backend模块目录；公开测试直接从本材料src导入该模块。

## 剧集登记与完整发布

每个`stream-cache`规范根只复用一个`VideoLibrary`实例。episode_loader获得`(meta, episodes)`后调用`register(series_id, meta, episodes)`，meta包含title和可选season_number/season，episodes包含正整数index与vid。宿主保留同一份命名上下文，供热切后的新下载根登记；不得因命名索引失败阻断尚未缓存的前台媒体加载。

下载时先捕获目标根，取得该根的库实例并登记命名上下文，以`target(vid)`取得安全输出位置。沿用同一媒体写锁，将实际输出路径加入宿主活跃下载protected集合，所有退出路径移除保护。调用`cache_complete_episode(..., before_publish=lambda staged, output: library.prepare_publish(vid, staged, output))`。完整下载、解密和封装校验通过后，先原子提交索引，再原子发布完整MP4；中途崩溃只留下无效记录，不产生可用的半集命中。

同名剧通过seriesId隔离，未知季度为未分季。索引不匹配、未知重名文件或目录链接均不得覆盖。容量仍由#246的CacheBudget递归计量与预留，满额暂停后台工作，不淘汰旧集；当前播放输出保护规则不变。

## 读取、清理与热切

source_loader按vid先调用当前库的`lookup`；命中后直接返回本地路径，不请求媒体信息或下载。未命中继续原流程，旧平铺完整原片保留兼容回退。此处是本地文件复用，不代表应用可以在完全断网时启动鉴权与离线页面。

手动清理调用`clean_video_cache(..., library=同一实例)`。protected包含当前源、转换源、活跃下载实际命名目标和持写锁路径。只清理索引身份及完整摘要一致、且不在使用中的命名文件；清理后移除索引记录，仅回收已空的两层命名目录。被修改、未知、活动和链接内容保留。

目录热切只影响之后捕获根的新请求。已有下载、转换与会话继续使用原根，旧会话按其固定output_root释放。禁止自动迁移旧视频、覆盖未知索引或按可变全局根删除旧输出。

## 验收与回滚

验证补丁能在#246设置基线上应用；运行本材料15项测试及#246的设置/容量测试，检查完整视频解码、重开后索引读取、未知内容与活动文件保护、满额暂停和热切旧会话释放。模块代码不变时可复用已有真实宿主证据；测试fixture不替代实际业务验收。

回滚宿主接线、本模块及容量/清理补丁。保留用户文件和索引，不移动正在使用的视频；旧版忽略索引并继续读取旧平铺缓存。应用内离线列表仅为后续候选。
