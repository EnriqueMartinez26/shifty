# Backup And Restore Runbook (Shifty)

## Objetivo operativo

- `RPO <= 24h`
- `RTO <= 4h`

Este runbook cubre la operacion minima para respaldos y prueba de recuperacion.

## Requisitos

- PostgreSQL client tools instalados (`pg_dump`, `pg_restore`)
- Variables de entorno de conexion configuradas (`DATABASE_URL`)
- Acceso al storage donde se guardan backups

## Backup manual

Ejecutar desde el directorio `backend`:

```bash
python scripts/backup_db.py --output-dir ../backups
```

Salida esperada:

- Archivo `shifty-YYYYMMDDTHHMMSSZ.dump`
- Archivo `shifty-YYYYMMDDTHHMMSSZ.sha256`

## Restore manual

Ejecutar desde el directorio `backend`:

```bash
python scripts/restore_backup.py --backup-file ../backups/shifty-YYYYMMDDTHHMMSSZ.dump
```

Recomendacion: restaurar primero en una base temporal de validacion antes de produccion.

## Prueba mensual de restore (obligatoria)

1. Tomar el backup mas reciente.
2. Restaurarlo en una base de staging aislada.
3. Ejecutar health checks:
   - login admin
   - lectura de agenda
   - consulta de reportes
4. Registrar evidencia:
   - fecha/hora inicio-fin
   - backup usado
   - resultado del chequeo
   - incidentes detectados

## Pipeline automatizado (GitHub Actions)

- Workflow: `.github/workflows/monthly-backup-drill.yml`
- Frecuencia: primer dia de cada mes (`cron: 0 5 1 * *`) y ejecucion manual.
- Evidencia: artefacto `backup-drill-evidence` con JSON y checksums.

Secrets requeridos:

- `BACKUP_DATABASE_URL`
- `DRILL_DATABASE_URL`

## Hardening de proxy y cabeceras

- `TRUST_PROXY_HEADERS` debe estar `true` solo si API esta detras de proxy confiable (`Cloudflare`, `Nginx`, `Traefik`).
- Si la API queda expuesta directa a internet, setear `TRUST_PROXY_HEADERS=false`.
- Forzar TLS en edge/proxy.
- Limitar metodos HTTP y tamano de body a nivel proxy.
- Activar WAF y rate limiting en edge.

## Alertas minimas recomendadas

- Error rate API mayor a 1%
- Latencia p95 anormal
- Cola de webhooks/outbox acumulada
- Fallo en tarea periodica de expiracion o procesamiento de outbox
