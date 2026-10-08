# 凭据状态核查（M0-W1）

- 核查日期：2026-10-08
- 核查方式：仅 `ls` 存在性检查。**未 cat/head/打印任何文件内容，本报告不含任何密钥值。**

## 1. secrets 目录

```
$ ls -la /home/pan-ding/workspace/视频能力/overnight/secrets/ 2>&1
ls: 无法访问 '/home/pan-ding/workspace/视频能力/overnight/secrets/': 没有那个文件或目录
（退出码 2）
```

**结论：目录不存在。** 符合密钥纪律预期——密钥从未落盘、从未入 git。

## 2. 本机数据目录

```
$ ls /home/pan-ding/workspace/视频能力/overnight/数据/
_archive-20261005
avatar_out
digital_human
golden
j6_v2
judges
samples
```

- `golden/`（金标 clips）与 `judges/`（三判官输出 + detectors 原始特征）在本机有副本，与 REPRODUCE.md §0 依赖表一致（GPU 侧为原件，本机为镜像）。
- `j6_v2/synthetic`、`avatar_out`、`digital_human` 为 21 片夹具 mp4（.gitignore 域），在位。

## 3. 结论

**凭据不在本机**（`overnight/secrets/` 不存在，未发现任何密钥文件）。任何需要 Volcano/即梦 API key、判官 API key 的操作（如 Seedance 实测计费验证、判官重跑），需 **owner 按环境变量或 OpenBao 现场重建注入**，本核验员不持有、不代管、不落盘。

本报告按红线仅记录文件名/目录名与存在性，无任何字节内容、无任何 key 值。
