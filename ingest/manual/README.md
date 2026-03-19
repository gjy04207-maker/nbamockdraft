# Manual Ingest Snapshots

将第三方数据快照保存为 JSON：
- `tankathon.json`
- `fanspo.json`
- `noceilings.json`

`ingest_runner.py` 会读取这些文件并写入 `data/ingest/raw/` 的快照文件（status=manual）。
结构不限，但建议包含 `items` 字段，例如：

```
{
  "items": [
    {"name": "示例球员", "rank": 1}
  ]
}
```
