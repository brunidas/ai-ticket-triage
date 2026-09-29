# AI Support Ticket Triage — fixtures (Semana 1)

Fixtures sintéticos para el proyecto **AI Support Ticket Triage**.

## Archivos

- `ticket-001.json` … `ticket-010.json`: entrada del CLI. Campos: `id`, `subject`, `description` y `logs` (opcional, saltado cuando no existe).
- `labels.json`: clasificación esperada de cada ticket (categoría, prioridad, idioma, urgencia, escalado). Se usa en el Día 4 para el conteo de aciertos; el modelo nunca la ve.
- `example-output.json`: salida de referencia que debe producir el CLI (estructura + registro de uso/costo/latencia).

## Distribución

- Categorías: `api`×2, `billing`×2, `integration`×1, `bug`×2, `account`×1, `how_to`×1, `other`×1.
- Idiomas: 8 en inglés, 2 en español (`ticket-009`, `ticket-010`).
- Caso urgente con escalado: `ticket-007` (único `P1` / `escalate: true`).
- Con logs: `ticket-001`, `ticket-003`, `ticket-007`, `ticket-010`.

## Reglas

- Datos 100% sintéticos. Nunca tickets reales de clientes o empleadores anteriores.
- Los Días 1–4 usan estos archivos locales; el CLI debe permanecer desacoplado de la fuente. Como segundo modo de entrada (Día 5 / Semana 2) se integra una plataforma free: Jira Cloud Free o Freshdesk Free.
