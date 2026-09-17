# Java 并发编程面试知识

## 线程生命周期

Java 线程有新建、可运行、阻塞、等待、超时等待和终止六种状态，新建线程调用 start 后进入可运行态等待 CPU 调度。synchronized 未获锁进入阻塞态，wait 进入等待态，sleep 进入超时等待态，锁释放或时间到后回到可运行态。

## volatile 可见性

volatile 保证变量可见性和禁止指令重排序，不保证原子性，写操作立即刷入主内存，读操作强制从主内存读取，常用于状态标志位和单例双重检查锁中。复合操作如 i++ 仍需 synchronized 或原子类保证原子性。

## synchronized 锁升级

synchronized 基于 Monitor 对象监视器实现，JVM 对锁进行偏向锁、轻量级锁、重量级锁的升级过程，锁只能升级不能降级。偏向锁减少无竞争加锁开销，轻量级锁用 CAS 自旋竞争，重量级锁由操作系统互斥量实现。

## AQS 原理

AQS 是 JUC 锁和同步器的核心框架，基于 volatile 状态变量加 CLH 变体双向等待队列实现，获取资源失败时线程封装成节点入队并阻塞，释放时唤醒队首后继节点。ReentrantLock、Semaphore、CountDownLatch 都基于 AQS 构建。

## CAS 与 ABA

CAS 即比较并交换，通过比较内存值与期望值相等才更新实现无锁原子操作，依赖处理器 cmpxchg 指令。ABA 问题指值从 A 变 B 又变回 A 导致 CAS 误判，可用版本号 AtomicStampedReference 解决。

## 线程池参数与拒绝策略

ThreadPoolExecutor 核心参数包括核心线程数、最大线程数、空闲存活时间、工作队列和拒绝策略，任务先占核心线程，队列满扩到最大线程数，再满触发拒绝策略。拒绝策略为 AbortPolicy、CallerRunsPolicy、DiscardPolicy 和 DiscardOldestPolicy。

## ThreadLocal 与内存泄漏

ThreadLocal 为每个线程保存独立变量副本，底层每个线程持有 ThreadLocalMap，Key 是 ThreadLocal 弱引用。线程池场景下线程复用导致 Entry 的 value 无法回收引发内存泄漏，使用后应调用 remove 清理。

## 并发容器

Java 并发容器有 ConcurrentHashMap、CopyOnWriteArrayList、BlockingQueue、ConcurrentLinkedQueue、跳表等。ConcurrentHashMap 用 CAS 加锁桶保证并发安全，CopyOnWriteArrayList 写时复制适合读多写少。

## CountDownLatch 与 CyclicBarrier

CountDownLatch 是计数器一次性门闩，主线程 await 等待计数归零，用于一个或多个线程等待其他线程完成。CyclicBarrier 是可循环复用的屏障，所有线程到达屏障点后一起放行，可传 barrierAction 回调。

## 死锁条件与排查

死锁产生的四个必要条件是互斥、持有并等待、不可剥夺和循环等待，破坏任一条件即可避免死锁，如按固定顺序加锁。排查可用 jps 加 jstack 查看线程堆栈，检测到 deadlock 后定位持锁线程。
