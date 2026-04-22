# Benchmark 指南

[English](benchmark.md)

当你想在同一套 `CLIProxyAPI` 承载的 Codex OAuth 池子上同时量化这两件事时，用 `codex-quota-benchmark`：

- `fast` 相对 baseline 的延迟和 token 行为
- Team 账号的 `5h` / `weekly` 容量相当于多少个 Plus

这个 benchmark 会为每个测试账号单独拉起一个只监听 loopback 的临时 `cli-proxy-api` 进程，并只复制那一个 auth file 进去，所以不需要改动现网 gateway 的路由。

## 前置条件

- 一个可访问的 `CLIProxyAPI` management gateway，典型值是 `http://127.0.0.1:8318`
- 对 management API 返回的底层 Codex auth file 有读取权限
- 本机能找到 `cli-proxy-api` 二进制，或者已有可被自动发现的 `cli-proxy-api.service`

## Selector 怎么工作

你不是直接给 raw path，而是用 selector 选账号：

- `--team-selector <value>`
- `--plus-selector <value>`，可重复传多个

selector 会在 `auth_index`、文件名、label、email、account、path 这些字段上做唯一匹配。如果同一个邮箱同时存在 Team 和 Plus 版本，就用完整文件名或 `auth_index`，不要只给邮箱。

## 推荐跑法

```bash
codex-quota-benchmark \
  --management-base-url http://127.0.0.1:8318 \
  --team-selector account-slot \
  --plus-selector account-slot \
  --plus-selector account-slot
```

默认行为：

- 在 `./result/` 下创建一个时间戳输出目录
- 性能部分先跑 `10` 组 warm-up A/B，再跑 `30` 组正式 A/B
- quota 部分默认用 baseline tier 批量压测，直到每个 Plus 参考号的 `5h` 至少下降 `15%`、`weekly` 至少下降 `5%`，或最多跑完 `40` 轮

## 常用参数

- `--prompt-file <path>`：用你自己的 prompt 集替换内置的 30 条默认样本
- `--model gpt-5.4`：把模型固定住
- `--reasoning-effort <value>`：把 reasoning 设置固定住
- `--quota-service-tier fast`：quota 压测也走 fast 路径，而不是 baseline
- `--skip-performance`：只测 Team 相对 Plus 的 quota 倍率
- `--skip-quota`：只测 fast 相对 baseline 的性能
- `--keep-work-dir`：把临时 gateway 的 config 和日志也保留下来

## 输出文件

- `config.json`：解析后的账号元数据、模型和 prompt 数量
- `requests.csv`：逐请求延迟、tier、prompt class 和 token 明细
- `quota_snapshots.jsonl`：逐批次 direct quota 快照和窗口 delta
- `summary.json`：机器可读摘要
- `report.md`：给人看的结论和倍率

## 结果怎么解读

- 性能 A/B 比的是 baseline 请求和 `service_tier = priority` 请求。
- Team 相对 Plus 的倍率，是用同负载下 direct quota window 的真实下降量反推出来的。
- 如果某个 batch 跨过了 quota reset，那个 batch 会被标成无效，不会被偷偷并进平均值里。
