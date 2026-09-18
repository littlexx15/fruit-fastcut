param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& $Python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $Python -m PyInstaller --noconfirm --clean --onedir --console --name FruitFastCut --hidden-import 混剪工具 --collect-all cv2 --collect-binaries onnxruntime --exclude-module torch --exclude-module transformers --exclude-module onnx --exclude-module scipy --exclude-module matplotlib --copy-metadata numpy --copy-metadata opencv-python-headless --add-data 'prep_clips.py;.' --add-data 'batch_cut.py;.' --add-data 'face_detection_yunet.onnx;.' --add-data 'licenses;licenses' launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Copy-Item README.md,THIRD_PARTY_NOTICES.md dist/FruitFastCut/
if (Test-Path models/siglip-base/vision.onnx) {
    Copy-Item models dist/FruitFastCut/models -Recurse -Force
} else {
    Write-Warning 'No models/siglip-base bundle: fruit sound recognition will be unavailable.'
}
Compress-Archive -Path dist/FruitFastCut -DestinationPath dist/FruitFastCut-windows-x64.zip -Force
