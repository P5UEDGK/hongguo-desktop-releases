# 正式搜索恢复

输入“谁说没灵根”时官网联想有结果，正式搜索却失败。本机对照发现：原生搜索向 `/novelfm/bookmall/search/page/v1/` 发送 POST JSON，HTTP 200 但业务码为6000；相同重建参数改用 GET query 返回业务码0及20条漫剧。官网联想属于另一条调用链。

本贡献提供已在本机接入验证的搜索模块、前端传输工厂和测试。公开发行仓库没有完整 Rust/React 工程，维护者仍需按 [接入说明](INTEGRATION.md) 移入私有源码、构建验收并发布。合并这些材料不会更新已发布应用。

- GET 请求复用宿主连接池和 TLS/网络策略，不改变身份、签名或代理配置。
- 短剧和漫剧每页20条；使用服务端 `next_offset`、`search_id`、`has_more`。重复页可重放，跨页重复、游标不推进及损坏响应明确报错；失败不提交游标。
- 会话仅存内存，10分钟过期、最多64组、页码上限100。服务重启或过期后重新从第一页搜索。
- 业务6000或传输失败最多再尝试一次；仍失败时明确报错，不伪装成无结果或末页。其他非零业务码不会自动重试。
- 每条结果保留 `source: "novelfm"`，继续使用宿主的封面缓存和详情入口。前端复用现有搜索队列。

## 测试

Python 3.11、Node.js 18及以上；依赖版本为本机实际验收版本。在本目录运行：

```pwsh
pwsh -NoProfile -Command 'python -m pip install -r requirements-test.txt'
pwsh -NoProfile -Command 'python -m unittest discover -s tests -p test_desktop_search.py -v'
pwsh -NoProfile -Command 'node --test tests/test_frontend_search.mjs'
```

单测使用人工数据，不访问上游。[验证范围与限制](VALIDATION.md) 区分导出测试、本机运行证据和维护者待验收项。
