# Strava 与 Garmin 数据源改造

## 用户目标

- Strava API 客户端失效后，改用官网下载的历史导出数据。
- 记录 Strava 历史数据的最后日期。
- 此后每天从 Garmin 动态拉取活动。
- 最终合并三类来源：早期手工数据、Strava 导出数据、Garmin 增量数据，并继续生成跑步统计。

## 本轮进展

- 将需求判定为架构型改造，先进行数据源与现有链路勘察。
- 当前生成链路为 `sync.py` 合并 JSON、导出 CSV，再由 `render.py` 生成 SVG。
- Strava 导出文件为中文表头，共 726 条活动；其中跑步 699、骑行 20、健走 6、远足 1。
- Git 中原有 Strava 同步基线共 708 条，类型分布同样包含跑步、骑行、健走和远足。
- Garmin 健康仓库已有可复用 tokenstore 登录逻辑，`garminconnect` 支持按日期和类型拉取活动。
- 当前工作区已有用户未提交变更，包括一次失败同步把 Strava 与合并数据写空；后续实现必须保留并谨慎恢复。

## 待确认

- 已确认活动筛选规则：排除骑行，其他活动都纳入统计。
- 已确认最终运行环境为 GitHub Actions，而不是长期运行的本地或 VPS 环境。
- 待确认 Garmin tokenstore 在 GitHub Actions 中的安全注入方式。

## GitHub Actions 现状

- 当前工作流每天北京时间 08:00 运行，并在推送到 `main` 时运行。
- 工作流会安装依赖、执行同步与渲染，然后把生成的数据和 SVG 提交回 `main`。
- Garmin 登录不能依赖本机路径；本机 tokenstore 当前只有一个 `garmin_tokens.json` 文件。

## 已确认的认证设计

- 将 `garmin_tokens.json` 内容保存到 GitHub Secret `GARMIN_TOKENS_JSON`。
- Action 运行时将 Secret 临时还原为 tokenstore 文件，任务结束后不保留该文件。
- 仓库不提交 Garmin 账号、密码或令牌。

## 已确认的增量状态设计

- 新增并提交 `data/running_records_garmin_sync.json`。
- 每次 Action 从已有 Garmin 增量数据的末尾继续拉取。
- 新数据经合并、去重后写回仓库，并随 CSV、SVG 一起提交到 `main`。

## 已确认的历史坐标设计

- 一次性导入 Strava 导出数据时，同时解析配套 GPX/FIT 文件。
- 尽量提取活动起点经纬度，保留地图历史点。
- 单个轨迹文件缺失、损坏或没有坐标时记录警告并留空，不阻断整体导入。

## 已确认的总体方案

- 采用方案 A：Strava 原始导出只在本地解析一次，仓库提交标准化快照与截止时间。
- GitHub Actions 日常运行只读取手工快照、Strava 快照并增量拉取 Garmin。
- 三类数据统一筛选、去重、排序后生成 combined JSON、CSV 和 SVG。

## Garmin 活动探测

- 用户建议先真实拉取 Garmin 活动并分析字段，再完成详细设计。
- 使用本机 `/Users/wanshuo/.garminconnect/137852926` tokenstore 进行只读登录探测。
- `garminconnect` 已成功加载 tokenstore，但读取 Garmin 用户资料时连续返回 HTTP 401。
- token 文件最后更新时间为 2026-04-11；当前证据表明令牌已被 Garmin 拒绝，并非路径或 JSON 格式问题。
- 在重新认证生成有效 token 前，不根据猜测固化 Garmin 字段映射。

### 更新令牌后的真实结果

- 用户更新 token 后登录成功，并拉取到边界附近 2 条 Garmin 跑步活动。
- `2026-09-02 06:24:09` 本地活动与 Strava 导出记录在 UTC 时间、距离和心率上一致。
- `2026-09-03 06:14:05` 本地活动同样与 Strava 最新记录一致，其 Garmin `activityId` 为 `24216312645`。
- Garmin 汇总活动直接提供 `activityId`、活动类型、UTC/本地开始时间、距离、持续时间、移动时间、平均速度、平均心率和起点经纬度，足够映射现有数据模型。
- `garminconnect` 会在 token 临近过期时主动刷新，并在设置 tokenstore 路径后自动覆盖 `garmin_tokens.json`；本次成功登录已实际更新文件修改时间。

## Token 持久化新约束

- 静态保存 token 内容不能保证长期运行，因为刷新后的文件必须跨 GitHub Actions 任务持久化。
- 需要在加密文件随仓库更新、Action 自更新 Secret、外部持久化存储三种方式中选定一种。
- 任何方案都只能通过每日运行显著降低失效概率；Garmin 主动撤销会话、长期停跑或认证机制变化时仍可能需要人工重新认证，不能承诺绝对永不失效。

## 已确认的 Token 存储方案

- 仓库提交加密后的 Garmin token 文件，GitHub Secret 只保存固定加密密钥。
- Action 启动时解密 tokenstore，运行结束前将最新 tokenstore 重新加密并提交。
- 已核对 `garminconnect`：刷新响应若包含新的 `refresh_token`，会同时替换内存中的旧值；序列化会完整保存 access token、refresh token 和 client ID。
- 实现必须比较刷新前后的明文内容，只在 token 实际变化时更新密文，避免随机加密造成无意义提交。
- 持久化逻辑必须覆盖 refresh token 轮换，并尽量缩短“服务端已轮换、密文尚未提交”的风险窗口。

## Garmin 类型目录验证

- 已从 Garmin 实际接口读取 154 个活动类型。
- 骑行父类型 `typeId=2`，公路车、山地车、室内骑行、砾石骑行、电助力车和手摇车等子类型均以 `parentTypeId=2` 归类。
- Garmin 侧应依据类型目录的父子关系排除骑行，不能只判断 `typeKey == cycling`。

## 设计归档

- 完整设计已写入 `docs/superpowers/specs/2026-09-03-strava-garmin-sync-design.md`。
- 已完成占位符、内部一致性、范围和歧义检查。
- 设计文档已提交，提交号为 `50df430`。
- 提交前工作区已有暂存的空 `vibe.md`，该空文件一并进入提交；磁盘上的 818 字节用户内容仍完整保留为未暂存修改，未被覆盖。

## 实施计划

- 用户已确认正式设计。
- 实施计划已写入 `docs/superpowers/plans/2026-09-03-strava-garmin-sync.md`。
- 计划分为八个可独立验证的任务，覆盖公共记录模型、Strava 导入、token 加密轮换、Garmin 增量同步、真实数据基线、GitHub Actions、文档验收和最终回归。
- 已完成规格覆盖、占位符和接口名称一致性检查。
- 计划明确保护当前工作区已有未提交内容，并要求每次只暂存任务指定文件。

## 实施进度：第一批

- 用户选择在当前会话按批次执行。
- 因项目禁用 worktree，已创建 `feature/strava-garmin-sync` 分支，未使用受禁名称。
- 完成统一活动记录、骑行过滤、来源边界和原子 JSON 写入，5 项测试通过，提交 `452d083`。
- 完成 Strava 中文 CSV、GPX、FIT 导入器和轨迹异常降级，相关 8 项测试通过，提交 `270d464`。
- 完成 Garmin tokenstore 认证加密、明文校验、变化检测、refresh token 轮换持久化和安全清理，5 项测试通过，提交 `d84c27c`。
- 当前所有提交均只暂存任务明确文件，原有用户修改仍保留在工作区。

## 实施进度：第二批进行中

- 完成 Garmin 字段映射、骑行父类型过滤、边界回看、ID 幂等更新、失败保护和 token `finally` 持久化，15 项相关测试通过，提交 `a322137`。
- 对完整 Strava 导出首次运行得到 706 条非骑行活动，但发现全部 FIT 因缺失字段抛 `KeyError`。
- 按系统化排查定位为 `fitdecode.get_value` 在字段不存在时抛异常，并确认本地时间位于 activity 帧、坐标位于 session 帧。
- 增加真实帧结构回归测试并修复，提交 `5dd502b`；重新导入后 706 条数量不变，坐标覆盖从 455 条提升到 553 条。
- 本机没有 GitHub CLI；已发现三个本地 Chrome 配置，需要用户指定用于登录 GitHub 并设置加密密钥的配置。
## 继续实现与验证

- 用户要求继续执行已确认的方案 A。
- 完成 GitHub Actions：使用 `GARMIN_TOKEN_KEY` 解密令牌，串行同步，并在任务结束时提交轮换后的密文和生成数据。
- 补充本地运行、Secret 配置、refresh token 轮换和令牌恢复说明。
- GitHub Secret 的值保存在本机钥匙串中，不在日志或代码中明文输出。
- 已在 `wansho/running` 的 Actions repository secrets 中创建 `GARMIN_TOKEN_KEY`，页面确认保存成功。
- 完成收尾验证，并修正 README 中令牌加密命令的参数格式。
