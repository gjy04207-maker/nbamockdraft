# Draft Data

此目录用于覆盖默认的模拟选秀数据。

## 方式一：单文件覆盖（推荐）
将 `draft_data.json` 放入本目录，结构如下：

```
{
  "updated_at": "2026-03-18T00:00:00Z",
  "teams": [
    {"id": "ATL", "abbr": "ATL", "name": "亚特兰大 老鹰", "needs": ["G", "F"]}
  ],
  "players": [
    {"id": "p001", "name": "示例新秀", "position": "G", "school": "杜克", "height": "6'4\"", "age": 19, "notes": "持球核心"}
  ],
  "boards": [
    {"id": "tankathon", "label": "Tankathon Big Board", "source_url": "https://www.tankathon.com/mock_draft"}
  ],
  "rankings": {
    "tankathon": ["p001"]
  },
  "draft_order": [
    {"pick": 1, "round": 1, "original_team": "ATL", "current_team": "ATL", "via": null}
  ],
  "pick_values": {
    "1": 3000
  },
  "order_sources": [
    {"id": "tankathon", "label": "Tankathon 模拟顺序"}
  ],
  "pick_value_source": "nbasense (参考)",
  "pick_value_tolerance": 100
}
```

服务端会优先读取该文件；不存在时会回退到内置的示例数据。
