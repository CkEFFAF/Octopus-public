# 0028：开发 / 生产 OCTOP_HOME 分离清单

规格：`docs/specs/0028-execution-isolation.md`（DEC-I05 / AC-I03）。

## 规则

1. **生产** `OCTOP_HOME`（如 `~/OctopData`）必须放置标记文件 `.octop_production`。
2. **开发**实例：`OCTOP_ENV=development|dev|local`（或未设置）**不得**指向已标记的生产目录。
3. JWT secret、连接器凭据、数据库均绑定该 home；共用即串权。

## 标记生产 home

```bash
# 在生产 OCTOP_HOME 下（示例）
touch "$OCTOP_HOME/.octop_production"
# 或
uv run python -c "from octop.infra.isolation.home_guard import write_production_marker; write_production_marker()"
```

建议 systemd 单元同时设置：

```ini
Environment=OCTOP_HOME=/home/ubuntu/OctopData
Environment=OCTOP_ENV=production
Environment=OCTOP_REQUIRE_BWRAP=1
```

## 启动检查

`octop run` 会调用 `check_dev_prod_home_separation`：

| 情况 | 结果 |
| --- | --- |
| 开发 env + 已标记 home | **失败**（进程不启动） |
| 生产 env + 未标记 | **警告**（建议补标记） |
| `OCTOP_HOME_GUARD=warn` | 失败降级为警告 |
| `OCTOP_HOME_GUARD=0` | 关闭检查 |

## 检查清单（人工）

- [ ] 生产与开发使用不同 `OCTOP_HOME`
- [ ] 生产已写 `.octop_production`
- [ ] 生产 JWT / Tunnel / 连接器密钥未拷进开发 home
- [ ] 开发配置未把 `OCTOP_HOME` 指到生产路径
- [ ] 备份恢复演练使用独立临时 home
