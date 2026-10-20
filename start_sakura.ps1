param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ModelPath
)

$ErrorActionPreference = "Stop"

$ServerExe = "C:\Llama-Sakura\build-cuda\bin\Release\llama-server.exe"
$MetricsScript = Join-Path $PSScriptRoot "metrics.py"
$env:HF_HOME = "C:\Llama-Sakura\hf-cache"

if (-not (Test-Path -LiteralPath $ServerExe -PathType Leaf)) {
    throw "No se encontró llama-server.exe en '$ServerExe'. Edita la variable ServerExe al inicio del script si está en otra ruta."
}

if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
    throw "No se encontró el archivo GGUF local '$ModelPath'. Pasa la ruta de un modelo que ya tengas; este script no descarga modelos."
}

if (-not (Test-Path -LiteralPath $MetricsScript -PathType Leaf)) {
    throw "No se encontró metrics.py junto a este script. Descarga la carpeta completa del proyecto."
}

$MetricsProcess = Start-Process `
    -FilePath "python" `
    -ArgumentList @("-u", "`"$MetricsScript`"") `
    -WorkingDirectory $PSScriptRoot `
    -WindowStyle Hidden `
    -PassThru

try {
    & $ServerExe `
        --model $ModelPath `
        --ctx-size 40000 `
        --n-gpu-layers 99 `
        --flash-attn on `
        --cache-type-k q8_0 `
        --cache-type-v q8_0 `
        --host 0.0.0.0 `
        --port 50002 `
        --metrics

    if ($LASTEXITCODE -ne 0) {
        throw "llama-server terminó con código $LASTEXITCODE."
    }
}
finally {
    if ($MetricsProcess -and -not $MetricsProcess.HasExited) {
        Stop-Process -Id $MetricsProcess.Id -Force
    }
}

