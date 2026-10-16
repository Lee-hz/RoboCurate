# RoboCurate

真机遥操作数据的 VLM 审核工作台。以范本定义任务阶段和完成条件，对同类记录逐段判断，提供同步录像、3D 姿态、关节反馈和人工复核。

[下载源码](https://github.com/Lee-hz/RoboCurate/archive/refs/heads/main.zip) · [使用说明](docs/TASKFLOW.md) · [English](README.md)

## 启动

需要 Python 3.10+、FFmpeg 和浏览器。已在 Linux 上测试，无需 ROS。

Ubuntu / Debian 安装依赖后启动：

```bash
sudo apt-get update
sudo apt-get install -y python3-venv ffmpeg
./start.sh
```

打开 http://127.0.0.1:8421/。首次启动自动创建 Python 环境并安装依赖。也可用 `./start.sh /你的录制目录` 指定 MCAP 数据目录。

## 使用

1. **接入 MiniMax**：右上角填写接口地址和自己的 API Key，保存接入。
2. **建立范本**：打开「任务范本」，先在「导入数据」中将采集记录加入审核数据，再选择范本录像并解析阶段与完成条件，查看并修订模型给出的定义。
3. **审核数据**：打开待审记录，选择范本和审核范围，开始分析。
4. **核对结果**：查看每次尝试的完成条件、证据和实际模型输入，通过时间轴联动录像、3D 和关节反馈。
5. **人工复核**：保存修订和保留结论，按需导出审核 JSON。

接入使用公司网关中的图像模型 `HORIZON-MiniMax`。接口须支持多图 Chat Completions；不会切换到其他模型。访问公司内网接口前，需连接公司网络或 VPN。保存配置不调用模型，任务分析按使用者自己的 API 额度计费。

每个人在自己的电脑运行。API Key 保存在本机 `workspace/taskflow/minimax-local.json`，权限为 `0600`，页面不回显。原始记录只读；审核结果、缓存和导出保存在 `workspace/`。源码不包含密钥、录像或模型权重。

## 适用范围

- 支持 G1 MCAP 和常见视频文件。MCAP 可使用相机及机器人反馈，普通视频只有视觉输入。
- 阶段允许重复、回退和多次尝试。结果分为已完成、未完成和证据不足。
- 模型输出需结合证据复核。关节运动不能单独证明抓取或放置成功；当前不提供精确空间测量或经验证的任务准确率。
- 范本定义可编辑；目前没有单独的范本审批状态。

## 开发与许可

[开发说明](CONTRIBUTING.md) · [源码打包](docs/SOURCE_PACKAGE.md) · [安全说明](SECURITY.md) · [贡献者](CONTRIBUTORS.md)

基础查看器的再分发许可尚待核实，项目未设置统一开源许可证。详见[许可状态](LICENSE_STATUS.md)及[第三方许可](THIRD_PARTY_NOTICES.md)。
