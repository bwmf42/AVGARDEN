# A/GARDEN Code And Storage Audit

Date: 2026-07-28

## Conclusion

The reported twenty-thousand-file tree is not the source repository. It is the
NAS media volume's `__weekly__` artwork cache. The active source checkout had
130 tracked files before this cleanup; most local filesystem entries came from
Git metadata and reinstallable frontend dependencies.

This cleanup does not delete media, Weekly artwork, online-search artwork,
configuration, database state, logs, or qBittorrent tasks.

## Storage Inventory

| Area | Inventory | Decision |
| --- | ---: | --- |
| Current `weekly.json` | 1,811 entries | Keep |
| Current Weekly artwork directories | 1,811 directories, 13,183 JPG files, 1.53 GB | Keep |
| Weekly directories absent from current index | 1,237 directories, 5,589 JPG files, 602,879,376 bytes | Report only |
| Total Weekly artwork | 18,772 JPG files, about 2.13 GB | Keep |
| Old Weekly JSON backups | 3 files, about 15 MB | Keep in this pass |
| Online temporary artwork | 1 directory, about 160 KB | Keep in this pass |
| NAS deployment residue removed | 21 exact paths, 25,108,415 bytes (23.95 MiB) | Removed from the deployment tree |

Of the 1,237 unindexed Weekly directories, 729 codes remain in watched history
and 115 have an exact same-name media directory. Neither category is deleted in
this pass.

## 延期问题

以下问题已在本次审计中确认，但由于本轮只处理文件精简，因此暂不修改业务逻辑，留待后续逐项修复。

1. **高：数字开头的本地番号会被截短。** `backend/main.go` 扫描媒体库文件夹时仍使用旧的
   `cleanVideoID` 逻辑。线上目前会把 `300MIUM-*` 显示成 `MIUM-*`，把 `259LUXU-*`
   显示成 `LUXU-*`。用户输入番号时虽然可以正确保留数字前缀，但媒体库扫描结果仍可能错误。
2. **高：Queue API 和 Go 服务判断“下载完成”的标准不一致。** `queue_api.py` 只检查作品目录
   第一层文件，MP4 大于 10 MB 且创建超过 60 秒就可能被视为完成；Go 服务则会递归查找，要求
   MP4 大于 100 MB，并且实际已写入的数据至少达到文件标称大小的 95%。因此，看起来很大但实际
   尚未下载完整的稀疏文件，或者附带的小视频，仍可能让 Queue API 提前执行完成后的操作。
3. **高：并非所有写入 `weekly.json` 的路径都使用共享锁。** 队列状态更新、详情图本地化、
   中文字幕替换和部分旧的一次性脚本仍会直接写文件，或使用固定名称的临时文件。它们如果和
   定时更新同时运行，可能互相覆盖数据或写坏 JSON。
4. **高：部分前端依赖已有公开安全漏洞。** npm 官方审计在当前锁定版本中报告了 4 个高危
   依赖条目：`axios 1.16.1`、`form-data 4.0.5`、`postcss 8.5.14` 和 `vite 6.4.2`。
   即使排除纯开发依赖，仍有 3 个高危条目。官方已有可升级版本，但依赖升级和回归测试留到
   单独一轮处理。
5. **中：媒体文件接口的路径限制不够严格。** `/file/` 目前只确认最终路径仍位于整个媒体库
   根目录内，因此请求仍可能跨到另一个作品目录；同时没有检查软链接解析后的真实路径。
6. **中：Queue API 没有独立鉴权，并且所有局域网接口都能访问。** 生产 Worker 使用 host
   网络模式，端口 31473 绑定到 `0.0.0.0`。同一网络内能够访问该端口的设备可能绕过主站接口，
   直接调用 Queue API。
7. **中：Go HTTP 服务没有设置读取、写入、请求头和空闲连接超时。** 异常或恶意客户端可以
   长时间占用连接，增加服务资源被耗尽的风险。
8. **中：部署脚本只合并新源码，不会删除已经从仓库移除的文件。** 本次通过精确 manifest
   做了一次安全清理，但以后仓库再次删除或移动文件时，旧副本仍可能继续留在 NAS，直到部署
   同步逻辑增加受控删除机制。
9. **低：在线搜索缓存没有服务端超时回收。** 浏览器离开页面时会尽力清理，但如果浏览器关闭、
   网络中断或请求失败，缓存仍可能留下。NAS 目前保留了一份 2026-07-06 产生的历史临时目录。

## Baseline Verification

- Go race tests and `go vet`: passed.
- Frontend Node tests and production build: passed.
- Official npm dependency audit: four high-severity package entries; three
  remain with development dependencies omitted. Recorded above for follow-up.
- Python: 76 effective tests passed and 2 Worker-container integration tests
  were skipped locally. The obsolete `test_clean.py` caused standard discovery
  to fail because it had no assertions and imported the full runtime at module
  load; it is removed by this cleanup.
- Production containers and API were healthy during the audit. Two qBittorrent
  tasks were active, with no online-stream downloader process and no Worker lock.

## Cleanup Result

The exact 21-path deletion manifest was saved on the NAS as
`/tmp/avgarden-cleanup-manifest-20260728.json` before removal. It contained only
reviewed project residue: implemented design demos, temporary genre scripts,
obsolete root-level module copies, an obsolete Vue file, two old backend
binaries, moved maintenance-script copies, unused starter assets, and dated
environment, Compose, and deployment-script backups.

After removal, the current Compose file, `.env`, `cfg/`, `db/`, and `logs/`
were verified present. Media directories, qBittorrent tasks, Weekly and online
artwork caches, and other runtime state were not touched.
