# running

![跑步统计](running.svg)

个人运动数据可视化。数据由三部分合并而成：

- `data/running_records_manual_add.json`：以前手工整理的数据；
- `data/running_records_strava_export.json`：从 Strava 官网一次性导入的历史数据；
- `data/running_records_garmin_sync.json`：从 Strava 截止时间之后持续同步的 Garmin 数据。

骑行活动会被排除，其他活动均会纳入统计。合并结果写入
`data/running_records_combined.json` 和 `data/running.csv`，再由 `render.py`
生成 `running.svg`。

## 本地运行

安装依赖：

```bash
python -m pip install -r requirements.txt
```

首次导入 Strava 官网导出包：

```bash
python import_strava_export.py /Users/wanshuo/Downloads/export_71335350
```

Garmin 登录令牌以 Fernet 密文形式保存在
`data/garmin_tokens.enc`。解密密钥保存在 macOS 钥匙串，读取后可执行同步：

```bash
GARMIN_TOKEN_KEY="$(security find-generic-password \
  -a wanshuo -s running-garmin-token-key -w)" python sync.py
python render.py
```

同步成功后，如果 Garmin 轮换了 access token 或 refresh token，程序会自动将
完整的新令牌重新加密并覆盖 `data/garmin_tokens.enc`。

## GitHub Actions

工作流每天北京时间 08:00 自动运行，也可在 Actions 页面手动触发。仓库只需设置
一个 Actions Secret：

- 名称：`GARMIN_TOKEN_KEY`
- 值：本机钥匙串中 `running-garmin-token-key` 的内容

密钥只放在 GitHub Secret；轮换后的完整 Garmin 令牌以密文提交回仓库。工作流带有
并发保护，并且即使同步失败也会尝试保存已经轮换的新密文，避免 refresh token
丢失。

若密文或 Secret 损坏，使用 Garmin Connect 重新登录生成有效的
`garmin_tokens.json`，再运行：

```bash
GARMIN_TOKEN_KEY="$(security find-generic-password \
  -a wanshuo -s running-garmin-token-key -w)" \
  python garmin_tokens.py encrypt \
  --input /Users/wanshuo/.garminconnect/137852926/garmin_tokens.json \
  --output data/garmin_tokens.enc
```
