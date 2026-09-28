# Script de démarrage n8n avec mot de passe FIXE
# Usage : double-cliquer sur ce fichier OU taper : .\start-n8n.ps1
# Le mot de passe ne changera JAMAIS tant que tu utilises ce script.

$env:N8N_BASIC_AUTH_ACTIVE = "true"
$env:N8N_BASIC_AUTH_USER = "admin@digiart.local"
$env:N8N_BASIC_AUTH_PASSWORD = "DigiArt2025!"
$env:GENERIC_TIMEZONE = "Africa/Tunis"
$env:N8N_PORT = "5678"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   DigiArt n8n Automation Server" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  URL     : http://localhost:5678" -ForegroundColor Green
Write-Host "  Login   : admin@digiart.local" -ForegroundColor Green
Write-Host "  Password: DigiArt2025!" -ForegroundColor Green
Write-Host ""
Write-Host "  Pour arreter : appuie CTRL+C" -ForegroundColor Yellow
Write-Host ""

npx n8n
