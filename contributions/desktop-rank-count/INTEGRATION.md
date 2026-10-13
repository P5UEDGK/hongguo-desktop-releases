# 接入方式

有完整原生源码时，优先在原榜单数据层完整读取官网 loader 数据并映射 `episodeVids.length`，移除首页补数。下述本地服务方式已在实际安装版验证；最终只保留一条默认榜单链路。

## 后端

把 `src/desktop_rank.py` 放入宿主后端目录，在既有桌面服务中初始化一次：

```python
from desktop_rank import DesktopRank, upstream_page, make_router

rank = DesktopRank(lambda board, page: upstream_page(board, page, H.http_request))
app.include_router(make_router(rank))
```

宿主 `H.http_request` 需支持 requests 的 `params`、`timeout`、`stream`、`allow_redirects` 及响应上下文管理；响应还须提供可中断读取的 `raw.shutdown()`（测试使用requests及urllib3 2.7）。沿用既有连接池、TLS验证和代理策略，禁用隐式重试。不支持限时中断的传输会明确报错，不能静默降级为无限等待。第一页不发送 `page=1`，该参数在实测中返回无内容；后续页传入对应页码。

连接及单次socket读超时仍为5/15秒，另设20秒总读取预算，从调用上游前计时。收到响应头后按剩余预算设置定时器，直接中止底层读取，避免 `iter_content` 等待凑满一块数据时永不返回。正常结束先关闭取消门禁，再归还连接池，避免定时器误伤已复用的连接。

读取的是官网榜单自身的 `__loader=rank_<route>/page&__ssrDirect=true` 响应，非详情接口。响应可能直接返回JSON，也可能先给 `__deferred_promise:content`，再用 `data:` 块提供完整 `content`。仅在同一响应完整结束且结构通过验证后计算集数；缺块不得转查详情或猜测。

后端只监听loopback。GET `/desktop/rank?board=hot&page=1&refresh=false` 返回卡片数组。board为hot/real/comic/ai，page为1至5，refresh为布尔值。按榜单与页码缓存30分钟；重叠加载共享同一个in-flight结果或异常，失败不会让等待者依次重新访问上游。下一独立调用可重新加载，显式刷新失败仍保留原成功缓存。

沿用宿主认证与CORS规则，不能全局关闭认证。此路由自行检查本机客户端地址、Origin和 `x-desktop-rank-client: 1`。允许来源 `http://tauri.localhost`、`tauri://localhost`，CORS增加GET和该请求头；仅在受管理桌面服务上下文中接入。不要对外暴露本地服务。

## 前端

```js
import {createDesktopRank} from './frontend-rank.mjs';
api.rank = createDesktopRank(api);
// 保留原来的卡片、封面缓存、分页和刷新逻辑。
```

依赖仅为 `api.validationStatus(): Promise<{baseUrl}>`，返回受管理服务的 `http://127.0.0.1:端口` 根地址。调用签名保持 `api.rank(board, refresh=false, page=1)`。每次调用只发一个本地GET，不查询详情，也不另外创建首页补数或后台补查任务。

新入口不读取旧原生榜单缓存。宿主若有持久化片单预览缓存，应刷新对应榜单快照，避免旧0集预览持续展示；不要清除收藏、历史和其他缓存。

## 验收与回滚

构建后核对四种榜单、第二页、540/162/150集样本、刷新、服务重启、失败提示及原封面加载。抓取榜单操作的请求，确认每个新页仅一次榜单请求且没有首页/详情补数。

回滚时恢复原 `api.rank`，移除新增路由及其独有CORS头，再删除两个模块并重新构建。模块不写持久数据库，无需迁移数据。二进制补丁与本机备份不属于这份公开贡献。
