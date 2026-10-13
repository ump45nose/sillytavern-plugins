# M1 模型锁定记录（2026-09-26）

| 模型 | 本地文件 | SHA-256 | 来源 |
|---|---|---|---|
| Silero VAD | `models/silero_vad.onnx` | `9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6` | [sherpa-onnx 官方发布](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models)，与 GitHub release asset digest 一致 |
| SenseVoice int8 压缩包 | `models/sensevoice-int8-2024-07-17.tar.bz2` | `7d1efa2138a65b0b488df37f8b89e3d91a60676e416f515b952358d83dfd347e` | 同上，与 GitHub release asset digest 一致 |
| SenseVoice int8 模型 | `models/sensevoice-int8-2024-07-17/model.int8.onnx` | `c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51` | 从已核验压缩包解出 |
| SenseVoice tokens | `models/sensevoice-int8-2024-07-17/tokens.txt` | `f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc` | 从已核验压缩包解出 |
| CAM++ 中文说话人 | `models/campplus_zh.onnx` | `f682b514c05d947ee3fa91cd6ec6c5c7543479a128373fa29b1faedccd21fd11` | [sherpa-onnx 官方发布](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models)，官方资产暂无 digest；只验证了下载长度、ONNX 可加载与 192 维向量计算 |

下载链路使用镜像代理，模型字节在使用前按官方公开 digest 校验；CAM++ 因官方未提供 digest，保留来源完整性待复核项。运行时路径为 `/vol1/1000/plaud-daily/models/`。
