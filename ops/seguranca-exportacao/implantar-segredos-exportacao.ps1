# Implantação dos segredos das exportações (dre-export e faturamento-export) — rodado pela TATIANA, fase a fase.
#
# Por que: hoje qualquer pessoa com a chave pública (anon) do Supabase lê os DREs, o faturamento e, pelo
# faturamento-export, qualquer e-mail da caixa. A branch fix/export-auth exige um segredo próprio por consumidor
# e só devolve o relatório de faturamento.
#
# Os segredos são gerados AQUI, gravados direto no destino e nunca impressos na tela.
#
# Onde mora o quê: este roteiro e os patches ficam em AGENTE-I.A\ops\seguranca-exportacao (permanente).
# O código corrigido está nas branches: fix/export-auth (Produtividade) e fix/export-secret-header (Torre).
#
# Uso (PowerShell, a partir de qualquer pasta):
#   .\implantar-segredos-exportacao.ps1 -Fase 1   # gera e grava os segredos + liga a transição (nada quebra)
#   .\implantar-segredos-exportacao.ps1 -Fase 2   # publica as 2 funções (a partir desta branch)
#   .\implantar-segredos-exportacao.ps1 -Fase 3   # aplica os ajustes nos consumidores (Torre e dre-bridge)
#   .\implantar-segredos-exportacao.ps1 -Fase 4   # desliga a transição: só quem tem segredo passa
#   .\implantar-segredos-exportacao.ps1 -Fase 5   # confere: chave pública sozinha tem de receber 401
# Entre a fase 3 e a 4: atualizar o dp-vision no Lovable (instrução impressa na fase 1).

param([Parameter(Mandatory = $true)][ValidateRange(1, 5)][int]$Fase)

$ErrorActionPreference = "Stop"
$ProjectRef = "isxmcpobhzzhwfnaozsr"
$ProdutividadeRepo = "C:\Plataforma de Produtividade — Design System\tati-command-deck-main\tati-command-deck-main"
$DeployDir = Join-Path $env:LOCALAPPDATA "sal-os\deploy-export-auth"    # checkout fixo da branch fix/export-auth
$TorreRepo = "C:\Projeto ClaudeCode\Torre-de-Controle"
$TorreEnv = Join-Path $TorreRepo ".env"
$DreBridge = "C:\Projeto ClaudeCode\dre-bridge"
$PatchPush = Join-Path $PSScriptRoot "dre-bridge-proposta\baixar_dres_local.patch"
$PatchSegredo = Join-Path $PSScriptRoot "dre-bridge-proposta\baixar_dres_local.export-secret.patch"
$TorreCommit = "19f7a3e"   # fix(faturamento): enviar o segredo próprio da Torre

function Novo-Segredo {
    $bytes = New-Object byte[] 48
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_").TrimEnd("=")
}

switch ($Fase) {
    1 {
        if ((Test-Path $TorreEnv) -and (Select-String -Path $TorreEnv -Pattern "^FATURAMENTO_EXPORT_SECRET=" -Quiet)) {
            throw "FATURAMENTO_EXPORT_SECRET já existe no .env da Torre: fase 1 já foi feita. Nada alterado."
        }
        $torre = Novo-Segredo; $dpvision = Novo-Segredo; $dreLocal = Novo-Segredo
        # transição ligada: consumidores antigos seguem funcionando até a fase 4
        supabase secrets set --project-ref $ProjectRef "EXPORT_SECRET_TORRE=$torre" "EXPORT_SECRET_DPVISION=$dpvision" "EXPORT_SECRET_DRE_LOCAL=$dreLocal" "EXPORT_ALLOW_LEGACY_ANON=true" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "supabase secrets set falhou (rode 'supabase login' antes). Nada gravado nos consumidores." }
        $precisaQuebra = (Test-Path $TorreEnv) -and -not ((Get-Content $TorreEnv -Raw) -match "\n$")
        if ($precisaQuebra) { Add-Content -Path $TorreEnv -Value "" -Encoding UTF8 }
        Add-Content -Path $TorreEnv -Value "FATURAMENTO_EXPORT_SECRET=$torre" -Encoding UTF8
        [Environment]::SetEnvironmentVariable("EXPORT_SECRET_DRE_LOCAL", $dreLocal, "User")   # tarefa agendada roda com seu usuário
        Set-Clipboard -Value $dpvision
        Remove-Variable torre, dpvision, dreLocal
        Write-Host "Fase 1 ok: 3 segredos gravados no Supabase; Torre (.env) e dre-bridge (variável de usuário) configurados."
        Write-Host "O segredo do dp-vision está na ÁREA DE TRANSFERÊNCIA: no Lovable do dp-vision, crie o secret EXPORT_SECRET_DPVISION"
        Write-Host "com esse valor e faça a função importar-dres enviar o header 'x-export-secret: <valor>' ao dre-export."
        Write-Host "Depois de colar, limpe a área de transferência (copie qualquer outro texto). Próximo: -Fase 2."
    }
    2 {
        if (-not (Test-Path $DeployDir)) {   # checkout da branch corrigida, fora da sua pasta de trabalho
            git -C $ProdutividadeRepo worktree add $DeployDir fix/export-auth
            if ($LASTEXITCODE -ne 0) { throw "não consegui preparar o checkout de fix/export-auth em $DeployDir" }
        }
        Push-Location $DeployDir
        try {
            supabase functions deploy dre-export --project-ref $ProjectRef
            if ($LASTEXITCODE -ne 0) { throw "deploy do dre-export falhou" }
            supabase functions deploy faturamento-export --project-ref $ProjectRef
            if ($LASTEXITCODE -ne 0) { throw "deploy do faturamento-export falhou" }
        } finally { Pop-Location }
        Write-Host "Fase 2 ok: funções publicadas com a trava (transição ainda ligada). Próximo: -Fase 3."
    }
    3 {
        git -C $TorreRepo cherry-pick $TorreCommit
        if ($LASTEXITCODE -ne 0) { throw "cherry-pick na Torre falhou: resolva ou rode 'git -C `"$TorreRepo`" cherry-pick --abort'." }
        # patch.exe vem com o Git for Windows: acha a instalação pelo próprio git
        $gitRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (git --exec-path)))
        $patchExe = Join-Path $gitRoot "usr\bin\patch.exe"
        if (-not (Test-Path $patchExe)) { throw "patch.exe não encontrado em $patchExe" }
        Copy-Item (Join-Path $DreBridge "baixar_dres_local.py") (Join-Path $DreBridge "baixar_dres_local.py.bak-antes-seguranca")
        & $patchExe -d $DreBridge -p1 -i $PatchSegredo
        if ($LASTEXITCODE -ne 0) { throw "patch do segredo no dre-bridge falhou (backup .bak-antes-seguranca ao lado)." }
        Write-Host "Fase 3 ok: Torre e dre-bridge enviam o segredo. (O patch que tira o push automático é separado:"
        Write-Host "  $PatchPush — ver PROPOSTA.md.) Atualize o dp-vision no Lovable; depois -Fase 4."
    }
    4 {
        supabase secrets unset --project-ref $ProjectRef EXPORT_ALLOW_LEGACY_ANON | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "não consegui desligar a transição" }
        Write-Host "Fase 4 ok: sem segredo, as exportações recusam. Próximo: -Fase 5 (conferência)."
    }
    5 {
        $anon = $env:SUPABASE_ANON_PRODUTIVIDADE
        if (-not $anon) { throw "defina `$env:SUPABASE_ANON_PRODUTIVIDADE com a chave PÚBLICA (anon) da Produtividade só nesta janela e rode de novo." }
        foreach ($fn in "dre-export", "faturamento-export") {
            try {
                Invoke-RestMethod -Method Post -Uri "https://$ProjectRef.supabase.co/functions/v1/$fn" -Headers @{ Authorization = "Bearer $anon" } -ContentType "application/json" -Body '{"action":"list"}' | Out-Null
                Write-Host "FALHA: $fn respondeu à chave pública sozinha. Rode -Fase 4 de novo e verifique o deploy." -ForegroundColor Red
            } catch {
                $code = $_.Exception.Response.StatusCode.value__
                if ($code -eq 401) { Write-Host "ok: $fn recusou a chave pública sozinha (401)." -ForegroundColor Green }
                else { Write-Host "atenção: $fn respondeu $code (esperado 401)." -ForegroundColor Yellow }
            }
        }
        Write-Host "Confira também que a Torre (faturamento diário), o dre-bridge (10h) e o dp-vision seguem funcionando."
    }
}
