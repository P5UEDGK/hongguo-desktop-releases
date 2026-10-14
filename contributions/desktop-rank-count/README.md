# 修复排行榜部分条目显示“全 ? 集”

官网榜单响应已经包含每部剧的完整 `episodeVids`，桌面端原链路遗漏了这些数据，只能从首页补齐部分条目。此贡献直接解析同一榜单 loader 响应，按列表长度填入 `episodeCount`，覆盖全部、真人、漫剧和AI榜单及既有分页。

每次未命中缓存或显式刷新只请求一次榜单；不查询详情、不请求首页、不逐部补数、不自动重试。同页重叠加载共享结果或错误，后续独立调用可以重试。服务复用HTTPX异步客户端和网络循环，调用有20秒等待预算；DNS停滞、响应头或正文持续慢速发送均触发超时取消。模块不写用户数据库，失败不会覆盖成功缓存。

本目录包含独立 Python 模块、前端工厂、离线测试和脱敏样本。公开仓库没有完整应用工程，合并本目录不会自动更新发行包，仍需维护者按 [INTEGRATION.md](INTEGRATION.md) 接入并构建验收。验证范围见 [VALIDATION.md](VALIDATION.md)。

在本目录执行：

```pwsh
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -p test_desktop_rank.py -v
node --test tests/test_frontend_rank.mjs
```
