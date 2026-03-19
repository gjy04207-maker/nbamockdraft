# 站点抓取器设计与合规策略

## 设计原则
- 默认拒绝：未明确允许的路径不抓取
- 先验合规：每次运行先读取 robots.txt
- 缓存与限速：降低对站点影响
- 透明可追溯：原始快照可回溯

## 现有实现
- fetcher 基类：`scripts/fetchers/base.py`
- 站点 fetcher：`scripts/fetchers/*.py`
- 运行器：`scripts/ingest_runner.py`
- 配置：`scripts/ingest_config.json`

## 合规步骤
1. 读取 robots.txt
2. 验证 planned_urls 是否允许
3. 未允许则标记 blocked_by_robots
4. 允许才执行实际抓取

## 目前已实现
- nba.com：抓取 /schedule、/standings、/players（HTML 标题）
- espn.com：抓取 /nba（HTML 标题）

## 下一步
- 为每站点补全 planned_urls 和解析逻辑
- 增加限速与重试
- 增加数据一致性校验
