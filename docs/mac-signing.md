# Mac 固定签名与钥匙串访问

客户端使用本机长期自签名代码证书，替代 `codesign --sign -`。Bundle ID 固定为 `com.yuwk.personal-data-hub`，指定要求同时匹配此 ID 和证书指纹，升级不再用二进制 CDHash 作为应用身份。这符合 [Apple 对指定要求及版本更新的说明](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Procedures/Procedures.html)。

首次构建由 `apps/mac-client/signing.swift` 创建 3072 位 RSA 代码签名证书，有效期十年。身份保存在 Mac 的 `~/Library/Application Support/PersonalDataHub/Signing/`：目录 700，文件 600。私钥导入独立签名钥匙串后删除临时 PEM 和 PKCS#12；此钥匙串仅授权系统 `codesign` 使用签名密钥。构建通过 Security API 在内存传入随机钥匙串密码，签名后重新锁定，不使用登录密码，不更改登录钥匙串搜索列表或系统证书信任。

每次安装继续运行 `python3 apps/mac-client/install.py`，自动复用同一证书，校验签名后安装并保留上一版。缺少身份、钥匙串损坏或签名校验失败时停止，不退回临时签名；已经安装证书版本的 Mac 丢失签名目录时也不会自动生成新身份。将整个 Signing 目录纳入 Mac 私有备份，不能提交 Git 或复制到公开构建产物。

由旧临时签名迁移时，macOS 对现有归档与 Google 两项凭据要求一次“始终允许”，将访问许可绑定到新证书。此操作不会重新授权 Google，也不会导出刷新凭据。后续相同证书与 Bundle ID 的版本复用此许可。手动锁定登录钥匙串、撤销应用访问许可或更换证书，仍按系统的钥匙串规则处理。

在 Mac 执行 `python3 checks/mac-signing-smoke.py` 验证：先检查已安装应用，再复制一个私有临时更新候选、修改版本并使用同一证书签名；要求两份应用的 CDHash 不同、指定要求相同，且两份均在禁止授权弹窗的模式下读取归档及 Google 凭据。测试不打印、导出或改写凭据，完成后删除候选。`--keychain-smoke` 也可单独用于升级检查。

`python3 checks/mac-signing-isolated-smoke.py` 使用临时钥匙串和合成凭据，编译两个不同二进制，并以同一证书签名。第二个程序必须在禁止弹窗时读取第一个程序存入的凭据；此测试可在登录钥匙串锁定时验证签名跨版本的访问行为，不触碰真实授权。

本机自签名用于当前 Mac 的持续开发和更新；公开分发所需的 Developer ID 与公证另行处理。
