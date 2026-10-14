# 宿主接入

优先在完整源码的原生搜索请求层修正 GET query，并保留既有分页和结果契约。下面提供本机已经验证的本地服务接入方式，供尚不能改原生模块时使用；后续迁回原生层后删除本地传输适配，避免两条搜索链并存。

## 后端

把 `src/desktop_search.py` 放入宿主后端模块目录，在已有桌面服务中初始化一次：

```python
from desktop_search import DesktopSearch, upstream_get, make_router

search = DesktopSearch(lambda params: upstream_get(params, H.http_request))
app.include_router(make_router(search))
```

`H.http_request(method, url, **kwargs)` 必须支持 requests 的 `params`、`timeout`、`stream` 及响应上下文管理；沿用宿主会话、TLS验证和网络策略，不另建代理绕行。查询版本字段沿用故障版本参数，不作为服务端稳定契约保证。

后端仅监听 loopback。保留已有 CORS 来源和请求头；允许 `http://tauri.localhost`、`tauri://localhost`，方法 GET/POST，增加 `content-type`、`x-desktop-search-client`、`x-desktop-search-token`。若宿主还有全局认证中间件，应沿用既有桌面服务规则接入，不能移除认证。

| 路由 | 输入与结果 |
| --- | --- |
| GET `/desktop/search` | 获取本进程 `requestToken`；校验loopback、Origin和桌面标志 |
| POST `/desktop/search` | `{query, page, mode}`；额外校验令牌；mode为short/manju |

POST成功返回 `{items, page, hasMore, mode, source, coverage, retrievedCount}`。`coverage: "unverified"` 不代表全集完整；失败返回502及可显示的 `detail`。结果ID始终为字符串。模块不写用户数据库。

## 前端及队列顺序

把 `src/frontend-search.mjs` 放入前端模块目录。替换传输必须发生在共享队列捕获原始方法之前，并且只初始化一次：

```js
import {createDesktopNovelfmSearch} from './frontend-search.mjs';

api.searchNovelfm = createDesktopNovelfmSearch(api);
// 然后执行现有共享队列初始化；例如 #304 的 createLibraryUI({..., api})。
// 最后挂载应用。
```

依赖仅为 `api.validationStatus(): Promise<{baseUrl}>`，返回受信本机服务的 `http://127.0.0.1:端口` 根地址。搜索调用保持 `api.searchNovelfm(query, page, mode)`；页码从1开始。工厂本身只处理传输，不创建第二条调度队列。官网联想入口保持原用途。

若队列已初始化，其保存的原始绑定仍可能指向旧原生方法；应调整初始化顺序后重启，不能把队列内的请求再次送回队列。普通搜索、补季和下一季查找均使用同一修复后的传输。

每条 `source: "novelfm"` 是宿主封面缓存识别所需字段。接收结果后继续使用既有卡片与详情组件，不另外复制封面或详情实现。

## 验收与回滚

构建后重验实际搜索按钮、短剧/漫剧、前两页、空末页、失败提示、详情、真实封面、队列恢复和服务重启。与其他贡献合并时保留已有路由、CORS头及缓存schema。

回滚时恢复原 `api.searchNovelfm` 初始化，移除搜索路由及仅本模块使用的CORS头，再删除这两个模块并重新构建。模块没有持久数据，无需数据库迁移。本机安装补丁的二进制修改与备份工具不包含在公开贡献中。
