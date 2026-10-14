# 接入方式

有完整原生源码时，优先在原榜单数据层完整读取官网 loader 数据并映射 `episodeVids.length`，移除首页补数。下述本地服务方式已在实际安装版验证；最终只保留一条默认榜单链路。

## 后端

把 `src/desktop_rank.py` 放入宿主后端目录，在既有桌面服务中初始化一次：

```python
from desktop_rank import DesktopRank, make_router

rank = DesktopRank()
app.include_router(make_router(rank))
```

网络依赖为HTTPX异步客户端，运行依赖见 `requirements-test.txt`。不再接收同步 `H.http_request`：同步传输在响应头返回前无法可靠取消。默认保留TLS校验及HTTPX环境代理/CA设置，复用已验证的SSL信任上下文。第一页不发送 `page=1`，该参数在实测中返回无内容；后续页传入对应页码。

连接及单次socket读超时为5/15秒。服务复用一个网络事件循环及异步客户端，调用通过Future等待最多20秒，覆盖DNS、连接、状态行/响应头和正文读取；超时取消网络任务。请求路径不关闭事件循环，也不等待系统DNS线程结束，因此DNS停滞不会延长调用预算。系统解析器本身不能强制中止，返回后由执行器回收结果。

若宿主有独立代理或CA策略，通过 `DesktopRank(client_factory=...)` 注入HTTPX客户端工厂。工厂接收 `timeout`、`follow_redirects`，在服务的网络循环内创建一次异步客户端；使用宿主已验证的SSL上下文，不能关闭TLS验证或开启隐式重试。默认会读取环境代理，不能绕过宿主网络策略。工厂构造不得执行阻塞网络操作。

`make_router` 的lifespan在宿主关闭时调用 `rank.close()`，取消未完成任务并关闭客户端和网络循环。宿主必须执行FastAPI lifespan；不通过此路由接入时，由宿主显式关闭服务。不要在每次请求中创建或关闭 `DesktopRank`，也不要复用已经关闭的实例。

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
