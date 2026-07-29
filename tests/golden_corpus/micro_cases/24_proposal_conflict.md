# 微型边界案例：两个Agent相反结论

## Source

[P01] Agent A判断“沈河在现场”。
[P02] Agent B判断“沈河不在现场”。
[P03] 原文只写“有人看见一个相似背影”。

## 测试问题

1. 两个Proposal能否直接覆盖？
2. Canonical Data应保存什么？
3. 是否应输出UNKNOWN并保留冲突来源？

## 作答规则

- 依据当前领域词汇与业务规则。
- 引用段落编号。
- 证据不足时必须输出UNKNOWN或UNCERTAIN。
- 不得自动修改领域词汇表。
