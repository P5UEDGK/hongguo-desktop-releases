# 按剧名和季度整理完整视频缓存（集成材料）

新下载的完整MP4按 `stream-cache/剧名 [剧集ID]/季度/剧名_季度_第001集.mp4` 保存，便于在没有网络时用支持对应编码的本地播放器观看。同名剧用ID区分；优先使用明确季度元数据或剧名中的第N季，无法识别时保存到“未分季”。文件名会处理Windows非法字符及保留名。

`.video-library.json`只记录本地剧集身份、位置、大小和完整摘要，不保存媒体URL、令牌或账号。缺失、被修改或不完整的文件不算缓存命中；旧平铺缓存继续兼容，不自动迁移或删除。应用内离线列表尚未实现。

本PR单独提供视频库模块、测试和接入补丁，依赖[#246](https://github.com/waligoraamodio288-rgb/hongguo-desktop-releases/pull/246)的缓存设置及预缓存模块。先接入#246，再按[INTEGRATION.md](INTEGRATION.md)应用补丁和宿主接线；不重复包含其设置界面和预缓存实现。该发行仓库没有私有完整应用源码，合并材料不会更新已发布客户端。

## 内容

- `src/desktop_video_library.py`：安全命名、剧集身份、持久完整原片索引及校验。
- `patches/cache-settings-library.patch`：扩展#246的容量发布和手动清理owner，使其支持命名子目录与同一库实例。
- `tests/test_library.py`：15项命名、完整发布、持久查找、损坏/路径/重名保护、容量、清理和并发回归。

## 验证

接入#246后，从仓库根运行：

```powershell
pwsh -NoProfile -Command "git apply --check contributions/desktop-video-library/patches/cache-settings-library.patch"
pwsh -NoProfile -Command "git apply contributions/desktop-video-library/patches/cache-settings-library.patch"
pwsh -NoProfile -Command "python -I -B contributions/desktop-video-library/tests/run.py"
```

测试需要#246的Python依赖，并复用其tests目录中的取消异常fixture，不包含私有编码器。其它依赖源码位置可传`--cache-source <目录>`；未接入依赖时明确退出，不跳过用例。补丁已应用时不重复执行`git apply`。

本机已在#246设置基线上验证补丁应用和15项测试，并回归其29项设置/容量测试。实现与此前真实客户端验收源一致：第141集缓存读取、第142集真实下载、2302/2975帧完整解码、满额暂停、目录热切、手动清理及索引更新通过。运行态证据来自本机私有宿主，不随PR上传。回归曾遇上游非JSON响应，后续真实请求成功；应用内离线入口不在该验收范围。

回滚本材料及私有接线时，保留用户视频、设置和索引。未知、活动或链接内容继续保留。
