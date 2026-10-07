# Mac 固定签名与钥匙串访问

客户端使用本机长期自签名代码证书，替代 `codesign --sign -`。Bundle ID 固定为 `com.yuwk.personal-data-hub`，指定要求同时匹配此 ID 和证书指纹，用于客户端与凭据助手的相互验证。这符合 [Apple 对指定要求及版本更新的说明](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Procedures/Procedures.html)。客户端和助手均启用 hardened runtime。

登录钥匙串还有独立的 partition 校验；本机自签名代码仍按 CDHash 分类，[Apple 的实现](https://github.com/apple-oss-distributions/Security/blob/main/securityd/src/clientid.cpp)明确采用此行为。因此只固定证书不足以保证升级免密码。客户端通过一个固定、不随界面更新重编译的访问助手调用 Keychain，钥匙串许可绑定到助手的固定二进制。没有删除 partition 限制、放开其他应用访问，或改动其他钥匙串条目。

首次构建由 `apps/mac-client/signing.swift` 创建 3072 位 RSA 代码签名证书，有效期十年。身份保存在 Mac 的 `~/Library/Application Support/PersonalDataHub/Signing/`：目录 700，文件 600。私钥导入独立签名钥匙串后删除临时 PEM 和 PKCS#12；此钥匙串仅授权系统 `codesign` 使用签名密钥。构建通过 Security API 在内存传入随机钥匙串密码，签名后重新锁定，不使用登录密码，不更改登录钥匙串搜索列表或系统证书信任。

每次安装继续运行 `python3 apps/mac-client/install.py`，自动复用同一证书，校验签名后安装并保留上一版。缺少身份、钥匙串损坏或签名校验失败时停止，不退回临时签名；已经安装证书版本的 Mac 丢失签名目录时也不会自动生成新身份。

统一应用 0.3.1 将采集环境作为 `Contents/Resources/collection.tar.gz` 封装并纳入外层签名；安装器先验证完整应用和资源 SHA-256，再解压到私有 Application Support 版本目录。原生读取器保持其原始字节，避免因重新签名改变微信读取行为。包内仅有固定凭据助手的代码副本和公开校验信息，不包含 Signing 私钥或任何 Keychain 凭据；本机安装继续校验并使用原获准助手，升级不替换它。登录启动使用 `SMAppService.mainApp`，Bundle ID 与指定要求保持一致。

助手源码在 `apps/mac-client/credential-reader/main.swift`；首次编译明确使用 macOS 13.0 部署目标，安装到 `~/Library/Application Support/PersonalDataHub/Personal Data Hub Credentials.app`。身份及源码/二进制 SHA-256 保存在 `Signing/credential-reader.json`。后续构建只验证并保留原文件，不重新签名；源码、身份或二进制不一致时停止，助手本身升级须显式迁移。备份整个 Signing 目录和此助手应用，不能提交 Git 或放进公开构建产物。

首次迁移时运行已安装客户端的 `--keychain-prepare`，macOS 对归档与 Google 两项凭据要求“始终允许”，授权固定助手访问。此操作不重新授权 Google、不复制 NAS 刷新凭据，也不把凭据导出到文件。后续界面版本复用助手的许可。助手只允许同一证书签名、指定 Bundle ID 的客户端调用，且只支持归档与 Google 两项；客户端也验证助手的证书及标识。数据通过子进程私有管道传递，不出现在参数或日志。手动锁定登录钥匙串、撤销访问许可或升级助手，仍按系统规则处理。

在 Mac 执行 `python3 checks/mac-signing-smoke.py` 验证：先检查已安装应用，再复制一个私有临时更新候选、修改版本并使用同一证书签名；要求两份应用的 CDHash 不同、指定要求相同，且两份均在禁止授权弹窗的模式下读取真实归档及 Google 凭据；助手 SHA-256 必须不变，普通脚本调用必须被拒绝且不返回数据。测试不打印、导出或改写凭据，完成后删除候选。`--keychain-smoke` 可单独检查读取；`--keychain-roundtrip-smoke` 在禁止弹窗时回写完全相同的凭据字节并校验一致；`--google-read-smoke` 验证实时 Google 查询，不做业务写入。

`python3 checks/mac-signing-isolated-smoke.py` 仅使用临时钥匙串和合成凭据验证指定要求，不能替代登录钥匙串的 partition 校验和真实凭据跨版本验收。

本机自签名用于当前 Mac 的持续开发和更新；公开分发所需的 Developer ID 与公证另行处理。
