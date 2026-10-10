// Person matte for a video range using Apple Vision (on-device, no download).
//   swift segment.swift <video> <start_s> <end_s> <fps> <outdir> [scale]
// Writes <outdir>/<frameindex>.png (8-bit grey, frame index = round(t*fps) of the whole video), white = person.
// scale (default 0.5) renders the matte at half resolution; the renderer upscales + feathers it. Speed ~40-80 fps on Apple silicon.
import AVFoundation
import Vision
import CoreImage
import ImageIO
import UniformTypeIdentifiers

let args = CommandLine.arguments
guard args.count >= 6 else { fputs("usage: segment.swift video start end fps outdir [scale]\n", stderr); exit(1) }
let url = URL(fileURLWithPath: args[1]); let start = Double(args[2])!; let end = Double(args[3])!; let fps = Double(args[4])!
let outDir = URL(fileURLWithPath: args[5]); let scale = args.count > 6 ? Double(args[6])! : 0.5
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

let asset = AVURLAsset(url: url)
guard let track = asset.tracks(withMediaType: .video).first else { fputs("no video track\n", stderr); exit(1) }
let reader = try! AVAssetReader(asset: asset)
reader.timeRange = CMTimeRange(start: CMTime(seconds: start, preferredTimescale: 600), end: CMTime(seconds: end, preferredTimescale: 600))
let output = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
output.alwaysCopiesSampleData = false
reader.add(output); reader.startReading()

let request = VNGeneratePersonSegmentationRequest()
request.qualityLevel = (CommandLine.arguments.count > 7 && CommandLine.arguments[7] == "accurate") ? .accurate : .balanced
request.outputPixelFormat = kCVPixelFormatType_OneComponent8
let ctx = CIContext(options: [.useSoftwareRenderer: false])
let size = track.naturalSize.applying(track.preferredTransform)
let W = Int(abs(size.width) * scale), H = Int(abs(size.height) * scale)
var n = 0, lastIdx = -1
while let sb = output.copyNextSampleBuffer() {
    let t = CMSampleBufferGetPresentationTimeStamp(sb).seconds
    let idx = Int((t * fps).rounded())
    if idx == lastIdx { continue }
    lastIdx = idx
    guard let pb = CMSampleBufferGetImageBuffer(sb) else { continue }
    let handler = VNImageRequestHandler(cvPixelBuffer: pb, options: [:])
    do { try handler.perform([request]) } catch { fputs("vision error \(error)\n", stderr); continue }
    guard let mask = request.results?.first?.pixelBuffer else { continue }
    var img = CIImage(cvPixelBuffer: mask)
    let sx = CGFloat(W) / img.extent.width, sy = CGFloat(H) / img.extent.height
    img = img.transformed(by: CGAffineTransform(scaleX: sx, y: sy))
    guard let cg = ctx.createCGImage(img, from: CGRect(x: 0, y: 0, width: W, height: H)) else { continue }
    let dst = outDir.appendingPathComponent(String(format: "%05d.png", idx))
    if let d = CGImageDestinationCreateWithURL(dst as CFURL, UTType.png.identifier as CFString, 1, nil) {
        CGImageDestinationAddImage(d, cg, nil); CGImageDestinationFinalize(d); n += 1
    }
}
print("mattes: \(n) frames, \(W)x\(H), \(start)-\(end)s")
