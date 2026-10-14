# 宿主接入

图片模块仅负责图片字节，详情签名、地址持久化、鉴权与收藏/历史由现有 owner 负责。将 src/desktop_posters.py 放到宿主 backend 模块目录。

```python
from desktop_posters import PosterCache
posters = PosterCache(cache_settings.active_root, fetch_image_bytes)
```

fetch_image_bytes 复用原图片下载/HEIC 转 JPEG 方法，返回 bytes；宿主设置有限超时和有界下载，不再从本函数触发搜索。每个活动设置缓存根只创建一个实例，同一桌面会话各页面共享。支持 JPEG/PNG/WEBP，单张最多 2 MiB、1600 万像素；图片域名白名单由 cover_url 统一验证。

## 详情地址与批量接口

本包沿用 [#246](https://github.com/waligoraamodio288-rgb/hongguo-desktop-releases/pull/246) 的 CacheSettings/视频热切 owner，不复制第二套配置或视频实现。patches/library-covers.patch 与 patches/server-posters.patch 是本机关系/服务 owner 的最小改动，适用于已有 backend/desktop_library.py 的宿主，不是可直接应用到当前发行仓库的补丁。接入相同前置模块后用 git apply --check 核对；不同宿主应实现以下契约，避免复制第二套图片缓存：

1. 同一关系数据库新增 poster_urls(series_id PRIMARY KEY, url NOT NULL)，旧 relations 六列不变。详情补齐时只保存 ID 精确匹配的 series_cover，经 cover_url 验证；已有合法关系不能被补图失败覆盖。WAL 本地读取不持远程查询的全局锁。
2. POST /desktop/library/covers 接收 {seriesIds:[字符串 ID],localOnly:布尔值}，最多 20 张，localOnly 默认 false。先对所有 ID 调用 posters.read；localOnly 为 true 时立即返回本地图及缺失 ID，不查详情、不下载。普通请求对剩余且 ready_to_fetch 的 ID 先通过 WAL 读取已有合法地址并立即下载，不获取关系查询锁；仅缺地址的 ID 后台批量补查，与已知地址下载共用最多六个工作线程。用动态 future 集合按完成顺序消费，详情完成后才加入对应下载，不能先等待整个详情批次。默认返回 {covers:{ID:dataURL},missing:[],localHits:n}；额外传 stream:true 时返回 application/x-ndjson，先发送本地命中，再按完成顺序逐张发送 {covers:{ID:dataURL},missing:[]}，每行最多一张图片。localOnly 为 true 时仍返回 JSON。非法 localOnly 或 stream 类型返回 400。
3. 地址下载失败后清除该条已失效地址，保留图片文件与有效关系；冷却过后可重新取得签名地址。没有地址也进入相同失败冷却，防止每张卡片反复查询。
4. 沿用桌面回环监听、可信 Origin、客户端标志和当前会话 requestToken。GET /desktop/library 取得会话 token；POST 验证 x-desktop-library-token。若普通 API key 中间件免除此路由，只免除精确路径并保留上述检查，不开放整个路径前缀。

本机接线为 LibraryRelations(application_data_root, provider, posters=posters)；关系数据库仍留在应用数据根，provider 复用已有签名 API。补丁包含上述后端方法及路由，不写原生收藏/历史表。默认 fetch 可以调用现有图片 owner，例如 lambda url: api_img(url).body；确认返回的是已转换图像 bytes，并保留原有网络限制。

## 设置目录切换

启动时图片根必须取 cache_settings.active_root。若旧 application_data_root/poster-cache-v1 存在，创建只用于读取的旧 PosterCache，并调用 posters.seed_from(旧实例)；这只复用验证通过的本地图片，不请求上游，不移动数据库或删除旧文件。

在现有视频目录 prepare_change 回调内合并图片准备，不能用新的回调覆盖视频接线：先调用 candidate = posters.prepare_directory(value['directory'])，它将已有有效图片复制到候选根但不激活。原子保存设置成功后，在原有 apply 内依次调用 posters.activate(candidate)、切换当前 posters 引用，并将 library.posters 指向 candidate。新旧实例共享下载锁/冷却；迟到的下载会向已激活新根发布。不能在 prepare 阶段激活，失败保存必须仍消费旧根。

server-posters.patch 包含这部分接线。cache-settings-label.patch 与 frontend-settings-label.patch 仅修正现有选择窗口及标签名称，分别应用到已有后端设置模块及前端可读设置实现；前端源码路径不同则仅迁入同一处文字。保留已有视频路径规范化（video-cache 子目录）、容量规则与视频清理行为，图片根明确为最终设置 directory/poster-cache-v1。此处不扩大为移动收藏/历史或日志。

## 公共前端入口

加载 src/frontend-posters.js，替换已有公共 seriesCover 方法，使所有卡片经过同一入口。request 为宿主现有受保护请求函数，负责可信 origin、会话 token 和有限超时；客户端不可保存过期 token。所有有效剧集 ID 的封面组件均走此入口，包括发现、排行榜、探索、搜索、推荐、收藏、历史、合集和单季。不能按 source 或远程地址是否为占位符决定是否走缓存。头像、二维码等非剧集图片不接入此接口。

```javascript
api.seriesCover = desktopCreatePosterLoader(async (seriesIds, options, onProgress) => {
  await desktopLibrary.load();
  return desktopLibrary.request('/covers', {seriesIds, ...options, stream:!!onProgress}, onProgress);
});
```

宿主 request 收到成功响应后，按 Content-Type 分流；onProgress 存在且为 NDJSON 时调用本包的读取器，否则保留原 JSON 处理。保持超时覆盖整个读取过程。

```javascript
if (onProgress && response.headers.get('content-type')?.includes('application/x-ndjson')) {
  return await desktopReadPosterStream(response, onProgress);
}
return await response.json();
```

读取器支持跨网络块的行与 UTF-8 字符，每帧验证后立即通知对应卡片。已完成的图片不等整批结束；后来某张失败或流中断，也不能撤回已显示图片。图片经原子保存后再返回，下次读取直接复用磁盘。

同一 ID 的在途 promise 合并。本地读取和补下载各自最多两批并行，每批最多 20 张。先发 localOnly 请求，本地图立即交给对应卡片，仅缺失 ID 进入补下载队列。即使两个补下载请求都阻塞，后来进入页面的缓存图仍可读取。

保留现有可视区域判断和短期内存缓存；移除挡在此适配器前面的旧六卡片限流，HTTP 并发统一由本适配器负责。否则六张缺图会占住旧队列，后续本地图仍无法进入读取阶段。内存淘汰后仍读磁盘，不能回退到原生 get_series_cover 的网络恢复链。该适配器不修改卡片外观、归组或播放行为。

必须检查最终打包资源中的公共 seriesCover 赋值已经执行；只有 desktopCreatePosterLoader 函数存在不足以证明接线生效。后续修改其他片单模块时也要保留此赋值。

## 验收与恢复

先通过公开测试，再验证宿主已有图片无详情/图片上游请求、冷缺图补齐一次、切页/进入合集/返回/重启继续命中、坏图仅修复本条、签名地址过期后冷却恢复，以及合法 token、错误 Origin 和缺失 token。补充阻塞回归：一批混有本地图和缺图时本地图先显示；六张缺图等待网络时，后来显示的本地图仍能加载；同批一张完成、一张仍下载时，完成的图片立即显示，剩余图片完成后独立显示。分别验证各封面页面以及无 source、validationApi、appImport 来源。对实际安装包统计 get_series_cover 调用必须为零，避免源码已接线但运行包漏接。核对原收藏/历史表未变，并确认目录映射后仍复用既有原生文件，并验证设置切换、保存失败及在途下载只向已提交的新根发布。

本机补丁应用、上述业务、鉴权及旧 schema 迁移已有对应测试和真实运行证据。公开 fixture 不能替代维护者私有工程的接入/发布验收。撤回补丁和公共入口接线可恢复旧路径，用户图片和新增地址表保留，不通过清缓存回滚。


### 缺地址阻塞回归

`tests/test_host_covers.py` 使用人工 ID 和图片，验证已知地址下载不等无关详情锁、同批已知地址先于缺地址返回。它需要已应用本包补丁的宿主 `desktop_library.py`，不会连接真实上游。未指定宿主路径时两项显式跳过，不能当作集成验收通过：

```pwsh
$env:HONGGUO_HOST_BACKEND = '<已应用补丁的宿主 backend 绝对路径>'
pwsh -NoProfile -Command "python -I -B contributions/desktop-poster-cache/tests/run.py"
```

本机在补丁应用后的宿主副本上执行这两项测试；原实现两项均超时，修复后通过。本轮本机完整宿主的图片/关系测试共26项通过。安装包UI与真实HTTP结果以本轮验收记录为准，公开测试不替代客户端发布验证。
