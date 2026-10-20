// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "PersonalDataHub",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "PersonalDataHub", targets: ["PersonalDataHub"])],
    targets: [.executableTarget(name: "PersonalDataHub"), .testTarget(name: "PersonalDataHubTests", dependencies: ["PersonalDataHub"])]
)
