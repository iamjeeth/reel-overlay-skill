import AVFoundation; import ImageIO; import UniformTypeIdentifiers
let a = AVURLAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
let g = AVAssetImageGenerator(asset: a); g.appliesPreferredTrackTransform = true
g.requestedTimeToleranceBefore = .zero; g.requestedTimeToleranceAfter = .zero
let img = try! g.copyCGImage(at: CMTime(seconds: Double(CommandLine.arguments[2])!, preferredTimescale: 600), actualTime: nil)
let d = CGImageDestinationCreateWithURL(URL(fileURLWithPath: CommandLine.arguments[3]) as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(d, img, nil); CGImageDestinationFinalize(d); print(img.width, img.height, img.colorSpace?.name ?? "")
