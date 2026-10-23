// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "Nook",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "PersonalHub", targets: ["PersonalHub"])],
    targets: [
        .target(name: "HubKit"),
        .executableTarget(name: "PersonalHub", dependencies: ["HubKit"]),
        .testTarget(name: "HubKitTests", dependencies: ["HubKit"]),
    ],
    swiftLanguageModes: [.v5]
)
