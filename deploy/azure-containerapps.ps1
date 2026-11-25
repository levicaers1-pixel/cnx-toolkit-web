<#
.SYNOPSIS
  Zet de CNX Toolkit (web) op Azure Container Apps, publiek en zonder login, of werkt een bestaande installatie bij.

.DESCRIPTION
  Maakt (als ze nog niet bestaan) een resourcegroep, een Container Apps-omgeving zonder Log Analytics en een
  container-app met het image van GHCR. De app schaalt naar nul als niemand ze gebruikt (zo blijf je normaal binnen
  het gratis maandelijkse tegoed) en draait nooit meer dan een container (de sessies leven in het geheugen).
  Opnieuw uitvoeren met een andere -Versie werkt de app bij. Zie docs/AZURE.md.

.EXAMPLE
  .\deploy\azure-containerapps.ps1                  # eerste keer, versie 0.2.2
  .\deploy\azure-containerapps.ps1 -Versie 0.2.0    # bijwerken naar een nieuwe versie
  .\deploy\azure-containerapps.ps1 -Domein cnx.voorbeeld.be   # eigen domein met gratis certificaat
  .\deploy\azure-containerapps.ps1 -Proef          # toont enkel de az-commando's, voert niets uit
#>
param(
    [string]$Naam = "cnx-toolkit",
    [string]$ResourceGroup = "rg-cnx-toolkit",
    [string]$Regio = "northeurope",    # West Europe nam in november 2026 geen nieuwe klanten aan
    [string]$Versie = "0.2.2",        # altijd een vaste versie: met "latest" maakt Container Apps geen nieuwe revisie
    [string]$Image = "ghcr.io/levicaers1-pixel/cnx-toolkit-web",
    [string]$Abonnement = "",
    [string]$Domein = "",              # eigen domein koppelen met een gratis certificaat, bv. cnx.voorbeeld.be (zie docs/AZURE.md)
    [string[]]$ExtraHosts = @(),       # extra hostnamen die de app aanvaardt (het eigen domein komt er vanzelf bij)
    [switch]$Pilot,                    # een pilotcode instellen (gevraagd, niet getoond; bewaard als geheim in Azure)
    [switch]$GeenPilot,                # de pilotcode weghalen: de app is weer open voor iedereen
    [switch]$Proef
)
if ($Pilot -and $GeenPilot) { throw "Kies -Pilot of -GeenPilot, niet allebei." }

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
$omgevingsdomein = Invoke-Az containerapp env show --name $Omgeving --resource-group $ResourceGroup --query "properties.defaultDomain" --output tsv
$fqdn = "$Naam.$omgevingsdomein"
$Domein = $Domein.Trim().ToLower().TrimEnd(".")
if ($Domein -and $Domein -notmatch '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$') { throw "Domein '$Domein' is geen geldige hostnaam." }
# Domeinen die al aan de app gekoppeld zijn, blijven toegelaten, ook als je -Domein deze keer niet meegeeft.
$gekoppeld = @()
if (-not $Proef -and (Test-Az containerapp show --name $Naam --resource-group $ResourceGroup)) {
    $gekoppeld = @(Invoke-Az containerapp show --name $Naam --resource-group $ResourceGroup `
        --query "properties.configuration.ingress.customDomains[].name" --output tsv | Where-Object { $_ })
}
$hosts = (@($fqdn) + $gekoppeld + @($Domein) + $ExtraHosts | Where-Object { $_ } | Select-Object -Unique) -join ","

$volledigImage = "${Image}:$Versie"
Write-Stap "Container-app $Naam met $volledigImage"
if (Test-Az containerapp show --name $Naam --resource-group $ResourceGroup) {
    Invoke-Az containerapp update --name $Naam --resource-group $ResourceGroup --image $volledigImage `
        --min-replicas 0 --max-replicas 1 --set-env-vars "CNX_HOSTS=$hosts" "CNX_PROXY=1" --output none | Out-Null
    Write-Host "Bijgewerkt."
} else {
    Invoke-Az containerapp create --name $Naam --resource-group $ResourceGroup --environment $Omgeving `
        --image $volledigImage --ingress external --target-port 8080 `
        --cpu 0.25 --memory 0.5Gi --min-replicas 0 --max-replicas 1 `
        --env-vars "CNX_HOSTS=$hosts" "CNX_PROXY=1" --output none | Out-Null
    if (-not $Proef) { Write-Host "Aangemaakt." }
}

if ($Pilot) {
    Write-Stap "Pilotcode instellen"
    if ($Proef) {
        Write-Host "  az containerapp secret set --name $Naam --resource-group $ResourceGroup --secrets pilotcode=***" -ForegroundColor DarkGray
        Write-Host "  az containerapp update --name $Naam --resource-group $ResourceGroup --set-env-vars CNX_PILOTCODE=secretref:pilotcode CNX_PILOT_GEZET=<tijd>" -ForegroundColor DarkGray
    } else {
        $veilig = Read-Host "Pilotcode (wordt niet getoond)" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($veilig)
        try { $code = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        if ($code.Length -lt 8) { throw "Kies een pilotcode van minstens 8 tekens." }
        # Rechtstreeks via az, niet via Invoke-Az: zo komt de code nooit in een foutmelding of op het scherm.
        $ErrorActionPreference = "Continue"
        $uit = & az containerapp secret set --name $Naam --resource-group $ResourceGroup --secrets "pilotcode=$code" --only-show-errors --output none 2>&1
        $gelukt = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = "Stop"
        $code = $null
        if (-not $gelukt) { throw "Mislukt: de pilotcode als geheim bewaren.`n" + (($uit | ForEach-Object { "$_" }) -join "`n") }
        # Een nieuwe waarde voor CNX_PILOT_GEZET maakt een nieuwe revisie, zodat de app de (nieuwe) code ook leest.
        Invoke-Az containerapp update --name $Naam --resource-group $ResourceGroup `
            --set-env-vars "CNX_PILOTCODE=secretref:pilotcode" "CNX_PILOT_GEZET=$(Get-Date -Format yyyyMMddHHmmss)" --output none | Out-Null
        Write-Host "Ingesteld. Bezoekers zien eerst een pagina die om de pilotcode vraagt."
    }
}
if ($GeenPilot) {
    Write-Stap "Pilotcode weghalen"
    Invoke-Az containerapp update --name $Naam --resource-group $ResourceGroup --remove-env-vars CNX_PILOTCODE CNX_PILOT_GEZET --output none | Out-Null
    if (Test-Az containerapp secret show --name $Naam --resource-group $ResourceGroup --secret-name pilotcode) {
        Invoke-Az containerapp secret remove --name $Naam --resource-group $ResourceGroup --secret-names pilotcode --output none | Out-Null
    }
    if (-not $Proef) { Write-Host "Weggehaald. De app is weer open voor iedereen." }
}

$domeinKlaar = $false
if ($Domein) {
    Write-Stap "Eigen domein $Domein"
    $verificatie = Invoke-Az containerapp env show --name $Omgeving --resource-group $ResourceGroup `
        --query "properties.customDomainConfiguration.customDomainVerificationId" --output tsv
    # Rechtstreeks bij publieke resolvers vragen (zoals Azure zelf doet): de resolver van Windows houdt een
    # 'bestaat niet' van daarnet nog een tijd in zijn cache. Zonder internet-DNS valt het terug op die van Windows.
    $cnameOk = $false; $txtOk = $false
    if (-not $Proef) {
        foreach ($server in @("1.1.1.1", "8.8.8.8", $null)) {
            $extra = @{ Name = $Domein; Type = "CNAME"; DnsOnly = $true; QuickTimeout = $true; ErrorAction = "SilentlyContinue" }
            if ($server) { $extra.Server = $server }
            $cname = (Resolve-DnsName @extra | Where-Object { $_.Type -eq "CNAME" } | Select-Object -First 1).NameHost
            $extra.Name = "asuid.$Domein"; $extra.Type = "TXT"
            $txt = @(Resolve-DnsName @extra | ForEach-Object { $_.Strings })
            if ($cname -and $cname.TrimEnd(".").ToLower() -eq $fqdn.ToLower()) { $cnameOk = $true }
            if ($txt -contains $verificatie) { $txtOk = $true }
            if ($cnameOk -and $txtOk) { break }
        }
    }
    if (-not $Proef -and (-not $cnameOk -or -not $txtOk)) {
        Write-Host "Maak eerst deze twee DNS-records bij de beheerder van het domein (zonder proxy, bv. bij Cloudflare 'DNS only'):" -ForegroundColor Yellow
        Write-Host ("  {0,-6} {1,-40} {2}" -f "Type", "Naam", "Waarde")
        Write-Host ("  {0,-6} {1,-40} {2}" -f "CNAME", $Domein, $fqdn) -ForegroundColor $(if ($cnameOk) { "Green" } else { "White" })
        Write-Host ("  {0,-6} {1,-40} {2}" -f "TXT", "asuid.$Domein", $verificatie) -ForegroundColor $(if ($txtOk) { "Green" } else { "White" })
        Write-Host "Voer het script daarna opnieuw uit met -Domein $Domein. DNS-wijzigingen kunnen enkele minuten tot een uur duren."
    } else {
        if (-not ($gekoppeld -contains $Domein)) {
            Invoke-Az containerapp hostname add --name $Naam --resource-group $ResourceGroup --hostname $Domein --output none | Out-Null
        }
        Write-Host "Gratis certificaat aanvragen en koppelen (dit kan enkele minuten duren)..."
        Invoke-Az containerapp hostname bind --name $Naam --resource-group $ResourceGroup --hostname $Domein `
            --environment $Omgeving --validation-method CNAME --output none | Out-Null
        $domeinKlaar = -not $Proef
    }
}

$url = if ($domeinKlaar) { "https://$Domein" } else { "https://$fqdn" }
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
