# 数据库设计（PostgreSQL + pgvector）

## 目标
- 支撑结构化数据、新闻、CBA 规则库、文风样本
- 便于向量检索与引用追溯

## 核心表
- teams / players / games
- team_stats / player_stats
- news_items
- cba_rules
- style_samples

## 结构文件
- `apps/api/db/schema.sql`

## pgvector
- 需要启用扩展：
  `CREATE EXTENSION IF NOT EXISTS vector;`
- CBA 与文风样本可加 embedding 字段（1536 维示例）

## 下一步
- 接入数据库迁移工具（如 Alembic）
- 加载 CBA JSONL 到 cba_rules
- 引入样本文风数据
