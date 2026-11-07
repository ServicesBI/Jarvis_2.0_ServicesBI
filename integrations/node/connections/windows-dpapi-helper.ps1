$ErrorActionPreference = 'Stop'

try {
    Add-Type -AssemblyName System.Security
    $inputText = [Console]::In.ReadToEnd()
    $request = $inputText | ConvertFrom-Json

    if ($request.action -eq 'protect') {
        $plainBytes = [Text.Encoding]::UTF8.GetBytes([string]$request.value)
        try {
            $protectedBytes = [Security.Cryptography.ProtectedData]::Protect(
                $plainBytes,
                $null,
                [Security.Cryptography.DataProtectionScope]::CurrentUser
            )
            [Console]::Out.Write([Convert]::ToBase64String($protectedBytes))
        }
        finally {
            if ($null -ne $plainBytes) { [Array]::Clear($plainBytes, 0, $plainBytes.Length) }
        }
        exit 0
    }

    if ($request.action -eq 'unprotect') {
        $protectedBytes = [Convert]::FromBase64String([string]$request.value)
        $plainBytes = [Security.Cryptography.ProtectedData]::Unprotect(
            $protectedBytes,
            $null,
            [Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        try {
            [Console]::Out.Write([Text.Encoding]::UTF8.GetString($plainBytes))
        }
        finally {
            if ($null -ne $plainBytes) { [Array]::Clear($plainBytes, 0, $plainBytes.Length) }
        }
        exit 0
    }

    exit 2
}
catch {
    exit 1
}
