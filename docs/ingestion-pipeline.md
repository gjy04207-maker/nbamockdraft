# 数据抓取管线

## 目标
- 小时级更新新闻与关键数据
- 可缓存、可回溯、可审计
- 严格遵守站点条款与 robots.txt

## 管线结构
- 任务调度：按来源与频率运行
- 原始快照：保留原始响应
- 结构化提取：映射到统一表结构
- 验证与去重：多源一致性校验

## 目录
- 配置：`scripts/ingest_config.json`
- 运行器：`scripts/ingest_runner.py`
- 原始快照：`data/ingest/raw/*.json`
- 状态：`data/ingest/state.json`

## 运行方式（本地）
- 先运行一次测试：
  `python3 scripts/ingest_runner.py`

## 下一步（接入真实站点）
- 每个站点建立独立 fetcher
- 增加限速与指数退避
- 加入 robots.txt 解析与合规检查
- 增加字段级验证（赛程、效率、薪资）
