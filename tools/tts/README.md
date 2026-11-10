# Text-to-speech

Narration is rendered locally with [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) 0.6.1
and the Kokoro v1.0 model files (`kokoro-v1.0.onnx`, `voices-v1.0.bin`) from the official
kokoro-onnx GitHub release `model-files-v1.0`. The prereqs phase downloads them into `models/`
(git-ignored). Voice `bm_george`, lang `en-us`, speed 1.0.

Licences: kokoro-onnx is MIT; the Kokoro-82M model weights are Apache-2.0. The voice is
AI-generated, so uploads set `containsSyntheticMedia: true`.
