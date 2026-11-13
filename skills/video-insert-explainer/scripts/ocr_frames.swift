// Text recognition (macOS Vision) over a directory of frame images.
// usage: swift ocr_frames.swift <dir> [lang,lang]   (default ja-JP,en-US)
// prints one line per recognized text: <file> \t <text> \t <x> \t <y> \t <w> \t <h>
// with the box in pixels of the image, origin top-left (Vision's own boxes are normalized, origin bottom-left).
import AppKit
import Foundation
import Vision

let args = CommandLine.arguments
let dir = args[1]
let langs = args.count > 2 ? args[2].split(separator: ",").map(String.init) : ["ja-JP", "en-US"]
let files = try! FileManager.default.contentsOfDirectory(atPath: dir)
    .filter { $0.hasSuffix(".jpg") || $0.hasSuffix(".png") }.sorted()
for f in files {
    guard let img = NSImage(contentsOfFile: dir + "/" + f),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    let w = Double(cg.width), h = Double(cg.height)
    let req = VNRecognizeTextRequest()
    req.recognitionLanguages = langs
    req.recognitionLevel = .accurate
    try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    for obs in req.results ?? [] {
        guard let text = obs.topCandidates(1).first?.string else { continue }
        let b = obs.boundingBox
        let x = b.minX * w, y = (1 - b.maxY) * h
        print("\(f)\t\(text)\t\(Int(x))\t\(Int(y))\t\(Int(b.width * w))\t\(Int(b.height * h))")
    }
}
