# 音频准备与维护

标准音直接采用cmguo/PinYinSound，按[ADR-0008](../adr/0008-trusted-standard-audio.md)信任该来源。产品只有学生和家长，无审音台、审核者、两人确认或待审状态。

## 安装标准音

```sh
npm run prepare:pinyin
```

显式下载固定提交62453b2a5ca6873eac1f4293b6e9794715d0fc8a的归档，校验归档与逐文件SHA-256；Mac本机解码、检查时长和非静音后安装到private/pinyinsound。201个课程目标映射保存在content/pinyin-source.json，去重后179份MP3。ü的显示与上游v文件名分开；整体认读目标的示范声调明确登记，不在运行时猜文件名。

已有固定归档时可离线安装：

```sh
npm run prepare:pinyin -- --archive /绝对路径/source.zip
```

需要停用整个来源时使用`npm run prepare:pinyin -- --disable`；保留文件，不删除家庭数据。重新准备可恢复。正常启动不下载声音；文件损坏/目标映射变化会使对应资源不可用，重新准备可修复文件。

## 中文指令与整课录音

`npm run prepare:voice -- --source '/Users/chad/Documents/1汉语拼音音频'`生成中文操作语音、导入原13课录音。中文TTS不读拼音，长录音不替代单音。资源各自通过本机配对接口播放。

## 验证与维护

运行`uv run --locked python -m scripts.validate_audio_resources`检查全部标准音、中文指令和课程录音的实际文件与摘要。`npm run test:e2e:product`验证浏览器真实声音播放和听辨闭环；不存在审核通过才可播放的步骤。

外部录音不随MIT源码公开，来源与许可事实保存在开发文档。曾经裁切的私有候选和原文件保持原样，当前运行时不再读取它们；旧制作工具可从Git历史查阅。
