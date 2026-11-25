<#
.SYNOPSIS
  Zet de CNX Toolkit (web) op Azure Container Apps, publiek en zonder login, of werkt een bestaande installatie bij.

.DESCRIPTION
  Maakt (als ze nog niet bestaan) een resourcegroep, een Container Apps-omgeving zonder Log Analytics en een
  container-app met het image van GHCR. De app schaalt naar nul als niemand ze gebruikt (zo blijf je normaal binnen
  het gratis maandelijkse tegoed) en draait nooit meer dan een container (de sessies leven in het geheugen).
  Opnieuw uitvoeren met een andere -Versie werkt de app bij. Zie docs/AZURE.md.

.EXAMPLE
  .\deploy\azure-containerapps.ps1                  # eerste keer, versie 0.1.1
  .\deploy\azure-containerapps.ps1 -Versie 0.2.0    # bijwerken naar een nieuwe versie
  .\deploy\azure-containerapps.ps1 -Proef          # toont enkel de az-commando's, voert niets uit
#>
param(
    [string]$Naam = "cnx-toolkit",
    [string]$ResourceGroup = "rg-cnx-toolkit",
    [string]$Regio = "westeurope",
    [string]$Versie = "0.1.1",        # altijd een vaste versie: met "latest" maakt Container Apps geen nieuwe revisie
    [string]$Image = "ghcr.io/levicaers1-pixel/cnx-toolkit-web",
    [string]$Abonnement = "",
    [string[]]$ExtraHosts = @(),       # eigen domeinnaam, bv. cnx.voorbeeld.be (zie docs/AZURE.md)
    [switch]$Proef
)

$ErrorActionPreference = "Stop"
$Omgeving = "$Naam-env"

function Invoke-Az {
    # Voert az uit en stopt bij een fout. In proefmodus enkel tonen.
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Argumenten)
    if ($Proef) {
        Write-Host ("  az " + ($Argumenten -join " ")) -ForegroundColor DarkGray
        return "<proef>"
    }
    $ErrorActionPreference = "Continue"      # Windows PowerShell 5.1 maakt van elke stderr-regel van az anders een fout
    $alles = & az @Argumenten --only-show-errors 2>&1
    $fout = ($alles | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } | ForEach-Object { $_.ToString() }) -join "`n"
    $uit = $alles | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }
    if ($LASTEXITCODE -ne 0) {
        $tip = ""
        if ($fout -match "not accepting new customers|locationineligible|LocationNotAvailable|not available in the location|SkuNotAvailable") {
            $tip = "`n`nTip: de regio '$Regio' neemt nu geen nieuwe klanten aan. Probeer een andere Europese regio, bv.:" +
                   "`n  -Regio northeurope   (of swedencentral, francecentral, germanywestcentral)"
        }
        throw "Mislukt: az $($Argumenten -join ' ')`n$fout$tip"
    }
    return $uit
}

function Test-Az {
    # True als het az-commando lukt (om te zien of iets al bestaat). Toont geen fouten.
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Argumenten)
    if ($Proef) { return $false }
    $ErrorActionPreference = "Continue"
    & az @Argumenten --only-show-errors --output none 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Write-Stap($tekst) { Write-Host "`n== $tekst" -ForegroundColor Cyan }

if ($Naam -notmatch '^[a-z][a-z0-9-]{0,30}[a-z0-9]$') {
    throw "Naam '$Naam': enkel kleine letters, cijfers en '-', 2 tot 32 tekens, beginnend met een letter."
}

Write-Stap "Azure CLI en aanmelding nakijken"
if (-not $Proef) {
    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        throw "De Azure CLI ontbreekt. Installeer ze met: winget install -e --id Microsoft.AzureCLI (en open daarna een nieuw venster)."
    }
    if (-not (Test-Az account show)) {
        Write-Host "Nog niet aangemeld bij Azure: er opent een browservenster."
        Invoke-Az login | Out-Null
    }
}
if ($Abonnement) { Invoke-Az account set --subscription $Abonnement | Out-Null }
$abo = Invoke-Az account show --query "name" --output tsv
Write-Host "Abonnement: $abo"

Write-Stap "Uitbreiding containerapp en resource provider"
Invoke-Az extension add --name containerapp --upgrade | Out-Null
Invoke-Az provider register --namespace Microsoft.App --wait | Out-Null

Write-Stap "Resourcegroep $ResourceGroup"
if (Test-Az group show --name $ResourceGroup) {
    # Een resourcegroep is enkel een map: de app mag in een andere regio staan dan de groep zelf.
    Write-Host "Bestaat al."
} else {
    Invoke-Az group create --name $ResourceGroup --location $Regio --output none | Out-Null
}

Write-Host "Regio voor de app: $Regio"

Write-Stap "Container Apps-omgeving $Omgeving"
if (Test-Az containerapp env show --name $Omgeving --resource-group $ResourceGroup) {
    Write-Host "Bestaat al."
} else {
    # Zonder Log Analytics: geen kosten voor logopslag. Live meekijken kan nog met 'az containerapp logs show'.
    Invoke-Az containerapp env create --name $Omgeving --resource-group $ResourceGroup --location $Regio `
        --logs-destination none --output none | Out-Null
}
$domein = Invoke-Az containerapp env show --name $Omgeving --resource-group $ResourceGroup --query "properties.defaultDomain" --output tsv
$fqdn = "$Naam.$domein"
$hosts = (@($fqdn) + $ExtraHosts | Where-Object { $_ }) -join ","

$volledigImage = "${Image}:$Versie"
Write-Stap "Container-app $Naam met $volledigImage"
if (Test-Az containerapp show --name $Naam --resource-group $ResourceGroup) {
    Invoke-Az containerapp update --name $Naam --resource-group $ResourceGroup --image $volledigImage `
        --min-replicas 0 --max-replicas 1 --set-env-vars "CNX_HOSTS=$hosts" --output none | Out-Null
    Write-Host "Bijgewerkt."
} else {
    Invoke-Az containerapp create --name $Naam --resource-group $ResourceGroup --environment $Omgeving `
        --image $volledigImage --ingress external --target-port 8080 `
        --cpu 0.25 --memory 0.5Gi --min-replicas 0 --max-replicas 1 `
        --env-vars "CNX_HOSTS=$hosts" --output none | Out-Null
    if (-not $Proef) { Write-Host "Aangemaakt." }
}

$url = "https://$fqdn"
Write-Stap "Nakijken: $url/gezond"
if ($Proef) {
    Write-Host "Proefmodus: niets aangemaakt. Zonder -Proef komt de app op https://$Naam.<domein van de omgeving>."
    return
}
$ok = $false
for ($i = 1; $i -le 24; $i++) {          # de eerste start (image ophalen) kan even duren
    try {
        $r = Invoke-WebRequest -Uri "$url/gezond" -UseBasicParsing -TimeoutSec 15
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { Start-Sleep -Seconds 5 }
}
if ($ok) {
    Write-Host "`nKlaar. De CNX Toolkit staat op: $url" -ForegroundColor Green
} else {
    Write-Host "`nDe app antwoordt nog niet op $url/gezond. Kijk de logs na:" -ForegroundColor Yellow
    Write-Host "  az containerapp logs show --name $Naam --resource-group $ResourceGroup --follow"
}
