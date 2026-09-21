# Spec002 — T042 bloqueada

## Estado

T042 permanece sin marcar en `specs/002-autenticacion_administrativa/tasks.md`.
No se implementó una interfaz, adaptador HTTP, sesión, ruta ni prueba simulada para esta tarea.

## Dependencias corregidas de T035–T038

| Dependencia | Corrección disponible | Tarea responsable |
|---|---|---|
| Crear una invitación | Contrato HTTP autenticado y formulario administrativo mínimo. | T035 |
| Informar fallo de entrega conservando acciones seguras | Respuesta sanitizada y estado visible con reenvío o cancelación. | T036 |
| Reenviar o cancelar | Operaciones HTTP y controles accesibles para ambas acciones. | T037 |
| Activación del personal | Ruta de navegador y endpoints de enlace separados para preparar, abandonar y completar. | T038 |

## Dependencia que continúa pendiente

T043 ya valida correo, contraseña y exactamente un segundo factor mediante un resultado genérico. T044 ya registra una sola falla por solicitud rechazada de una cuenta conocida y consume condicionalmente el periodo TOTP o el único código de recuperación dentro de la transacción exterior. T045 ya cuenta la ventana móvil, crea una sola vez el bloqueo exacto del quinto fallo, lo audita y prepara los avisos durables exigidos. T046 ya rechaza antes de comprobar credenciales durante el bloqueo, no altera el plazo ni las sesiones existentes y reinicia la ventana al vencimiento exacto. T047 ya limpia los fallos al autenticar, crea una sesión con el rol vigente de la cuenta y sustituye atómicamente cualquier sesión activa anterior, incluso ante dos logins concurrentes. T048 ya expone el login HTTP con una cookie `__Host-` segura y entrega un CSRF distinto cuyo valor legible no se persiste. T049 ya exige el mismo origen y el token CSRF ligado a la sesión activa antes de ejecutar mutaciones administrativas. T050 ya invalida exactamente al llegar a 30 minutos sin actividad humana o a ocho horas desde creación, y solo las acciones humanas renuevan la primera ventana. T051 ya invalida condicionalmente la sesión activa, retira la cookie segura y registra un único cierre sin secretos; repetirla no revive el estado. Todavía faltan la invalidación por cambios de seguridad de T052 y la revalidación completa de identidad/cuenta de T053. El adaptador de invitaciones continúa fallando cerrado con `401` por defecto y solo permite inyectar una identidad ficticia en pruebas.

**Punto de regreso:** al terminar T053 deben reanudarse y finalizarse las pruebas reales de T042 antes de continuar con trabajo que dependa de la gestión autenticada del personal.

## Consecuencia para T042

T042 continúa sin implementarse porque el recorrido real propietario → invitación requiere la sesión administrativa completa hasta T053. Las pruebas añadidas verifican por separado los adaptadores y la UI de T035–T038; no se presentan como evidencia del recorrido integral T042.
