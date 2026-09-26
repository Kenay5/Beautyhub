# Verificaciones ejecutables de Spec002

Esta guía define los comandos reproducibles para verificar Spec002. Los
comandos se ejecutan desde la raíz del repositorio, con el entorno virtual
activado cuando corresponda. Las pruebas usan datos ficticios, reloj
controlable y dobles de proveedores; no requieren secretos versionados.

## Prerrequisitos

- Python 3.14 y las dependencias ya aprobadas del proyecto.
- Node.js y dependencias existentes del frontend para typecheck, build y
  Playwright.
- Para PostgreSQL: una base local exclusiva `beautyhub_test`. El helper pide la
  contraseña de forma segura y no la guarda en el repositorio.

## Grupos y cobertura

| Grupo | Comando | Cobertura |
| --- | --- | --- |
| Unitarias de dominio y aplicación | `python -m pytest backend/tests/unit -q` | RF-01 a RF-12; reglas puras, reloj, límites, contraseñas, TOTP, códigos, sesiones, autorización y estados; RNF-01 a RNF-04 cuando no requieren PostgreSQL. |
| Esquema e invariantes PostgreSQL | `python -m pytest backend/tests/integration -q` | Persistencia, restricciones, cifrado/huellas, transacciones, retención y recuperación de RF-01 a RF-12; RNF-01 y RNF-02. |
| Un test PostgreSQL enfocado | `./backend/scripts/run_postgres_integration_tests.ps1 -TestTarget backend/tests/integration/<test>.py` | Evidencia aislada para una tarea o criterio sin ejecutar toda la integración. |
| Contratos y autorización | `python -m pytest backend/tests/contract -q` | Entradas, salidas, errores sanitizados, cookies, CSRF y matriz propietario/personal/no autenticada de RF-01 a RF-12; RNF-01 y RNF-03. |
| Seguridad enfocada | `python -m pytest backend/tests/unit/admin_access backend/tests/contract/admin_access -q` | Secretos, logs, enlaces, factores, autorización y ausencia de filtraciones de RF-01 a RF-12; RNF-01 y RNF-03. |
| Concurrencia enfocada | `python -m pytest backend/tests/integration/test_schedule_concurrency.py backend/tests/integration/test_public_limits_concurrency.py -q` | Carreras protegidas ya presentes en el harness; los casos administrativos se agregarán en sus tareas correspondientes; RF-01 a RF-12; RNF-01 y RNF-02. |
| Tipos y compilación frontend | `npm --prefix frontend run typecheck` y `npm --prefix frontend run build` | Contratos consumidos por React, presentación administrativa y compatibilidad de RNF-05, sin sustituir pruebas de backend. |
| Recorridos administrativos con PostgreSQL real | Desde `frontend/`: `npx playwright test --config=playwright.admin-staff-invitation.config.ts` | Invitación, activación, códigos y cambio de correo mediante el servidor HTTPS exclusivo de pruebas. |
| Recorridos E2E generales | `npm --prefix frontend run test:e2e` | Regresión pública y administrativa con el servidor habitual; excluye los casos que requieren el harness HTTPS. No sustituye pruebas unitarias, de contrato ni PostgreSQL. |

Los marcadores de pytest pueden consultarse con `python -m pytest --markers`.
Si una ruta aún no contiene pruebas administrativas, el grupo se considera
pendiente y no exitoso; no se crean fixtures artificiales para forzar un
resultado positivo.

## Reglas de seguridad para ejecutar

- No pongas contraseñas, claves, tokens, correos reales ni códigos privados en
  comandos, fixtures, capturas, trazas o reportes.
- Las pruebas PostgreSQL deben usar únicamente `beautyhub_test`, nunca una base
  de desarrollo o producción.
- Los proveedores de correo y WhatsApp permanecen simulados; no se realizan
  llamadas de red.
- Una verificación solo cuenta como pasada cuando su comando se ejecutó y su
  salida no contiene fallos.
