# RoboCurate

真机遥操作数据的 VLM 审核工作台。从范本录像提取任务阶段和完成条件，对照审核其他记录，联动查看录像、3D 姿态和关节反馈。

[下载](https://github.com/Lee-hz/RoboCurate/releases/latest) · [English](README.md)

## 启动

需要 Python 3.10+、FFmpeg 和浏览器。Ubuntu / Debian：

```bash
sudo apt-get update
sudo apt-get install -y python3-venv ffmpeg
./start.sh
```

打开 http://127.0.0.1:8421/。首次启动自动创建 Python 环境并安装依赖。可用 `./start.sh /你的录制目录` 指定 MCAP 目录。

## 使用

1. **接入 MiniMax**：在右上角「MiniMax 接入」填写网关地址和自己的 API Key。
2. **建立范本**：打开「任务范本」，在「导入数据」中添加录像，再选为「范本录像」，解析并修订阶段与完成条件。
3. **审核数据**：打开另一条记录，选择范本和审核范围，开始分析。
4. **核对与保存**：联动回放查看证据和模型输入，保存人工修订，导出审核 JSON。

支持多图 Chat Completions 网关中的 **HORIZON-MiniMax**。内网接口需连接公司网络或 VPN。每个人在自己的电脑运行，使用自己的 API Key。

支持 G1 MCAP 和视频文件。MCAP 提供相机及机器人反馈，视频提供画面。结果与配置保存在 `workspace/`。

## 文档

[使用说明](docs/TASKFLOW.md) · [开发说明](CONTRIBUTING.md) · [源码打包](docs/SOURCE_PACKAGE.md) · [安全说明](SECURITY.md) · [贡献者](CONTRIBUTORS.md) · [许可状态](LICENSE_STATUS.md) · [第三方许可](THIRD_PARTY_NOTICES.md)
