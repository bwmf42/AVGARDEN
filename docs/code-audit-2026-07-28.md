# A/GARDEN 全量代码与存储审计

审计日期：2026-07-28

修复与清理完成：2026-07-29

## 结论

上一轮记录的 9 个延期问题已经全部修复、测试并部署。生产媒体库当前识别 220 部有效作品，全部主视频通过 `ffprobe`；Weekly 原始数据 1,811 条、已看历史 2,017 条保持不变。

用户看到的“两万多个文件”主要来自 NAS 的 `__weekly__` 图片缓存，不是源代码仓库。清理后 Weekly 图片由 18,772 张降为 13,183 张，1,237 个无引用目录已清零。

## 代码修复

| 原问题 | 最终处理 |
| --- | --- |
| 数字开头番号被截短 | Python、Go 和前端保留 `259LUXU-*`、`300MIUM-*` 等真实前缀；旧短 URL 和 qB 标签通过只读别名兼容。 |
| Queue 与 Go 的完成规则不一致 | 统一递归 MP4、100 MiB、95% 实际分配、普通作品选最大文件、多段优先第 1 段。 |
| `weekly.json` 写入不统一 | 全部生产写入使用跨进程锁、唯一临时文件和原子替换；无变化的标题任务不再重写 JSON。 |
| 前端依赖漏洞 | 同主版本升级 Axios、Vue、Vite、PostCSS 和 `form-data`；npm 官方审计为 0。 |
| `/file/` 路径边界过宽 | 限制到单个作品所有者目录，打开文件后复核软链接边界，并从已打开文件描述符提供 Range。 |
| Queue API 暴露到局域网 | Worker 改用 Compose 私有网络，31473 只在容器网络开放。 |
| Go HTTP 服务无超时 | 增加读取、请求头、写入和空闲超时；视频 Range 使用独立长写入期限。 |
| 部署只合并不删除 | 改用带运行数据保护规则的 `rsync --delete`，仓库移除的源码不会继续残留。 |
| 在线搜索缓存不回收 | 增加 24 小时 TTL、启动清理和每小时清理。 |

同时修复了两个执行期发现的兼容问题：本地目录 `fns-224ch` 现在在 Python 和 Go 中都解析为 `FNS-224`；旧 qB 短标签 `LUXU-*`、`MIUM-*` 可以找到数字前缀真实目录，但不会覆盖真实短号目录。

## 数据清理

主清单：`/db/maintenance/manifests/storage-cleanup-final-v2-20260729.json`

主结果：`/db/maintenance/manifests/storage-cleanup-final-v2-20260729.json.result.json`

补充 qB 清单：`/db/maintenance/manifests/qb-orphan-completions-20260729.json`

执行结果：

- 复制 12 张 Weekly 海报到已有有效视频但缺海报的媒体目录。
- 删除 1,237 个不在当前 `weekly.json` 的 Weekly 图片目录。
- 删除 7 个无有效任务的稀疏残留目录和 10 个无正片空壳目录。
- 删除 3 个旧 Weekly JSON 备份、2 个误放日志脚本和 1 个超过 30 天的日志文件。
- 从 qB 删除 160 条 `missingFiles`、3 条指定假完成记录和 4 条无目录假完成记录，全部使用 `deleteFiles=false`。
- 将 17 条有效 qB 任务迁移到 `AV_GARDEN`；最终 qB 中失效记录为 0，剩余任务分类全部为 `AV_GARDEN`。
- 为 `MIKR-109`、`PRED-886`、`SNOS-264` 重新入队；保留 `DEBZ-015` 的原在途任务。
- 实际释放 14,458,339,328 个已分配字节，约 13.47 GiB；稀疏文件逻辑大小使清单逻辑总量为 38.68 GiB。

## 备份与权限

删除前已在 `/db/backups` 生成并校验 5 份 gzip 备份：`.env`、Weekly、已看、`configs.json` 和 SQLite。权限结果：

- `.env`：`600`
- `cfg/configs.json`：`600`
- `cfg/`：`700`
- `/db/backups`：`700`

备份、manifest、结果报告、现役数据库和配置均保留。

## 验证结果

- Python：97 项通过，2 项仅容器环境测试在本地跳过；两项 Worker 集成路径已在生产容器单独验证。
- Go：race 测试与 `go vet` 通过。
- 前端：Node 测试和生产构建通过。
- npm：官方 registry 审计为 0 漏洞。
- 媒体：220 个统一主视频全部通过 `ffprobe`，失败 0、小 MP4 0、非多段重复候选 0。
- Weekly：1,811 条原始数据和 2,017 条已看记录不变；孤儿目录 0。
- API：`/api/version`、`/api/videos`、`/api/weekly`、`/api/video-status`、`/api/queue-status` 均正常。
- 播放：`FNS-224` 详情返回本地视频，Range 请求返回 `206`、正确 `Content-Range` 和 1,024 字节。
- 网络：NAS 宿主机 31473 连接被拒绝，主站容器代理正常。
- Docker：两个容器健康，仅删除 7 个本轮替换且无容器引用的旧镜像。

## 日常维护

`tools/maintenance/weekly_cache_maintenance.py` 是日常 Weekly 图片维护入口。默认只把“不在当前 JSON 且超过 30 天”的直接子目录写入 dry-run manifest；应用前再次验证 JSON、目录签名、mtime 和路径边界，并先备份索引。它不会替代本次一次性全量清理清单。

## 剩余运行态

没有未修复的审计代码项。`DEBZ-015` 以及三条恢复任务的最终下载结果属于持续变化的 qB 运行态，不是本轮代码阻塞项；4 个对应空目录在任务结束前按计划保留。
