# Strava 历史快照与 Garmin 增量同步设计

## 背景与目标

现有项目依赖 Strava API 每日拉取活动，但该客户端已无法继续免费使用。新链路需要在 GitHub Actions 中持续运行，并统一使用三类数据：早期手工整理数据、Strava 官网导出历史、Garmin 每日增量活动。

目标如下：

- 一次性导入 `/Users/wanshuo/Downloads/export_71335350` 中的 Strava 历史数据。
- 记录 Strava 最后一条活动的 UTC 与本地时间，作为数据源切换边界。
- 边界之后只从 Garmin 拉取增量活动。
- 排除所有骑行活动，保留跑步、健走、远足及其他活动。
- 保持现有 combined JSON、CSV、SVG 生成链路可用。
- 支持 Garmin access token 与 refresh token 轮换，并在 GitHub Actions 之间安全持久化。

## 总体方案

采用“一次性历史快照 + 每日增量文件”方案：

```text
手工 JSON ───────────────┐
Strava 标准快照 ─────────┼─> 筛选与去重 ─> combined JSON ─> CSV ─> SVG
Garmin 增量 JSON <─ API ─┘
                        ↑
              加密 token 持久化
```

Strava 原始导出目录仅在本地导入一次，不提交仓库。仓库提交标准化 Strava 快照、Garmin 增量文件和加密 token 文件。GitHub Secret 只保存固定加密密钥，不直接保存 Garmin token。

## 数据文件

### 手工数据

继续使用 `data/running_records_manual_add.json`，不改变原始内容。

### Strava 历史快照

新增 `data/running_records_strava_export.json`：

```json
{
  "records": [],
  "data_source": "strava_export",
  "exported_at": "导入时间",
  "last_activity_start_utc": "2026-09-02 22:14:05",
  "last_activity_start_local": "2026-09-03 06:14:05"
}
```

当前已通过 Strava 与 Garmin 实际数据交叉验证，最新非骑行活动对应：

- Strava UTC：`2026-09-02 22:14:05`
- Garmin 本地时间：`2026-09-03 06:14:05`
- Garmin 活动 ID：`24216312645`

### Garmin 增量数据

新增 `data/running_records_garmin_sync.json`：

```json
{
  "records": [],
  "data_source": "garmin_sync",
  "last_successful_sync_at": null
}
```

该文件随每日结果提交，用于跨 Action 保存增量状态。只有完整拉取、解析和校验成功后才原子替换；接口异常时保留旧文件。

### Garmin 加密令牌

新增 `data/garmin_tokens.enc`，保存加密后的完整 tokenstore。明文 token 只写入 Action 的临时目录，并在任务结束时删除。

GitHub Secret `GARMIN_TOKEN_KEY` 保存固定加密密钥。使用带认证的加密方案，解密失败时立即停止，不尝试使用损坏数据。

## Strava 一次性导入

新增 `import_strava_export.py`，接收导出目录参数，执行以下步骤：

1. 使用 UTF-8 BOM 兼容方式读取中文表头 `activities.csv`。
2. 将活动 ID、名称、类型、UTC 时间、距离、耗时、移动时间、速度与心率映射到统一模型。
3. 排除中文类型“骑行”。
4. 根据 CSV 中的文件名解析 GPX 或压缩 FIT 文件，提取本地时间与起点经纬度。
5. 单个轨迹缺失、损坏或没有坐标时记录警告，保留汇总记录并将坐标置空。
6. 对结果去重、排序并原子写入 Strava 快照。
7. 从最终有效记录计算截止时间，不依赖 CSV 行顺序。

原有 Git 中的 Strava API 数据仅可用于导入结果核对，不作为新快照的数据来源。

## Garmin 拉取与字段映射

移除 `stravalib`、Strava OAuth 配置和 Strava API 调用，增加 `garminconnect`。

Garmin 实际响应已验证可直接提供：

- `activityId`
- `activityName`
- `activityType.typeId`、`typeKey`、`parentTypeId`
- `startTimeGMT`、`startTimeLocal`
- `distance`
- `duration`、`movingDuration`、`elapsedDuration`
- `averageSpeed`、`averageHR`
- `startLatitude`、`startLongitude`

统一模型继续沿用现有字段名，并把 `source` 设置为 `garmin`。配速由移动时间和距离统一计算。

Garmin 活动类型目录中，骑行父类型为 `typeId=2`。任何自身 `typeId=2` 或 `parentTypeId=2` 的活动都排除，从而覆盖公路车、山地车、室内骑行、砾石骑行、电助力车和手摇车等子类型。未知类型默认保留并记录日志。

## 时间边界与增量策略

首次 Garmin 同步从 Strava 截止日期的前一天开始查询，但只接纳严格晚于 `last_activity_start_utc` 的活动。回看一天用于规避本地日期查询和 UTC 边界差异。

后续同步从 Garmin 已存最新活动日期的前一天开始查询，并按 `activityId` 覆盖式合并。这样定时任务重跑、手动重跑和 Garmin 延迟入库都不会产生重复数据。

合并三类来源时再使用规范化活动指纹兜底去重。指纹由 UTC 开始时间、距离和持续时间组成；来源 ID 是首选标识。发生跨来源重复时，优先级为：

1. 手工数据保留其原始历史区间。
2. Strava 在截止时间及以前优先。
3. Garmin 在截止时间以后优先。

所有数据最终按本地开始时间排序。

## Token 刷新与持久化

Action 执行顺序如下：

1. 从 `data/garmin_tokens.enc` 解密完整 tokenstore 到临时目录。
2. 记录运行前 tokenstore 内容摘要。
3. 向 `garminconnect` 传入 tokenstore 路径并登录。
4. 库在 token 临近过期时自动刷新；刷新响应若返回新 refresh token，会同时替换旧值。
5. 库把最新 access token、refresh token 和 client ID 写回 tokenstore。
6. 在同步逻辑的 `finally` 阶段比较运行前后明文；仅在内容变化时重新加密并原子替换密文。
7. 删除临时明文文件。

若服务端已经轮换 refresh token，密文持久化失败属于关键故障。工作流必须失败并输出明确日志，不能报告同步成功。

为缩短轮换风险窗口，token 密文提交不依赖渲染成功。工作流的持久化提交步骤使用 `if: always()`，仅提交已完整生成的数据文件、SVG 和 token 密文。同步脚本对数据文件使用临时文件加原子替换，防止半写文件进入提交。

加密算法每次可能生成不同密文，因此只有明文 token 变化时才重新加密，避免无意义提交。

每日刷新只能降低自然过期概率，无法保证 Garmin 主动撤销会话、长期停跑或认证机制变化时永不失效。遇到认证失效时需要人工重新生成 token，并重新制作加密文件。

## GitHub Actions

更新 `.github/workflows/sync_render.yml`：

- 保留每日北京时间 08:00 的计划任务和 `main` 推送触发。
- 增加 `workflow_dispatch`，便于手动验证与补跑。
- 增加同一同步任务的并发锁，不取消正在运行的任务，避免两个任务同时轮换 token。
- 显式设置最小权限 `contents: write`。
- 删除全部 Strava Secret。
- 从 `GARMIN_TOKEN_KEY` 解密 token，并通过临时路径传给同步脚本。
- 同步结束后安全删除明文。
- 即使渲染失败，也执行 token 密文的提交步骤。
- 提交步骤只暂存明确列出的生成文件，不使用宽泛的 `git commit -a`。

工作流不依赖 Action cache 或 artifact 保存唯一 token 状态，因为两者都不适合作为不可丢失的长期状态源。

## 错误处理与日志

- 认证失败：立即失败，不修改 Garmin 增量文件。
- token 轮换后加密或提交失败：工作流失败并明确提示需要人工处理。
- Garmin 接口失败：保留旧增量文件，不用空列表覆盖。
- 单条 Garmin 活动字段异常：记录活动 ID 和异常字段；其余活动继续处理。
- Strava 单个轨迹异常：保留 CSV 汇总记录，坐标留空。
- 合并发现重复：记录来源、ID 和采用结果。
- 未知 Garmin 类型：默认保留并记录类型信息。
- 所有敏感 token 内容禁止写入日志。

## 测试与验收

自动测试不访问 Garmin 网络，使用固定响应覆盖：

- 中文 Strava CSV 解析与数值转换。
- GPX、FIT 和压缩 FIT 的坐标提取。
- 轨迹缺失或损坏时的降级行为。
- Strava 截止 UTC 与本地时间计算。
- Garmin 真实字段映射。
- `typeId=2` 与 `parentTypeId=2` 的骑行过滤。
- 未知活动类型保留。
- 首次边界过滤和每日回看。
- Garmin ID 去重与跨来源活动指纹去重。
- access token 不变、仅 access token 变化、refresh token 轮换三种持久化场景。
- 解密失败、加密失败和接口失败时不破坏旧数据。
- GitHub Actions 包含手动触发、并发锁、最小写权限和失败后的 token 持久化步骤。

本地验收包括：

1. 对完整 Strava 导出执行导入，核对活动数量、类型分布、最早与最晚时间。
2. 使用有效 Garmin token 拉取边界附近数据，确认边界活动只保留 Strava 版本。
3. 对 token 加密、解密和模拟轮换做往返校验。
4. 执行同步两次，确认第二次不产生重复记录。
5. 生成 CSV 和 SVG，确认图表可正常渲染且历史地图点未明显丢失。

## 不在本次范围

- 不提交 Strava 原始导出目录。
- 不继续调用 Strava API。
- 不修改图表视觉设计。
- 不把 Garmin 明文 token、账号或密码提交到仓库。
- 不依赖 VPS 或新增外部存储服务。
