# =============================================================================
# make.ps1 — Windows PowerShell fallback для тех, у кого не установлен make
# =============================================================================
# Использование: .\make.ps1 up
# Или:           .\make.ps1 tunnel-up
# =============================================================================

param(
    [Parameter(Position=0)]
    [string]$Command = "help",

    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"

# Обработка make-style аргументов: revision msg="create foo" → -msg "create foo"
$namedArgs = @{}
foreach ($arg in $Args) {
    if ($arg -match '^(\w+)=(.*)$') {
        $namedArgs[$Matches[1]] = $Matches[2]
    }
}

function Run-Docker {
    param([string[]]$Args)
    docker @Args
}

function Show-Help {
    Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║  KSR Vector Search v2 — команды (PowerShell версия)        ║" -ForegroundColor Cyan
    Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Использование: .\make.ps1 <command> [args...]" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "━━━ БАЗОВЫЕ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
    Write-Host "  up                Поднять весь стек"
    Write-Host "  down              Остановить стек"
    Write-Host "  restart           Перезапустить стек"
    Write-Host "  ps                Статус контейнеров"
    Write-Host ""
    Write-Host "━━━ ЛОГИ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
    Write-Host "  logs              Все сервисы"
    Write-Host "  logs-api          Только API"
    Write-Host "  logs-celery       Только Celery"
    Write-Host ""
    Write-Host "━━━ ОБНОВЛЕНИЕ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
    Write-Host "  rebuild-api       Пересобрать API (после правок api/app/*.py)"
    Write-Host "  rebuild           Пересобрать ВСЁ"
    Write-Host ""
    Write-Host "━━━ БД ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
    Write-Host "  migrate           Применить миграции"
    Write-Host "  revision <msg>    Создать миграцию"
    Write-Host ""
    Write-Host "━━━ БЭКАП ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
    Write-Host "  backup            Бэкап PostgreSQL"
    Write-Host "  backup-full       Бэкап PostgreSQL + Qdrant"
    Write-Host "  restore <file>    Восстановить из дампа"
    Write-Host ""
    Write-Host "━━━ CLOUDFLARE TUNNEL ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
    Write-Host "  tunnel-up         Запустить cloudflared"
    Write-Host "  tunnel-down       Остановить cloudflared"
    Write-Host "  tunnel-logs       Логи cloudflared"
    Write-Host ""
    Write-Host "━━━ BROWSER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
    Write-Host "  open-site         Открыть сайт"
    Write-Host "  open-admin        Открыть админку"
    Write-Host "  open-flower       Открыть Flower"
    Write-Host ""
    Write-Host "━━━ ОЧИСТКА ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
    Write-Host "  clean             Удалить __pycache__"
    Write-Host "  prune             ⚠️  Удалить ВСЕ ДАННЫЕ"
    Write-Host ""
    Write-Host "📖 Документация: docs/README.md" -ForegroundColor Yellow
}

switch ($Command) {
    "help" { Show-Help }

    "up" {
        Run-Docker compose up -d --build
        Write-Host ""
        Write-Host "✅ Стек поднят:" -ForegroundColor Green
        Write-Host "   🌐 Сайт:    http://localhost:8000"
        Write-Host "   ⚙️  Админка:  http://localhost:8000/admin (admin/admin)"
        Write-Host "   📚 API docs: http://localhost:8000/docs"
        Write-Host "   🌸 Flower:   http://localhost:5555"
        Write-Host ""
        Write-Host "💡 Следующий шаг: .\make.ps1 migrate" -ForegroundColor Yellow
    }

    "down" { Run-Docker compose down }
    "restart" { Run-Docker compose restart }
    "ps" { Run-Docker compose ps }

    "logs" { Run-Docker compose logs -f --tail=100 }
    "logs-api" { Run-Docker compose logs -f api }
    "logs-celery" { Run-Docker compose logs -f celery_worker }
    "logs-worker" { Run-Docker compose logs -f celery_worker }
    "logs-db" { Run-Docker compose logs -f postgres qdrant }

    "shell-api" { Run-Docker compose exec api bash }
    "shell-worker" { Run-Docker compose exec celery_worker bash }
    "shell-postgres" {
        $env:POSTGRES_USER = $env:POSTGRES_USER ?? "ksr"
        $env:POSTGRES_DB = $env:POSTGRES_DB ?? "ksr"
        Run-Docker compose exec postgres psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB
    }
    "shell-qdrant" { Run-Docker compose exec qdrant sh }

    "rebuild-api" {
        Write-Host "🔨 Пересобираю API..." -ForegroundColor Yellow
        Run-Docker compose build api
        Write-Host "🔄 Перезапускаю..." -ForegroundColor Yellow
        Run-Docker compose up -d api celery_worker
        Write-Host "✅ Готово" -ForegroundColor Green
    }

    "rebuild" {
        Write-Host "🔨 Пересобираю все..." -ForegroundColor Yellow
        Run-Docker compose build
        Run-Docker compose up -d
        Write-Host "✅ Готово" -ForegroundColor Green
    }

    "migrate" { Run-Docker compose exec api alembic upgrade head }

    "revision" {
        $msg = $namedArgs["msg"]
        if (-not $msg) { Write-Host "❌ Использование: .\make.ps1 revision msg=create_foo" -ForegroundColor Red; exit 1 }
        Run-Docker compose exec api alembic revision --autogenerate -m "$msg"
    }

    "backup" {
        New-Item -ItemType Directory -Force -Path "data\backups" | Out-Null
        $ts = Get-Date -Format "yyyyMMdd_HHmmss"
        Run-Docker compose exec -T postgres pg_dump -U ksr ksr > "data\backups\ksr_$ts.sql"
        Write-Host "✅ Бэкап: data\backups\ksr_$ts.sql" -ForegroundColor Green
    }

    "backup-full" {
        New-Item -ItemType Directory -Force -Path "data\backups" | Out-Null
        $ts = Get-Date -Format "yyyyMMdd_HHmmss"
        Run-Docker compose exec -T postgres pg_dump -U ksr ksr > "data\backups\pg_$ts.sql"
        Run-Docker compose exec -T qdrant tar czf - /qdrant/storage > "data\backups\qdrant_$ts.tar.gz"
        Write-Host "✅ Полный бэкап сохранён в data\backups\" -ForegroundColor Green
    }

    "restore" {
        if (-not $Args[0]) { Write-Host "❌ Использование: .\make.ps1 restore <file>" -ForegroundColor Red; exit 1 }
        $file = $Args[0]
        Write-Host "⚠️  УДАЛИТ текущие данные. Восстановить из $file ? (y/N)" -ForegroundColor Yellow
        $r = Read-Host
        if ($r -ne "y") { exit 0 }
        Get-Content $file -Raw | Run-Docker compose exec -T postgres psql -U ksr ksr
        Write-Host "✅ БД восстановлена" -ForegroundColor Green
    }

    "tunnel-up" {
        $token = ""
        if (Test-Path .env) {
            $match = Select-String -Path ".env" -Pattern "^TUNNEL_TOKEN=(.+)" -ErrorAction SilentlyContinue
            if ($match) {
                $token = $match.Matches.Groups[1].Value
            }
        }
        if (-not $env:TUNNEL_TOKEN -and -not $token) {
            Write-Host "❌ TUNNEL_TOKEN не задан в .env" -ForegroundColor Red
            Write-Host "   1. Создай туннель: https://one.dash.cloudflare.com/" -ForegroundColor Yellow
            Write-Host "   2. Скопируй токен в .env: TUNNEL_TOKEN=eyJh..." -ForegroundColor Yellow
            exit 1
        }
        Write-Host "🌐 Запускаю Cloudflare Tunnel..." -ForegroundColor Yellow
        Run-Docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml up -d cloudflared
        Write-Host "✅ Запущен. Логи: .\make.ps1 tunnel-logs" -ForegroundColor Green
    }

    "tunnel-down" {
        Run-Docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml stop cloudflared
        Run-Docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml rm -f cloudflared
        Write-Host "✅ Tunnel остановлен" -ForegroundColor Green
    }

    "tunnel-logs" {
        Run-Docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml logs -f cloudflared
    }

    "open-site" { Start-Process "http://localhost:8000" }
    "open-admin" { Start-Process "http://localhost:8000/admin" }
    "open-flower" { Start-Process "http://localhost:5555" }
    "open-docs" { Start-Process "docs\README.md" }

    "test" { Run-Docker compose exec api pytest -v }
    "lint" { Run-Docker compose exec api ruff check app }
    "format" { Run-Docker compose exec api ruff format app }

    "clean" {
        Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
        Get-ChildItem -Path . -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue | Remove-Item -Force
        Write-Host "✅ Кэш очищен" -ForegroundColor Green
    }

    "prune" {
        Write-Host "⚠️  УДАЛИТ ВСЕ ДАННЫЕ. Продолжить? (y/N)" -ForegroundColor Red
        $r = Read-Host
        if ($r -ne "y") { exit 0 }
        Run-Docker compose down -v
        docker system prune -f
        Write-Host "✅ Очищено" -ForegroundColor Green
    }

    default {
        Write-Host "❌ Неизвестная команда: $Command" -ForegroundColor Red
        Write-Host "Список команд: .\make.ps1 help" -ForegroundColor Yellow
        exit 1
    }
}
