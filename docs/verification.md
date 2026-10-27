# A/GARDEN 验证命令

## 一键验证

在仓库根目录执行 `scripts/check.sh`（默认 `--layer 1`）；`--quick` 仅跑 Python 语法和单测，覆盖 `--layer` 参数。第 1 层覆盖 Python 语法/单测、Go vet/test、前端构建；`--layer 2` 只读检查 NAS 版本、JSON 接口、容器状态；`--layer all` 运行两层。第 3 层真实入口需人工或浏览器验收。

退出码：`0` 全部 PASS 或 SKIP；`1` 有 FAIL 或参数错误；`2` 第 2 层整体连不上 NAS。必须同时检查 PASS/FAIL/SKIP，退出码 0 不表示跳过项已经验证。缺少工具会 SKIP，Go 依赖下载被禁用；具体子命令日志路径见脚本输出。只有任务明确允许联网时才运行第 2 层。

以下保留原分项验证命令，按改动范围选用；各代码块从仓库根目录开始执行。

## 常用验证命令

前端：

```bash
cd frontend
npm run build
```

Go 后端：

```bash
cd backend
GOCACHE=/private/tmp/av-garden-gocache go test ./...
```

Python 语法检查：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/av-garden-pycache python3 -m py_compile \
  worker.py queue_api.py launcher.py weekly_updater.py run_scrape_followups.py \
  unwatched_chinese_refill.py metadata.py replace_chinese.py \
  plwt_art_backfill.py weekly_backfill_details.py \
  src/weekly/artwork.py src/weekly/javdatabase.py src/weekly/dmm.py src/weekly/mgs.py \
  src/weekly/enrich.py src/weekly/sukebei.py
python3 -m unittest test_artwork_sources -v
python3 -m unittest test_unwatched_chinese_refill -v
```

Compose 部署验证：

```bash
docker compose -f docker-compose.example.yml --env-file .env ps
curl -sS http://127.0.0.1:31471/api/version
curl -sS http://127.0.0.1:31471/api/queue-status
```
