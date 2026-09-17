# 张伟 的简历

## 基本信息
- 姓名：张伟
- 职位：Java 后端开发工程师
- 工作年限：8 年
- 邮箱：zhangwei@example.com
- 电话：13800000001
- 教育背景：华中科技大学 计算机科学与技术 本科 2014-2018

## 技能清单
- Java
- Spring Boot
- Spring Cloud
- Redis
- MySQL
- Kafka
- Docker
- Kubernetes
- Elasticsearch
- Nginx

## 项目经历
### 电商订单系统（后端负责人）
主导日订单量百万级的电商订单系统重构。使用 Spring Boot + Spring Cloud 微服务架构，Redis 缓存热点数据，MySQL 分库分表承载订单存储。
技术选型：Spring Cloud、Redis、MySQL 分库分表、Seata 分布式事务
难点与亮点：订单状态机设计，解决分布式环境下订单状态一致性问题；缓存雪崩防护：Redis 多级缓存 + 热点数据本地缓存预热

### 支付网关（核心开发）
对接微信、支付宝等 12 家渠道的支付网关，统一签名与回调协议，峰值 5000 TPS。
技术选型：Netty、RocketMQ、幂等设计
难点与亮点：回调幂等：基于渠道单号 + 本地流水表唯一约束去重；对账系统每日自动核对资金流水差异

### 消息推送平台（技术选型）
自建消息推送平台，支持短信/站内信/APP Push 多渠道触达，日推送量千万级。
技术选型：Kafka、Flink、Redis
难点与亮点：Kafka 削峰填谷，Flink 实时统计各渠道送达率；失败消息重试与死信队列治理


## 工作经历
- 2021-至今 某电商公司 Java 后端开发工程师
- 2018-2021 某软件公司 Java 开发工程师
