<div align="center">
<img style="max-width:50%;" src="pic/logo.png" alt="AV/GARDEN" />
<br>
</div>

# AV/GARDEN

AV/GARDEN 是一个给 NAS 和家庭服务器用的媒体管理小站。

它的目标很简单：

1. 先帮你找到能下的资源。
2. 再把任务交给 qBittorrent 或在线兜底源。
3. 下载完后自动整理成 Jellyfin 之类能直接看的库。

当前版本：`0.1.0`

仓库名建议：`AVGARDEN`

## 一句话说明

你可以把它理解成一个“下载 + 刮削 + 浏览”一体的小工具。
打开网页后，你能：

- 看每日推荐
- 一键加入下载队列
- 只看最近一周的失败记录
- 搜索本地库和已刮削条目
- 手动触发刮削
- 查看下载和整理状态

## 适合谁

- 已经有 NAS 或家庭服务器的人
- 已经在用 qBittorrent 的人
- 想把视频库整理得更像媒体库的人
- 想要一个能在浏览器里直接操作的界面的人

如果你只是想先跑起来，直接看 [INSTALL.md](INSTALL.md)。

## 它大概怎么工作

```text
浏览每日推荐 -> 加入队列 -> 先找磁链 -> 交给 qB -> 失败时再走在线兜底 -> 刮削元数据 -> 进媒体库
```

在线兜底源只在没有找到磁链时才会尝试。

## 主要功能

- 粉白色 Web 界面，直接在网页里操作
- 每日推荐和详情页
- 搜索本地媒体和刮削结果
- 下载队列和最近失败记录
- 手动刮削
- 下载完成后生成封面、NFO 和预览图
- 支持屏蔽、收藏、已看状态
- `GET /api/version` 可以快速确认版本

## 快速开始

1. 先准备好 Docker、qBittorrent 和一个视频保存目录。
2. 复制配置模板：

```bash
cp .env.example .env
cp cfg/configs.json.example cfg/configs.json
mkdir -p db logs
```

3. 把 `.env` 里的这几项改成你自己的：

```text
AV_GARDEN_DATA_DIR=/你的/视频目录
QBITTORRENT_URL=http://你的qB地址
QBITTORRENT_USERNAME=你的用户名
QBITTORRENT_PASSWORD=你的密码
```

4. 启动：

```bash
docker compose -f docker-compose.example.yml --env-file .env up -d --build
```

5. 打开网页：

```text
http://<服务器地址>:31471
```

更完整、也更稳妥的步骤写在 [INSTALL.md](INSTALL.md)。

## 给 AI agent 的最短清单

如果让别的 AI 来接手，先给它看这些文件：

```text
README.md
INSTALL.md
AGENTS.md
.env.example
docker-compose.example.yml
cfg/configs.json.example
```

它只需要确认三件事：

- 视频目录填对了没有
- qBittorrent 地址和账号密码对不对
- qB 的保存目录是不是和 `AV_GARDEN_DATA_DIR` 指向同一份存储

## 常见问题

### 为什么页面能开，但下载不工作

通常是 qBittorrent 地址、账号密码，或者保存目录没对上。先看 `INSTALL.md` 里的排查步骤。

### 为什么状态栏里只看最近的失败

这是故意的。成功项不占位置，失败项也只保留最近一周。

### 为什么有时要去在线兜底源

因为并不是每个条目都能找到磁链。没有磁链时，才会去尝试在线兜底。

## 致谢

感谢 [Satoing/NASSAV](https://github.com/Satoing/NASSAV) 的开源源码和思路，AV/GARDEN 是在它基础上继续整理和演进的。

## 许可证

MIT License。详见 [LICENSE](LICENSE)。
