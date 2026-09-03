$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'H3-Slides - Scegli il modello GGUF locale'
$dialog.Filter = 'Modelli GGUF (*.gguf)|*.gguf'
$dialog.CheckFileExists = $true
$dialog.Multiselect = $false
$dialog.RestoreDirectory = $true
try {
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::WriteLine($dialog.FileName)
    }
} finally { $dialog.Dispose() }
