# 音频准备与维护

标准音直接采用cmguo/PinYinSound，按[ADR-0008](../adr/0008-trusted-standard-audio.md)信任该来源。产品只有学生和家长，无审音台、审核者、两人确认或待审状态。

## 安装标准音

```sh
npm run prepare:pinyin
```

显式下载固定提交62453b2a5ca6873eac1f4293b6e9794715d0fc8a的归档，校验归档与逐文件SHA-256；Mac本机解码、检查时长和非静音后安装到private/pinyinsound。205个课程目标映射保存在content/pinyin-source.json，去重后183份MP3。ü的显示与上游v文件名分开；整体认读目标的示范声调明确登记，不在运行时猜文件名。

已有固定归档时可离线安装：

```sh
npm run prepare:pinyin -- --archive /绝对路径/source.zip
```

需要停用整个来源时使用`npm run prepare:pinyin -- --disable`；保留文件，不删除家庭数据。重新准备可恢复。正常启动不下载声音；文件损坏/目标映射变化会使对应资源不可用，重新准备可修复文件。

## 中文指令与整课录音

现行普通开发者运行 `./run.sh` 即可使用已提交的13份课程MP3与全部开源中文引导，不再手工提供源目录或安装Tingting。中文素材由Kokoro-82M-v1.1-zh本地生成，维护者运行 `npm run prepare:voice` 校验模型后重生成；参数/摘要见content/voice-build.json。旧Mac声音准备脚本仅保留测试及私人素材兼容，不进入发布素材。中文TTS不替代固定PinYinSound单音，原长录音仍保留独立来源。家庭/访客接口均只按登记ID读取。

## 验证与维护

运行`uv run --locked python -m scripts.validate_audio_resources`检查全部标准音、中文指令和课程录音的实际文件与摘要。`npm run test:e2e:product`验证浏览器真实声音播放和听辨闭环；不存在审核通过才可播放的步骤。

外部录音不随MIT源码公开，来源与许可事实保存在开发文档。曾经裁切的私有候选和原文件保持原样，当前运行时不再读取它们；旧制作工具可从Git历史查阅。
