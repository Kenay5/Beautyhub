# Plan de implementación — 001 Manita de Gato MVP

**Estado:** aprobado explícitamente por el responsable del proyecto el 9 de septiembre de 2026; enmienda técnica para RNF-06 aprobada explícitamente el 10 de septiembre de 2026.

**Spec cubierta:** `specs/001-manita_gato/spec.md` aprobada.  
**Dependencia:** las operaciones administrativas dependen de la autenticación y autorización definidas en `specs/002-autenticacion_administrativa/spec.md`.

## 1. Propósito y límites del plan

Este plan describe cómo implementar la gestión de servicios, disponibilidad y citas de Manita de Gato sin modificar el comportamiento aprobado en la spec.

El stack aprobado es FastAPI con Python para el backend, React con TypeScript y Vite para el frontend, PostgreSQL con SQLAlchemy y Alembic para datos, pytest para pruebas de dominio e integración, Playwright para pruebas web y Axe exclusivamente para comprobaciones automatizadas de accesibilidad durante el desarrollo. Permanecerán en un repositorio y un despliegue, sin instalar dependencias hasta autorizar la primera tarea de implementación.

No forman parte de este plan:

- implementar la autenticación administrativa completa de la spec 002;
- incorporar pagos, cuentas de clientas o listas de espera;
- resolver la validación jurídica final del aviso de privacidad;
- definir infraestructura de despliegue no necesaria para cumplir la spec.

## 2. Estructura lógica de módulos

La aplicación se organizará como un monolito modular con dependencias dirigidas hacia el dominio:

```text
React público/administrativo
            ↓
FastAPI (entrada web)
            ↓
Casos de uso ─> Dominio
      └────────> Puertos de infraestructura: PostgreSQL, correo,
                 WhatsApp, reloj y generación segura de secretos
```

La lógica de negocio no dependerá de la interfaz web, del proveedor de mensajes ni del mecanismo concreto de persistencia.

| Módulo | Responsabilidad | Cobertura |
|---|---|---|
| Catálogo de servicios | Crear, editar, activar y desactivar; validar nombre canónico, descripción, duración, precio y sucursales; publicar solo opciones activas; conservar los acuerdos históricos. Solo el propietario puede gestionarlo. | RF-01; soporte de RF-03, RF-06 y RF-13 |
| Agenda y disponibilidad | Generar inicios cada 15 minutos; aplicar jornada, anticipación, horizonte, duración, bloqueos y separaciones; tratar al profesional como recurso único; calcular alternativas. | RF-02, RF-10 y RF-11; soporte de RF-03 y RF-06 |
| Citas | Crear, consultar, modificar y cancelar; generar el código; conservar instantáneas; registrar estados finales sin borrar antes del vencimiento. | RF-03, RF-05, RF-06, RF-07 y RF-09 |
| Agenda administrativa | Buscar, filtrar y gestionar citas mediante una identidad autorizada; consumir la autorización de la spec 002 sin implementar cuentas o sesiones. | RF-01, RF-03, RF-06 a RF-10 y RF-12 |
| Notificaciones | Preparar correo y WhatsApp; programar un recordatorio durable por horario elegible; registrar cada resultado; no revertir operaciones válidas; impedir envíos duplicados; recuperar el mismo código por acción autorizada. | RF-04 y RF-12; soporte de RF-03, RF-06 y RF-07 |
| Privacidad y retención | Registrar el aviso aceptado; retirar citas y datos al vencer; conservar solo estadísticas disociadas y las versiones del aviso aún referenciadas. | RF-03 y RF-13; RNF-01 |
| Protección contra abuso | Aplicar ventanas por IP, bloqueo por credenciales fallidas, no contar rechazos por límite y responder sin revelar citas. | RF-05 y RNF-04 |
| Persistencia y concurrencia | Implementar PostgreSQL, escrituras atómicas y serialización de agenda; guardar operación y entregas antes de contactar proveedores. | RF-01 a RF-13; RNF-02 |
| Continuidad operativa | Ejecutar retiros diarios y al arrancar; comprobar aplicación y base de datos; coordinar respaldos y restauraciones seguras. | RF-13 y RNF-05 |
| Presentación y usabilidad | Construir componentes fluidos y semánticos, conservar todas las funciones desde 320 píxeles CSS y comunicar estados, foco y errores de forma perceptible. No contiene reglas del dominio. | RF-01 a RF-12 como interfaz; RNF-06 |

### 2.1 Estructura de archivos propuesta

Las rutas todavía no existen y solo se crearán dentro de las tareas aprobadas. La estructura refleja los límites del monolito modular sin asignar un archivo a cada clase o caso de uso:

| Ruta prevista | Estado | Responsabilidad |
|---|---|---|
| `.python-version`, `requirements.txt` y `requirements-dev.txt` | Nuevos | Serie Python 3.14 y dependencias de producción y desarrollo fijadas para `pip`. |
| `backend/app/domain/` | Nueva | Reglas puras de servicios, agenda, citas, estados y retención. |
| `backend/app/application/` | Nueva | Casos de uso y puertos de reloj, secretos, persistencia y notificaciones. |
| `backend/app/infrastructure/` | Nueva | Adaptadores de PostgreSQL, correo, WhatsApp, cifrado y continuidad operativa. |
| `backend/app/web/` | Nueva | Entrada FastAPI, validación de contratos y entrega del frontend compilado. |
| `backend/alembic.ini` y `backend/migrations/` | Nuevos | Configuración y revisiones del esquema PostgreSQL. |
| `backend/tests/unit/` | Nueva | Pruebas de dominio sin infraestructura. |
| `backend/tests/integration/` | Nueva | PostgreSQL real, migraciones, transacciones y concurrencia. |
| `backend/tests/contract/` | Nueva | Contratos públicos y administrativos, validación, seguridad y autorización. |
| `frontend/package.json` y `frontend/package-lock.json` | Nuevos | Node 24 LTS, dependencias y scripts reproducibles administrados con `npm`. |
| `frontend/src/public/` | Nueva | Reserva, consulta, modificación y cancelación para clientas. |
| `frontend/src/admin/` | Nueva | Interfaces administrativas condicionadas a la spec 002. |
| `frontend/src/shared/` | Nueva | Componentes visuales y contratos compartidos sin reglas de negocio. |
| `frontend/tests/e2e/` y `frontend/playwright.config.ts` | Nuevos | Recorridos completos, tamaños representativos, navegadores objetivo y comprobaciones Axe contra la aplicación integrada. |

Las rutas técnicas utilizarán nombres en inglés. Esta tabla define fronteras y no autoriza crear archivos ni instalar dependencias por sí sola.

## 3. Modelo de datos

### 3.1 Modelo relacional propuesto

| Entidad | Datos e invariantes principales | Cobertura |
|---|---|---|
| `services` | Identificador; nombre original y canónico; descripción ≤250; duración múltiplo de 5 entre 5 y 600; precio de 0.01 a 20,000.00 con dos decimales; estado; disponibilidad en al menos una de las dos sucursales; fechas técnicas. | RF-01 |
| `appointments` | Identificador interno; código cifrado y huella; datos y declaración de la adulta responsable; sucursal; servicio e instantánea de nombre, duración y precio; inicio/fin; estado; motivo; origen; cuenta administrativa opcional; versión y fecha del consentimiento. | RF-03, RF-05 a RF-09 y RF-13 |
| `booking_confirmation_references` | Huella de la referencia, vencimiento exacto, cita asociada, resultado original por canal y marca de consumo único. Solo se muestra la referencia secreta al emitirla. | RF-03 y RF-04 |
| `availability_blocks` | Alcance global o sucursal, inicio/fin, cuenta responsable y fechas técnicas. | RF-10 |
| `appointment_reminders` | Cita, versión u horario programado, instante de envío calculado 24 horas antes, estado programado, reclamado, completado, invalidado u omitido, arrendamiento breve de reclamación y fechas técnicas; unicidad por cita y horario para impedir dos recordatorios iniciales y recuperación de reclamaciones abandonadas. | RF-04 |
| `notification_deliveries` | Identificador estable, cita, evento, canal, estado pendiente, aceptado, entregado o fallido, instante, referencia externa, relación opcional con el intento anterior y error sanitizado; nunca guarda el código ni contactos completos en texto de diagnóstico. | RF-04 y RF-12 |
| `privacy_notice_versions` | Versión y contenido inmutables, publicación y vigencia; no se elimina mientras una aceptación la referencie. | RF-03 y RF-13 |
| `monthly_appointment_statistics` | Mes de la última fecha vigente, servicio, sucursal, estado y conteo disociado; clave idempotente. | RF-13 |
| `public_request_events` | Huella con clave de IP o credencial, categoría, instante, resultado y vencimiento; nunca almacena la IP en texto plano. | RF-05 y RNF-04 |
| `schedule_guard` | Fila única bloqueada por toda escritura que pueda ocupar, mover o bloquear tiempo, o cambiar la vigencia de un servicio; obliga a recalcular antes del commit. | RF-01, RF-02, RF-03, RF-06, RF-10 y RF-11 |

Como las sucursales son exactamente dos y fijas en el MVP, su disponibilidad se guarda mediante indicadores restringidos en el servicio; no se introduce un catálogo extensible. La instantánea de la cita conserva el acuerdo aunque el servicio cambie después.

### 3.2 Restricciones de integridad principales

- unicidad del nombre canónico de servicio;
- rangos y múltiplos permitidos para duración y precio;
- al menos una sucursal por servicio;
- correo y teléfono obligatorios en citas;
- estados limitados a los aprobados;
- referencias de confirmación no reutilizables y con vencimiento;
- integridad entre cita, entregas y aceptación del aviso;
- unicidad del recordatorio inicial por cita y horario, reclamación concurrente única y máximo de tres reintentos manuales por canal;
- ausencia de secretos en índices, URLs, trazas y mensajes de error.

Las reglas temporales y de cruce entre citas se verifican en el dominio y se repiten dentro de la misma transacción protegida por `schedule_guard`.

**RF cubiertos:** RF-01 a RF-13 según la entidad afectada.

### 3.3 Ejemplo JSON lógico

El siguiente ejemplo describe el agregado de una cita. No representa una tabla ni expone un código real:

```json
{
  "appointmentId": "appointment-example-001",
  "status": "scheduled",
  "origin": "public",
  "customer": {
    "firstName": "Clienta",
    "lastName": "Ejemplo",
    "phone": "5510000000",
    "email": "clienta.ejemplo@example.test"
  },
  "serviceSnapshot": {
    "serviceId": "service-example-001",
    "name": "Servicio de ejemplo",
    "durationMinutes": 60,
    "price": "350.00"
  },
  "branch": "chiconcuac",
  "scheduledStart": "2030-06-15T17:00:00-06:00",
  "scheduledEnd": "2030-06-15T18:00:00-06:00",
  "privateCode": "<secreto entregado solo por los canales autorizados>",
  "privacyConsent": {
    "noticeVersion": "privacy-example-v1",
    "acceptedAt": "2030-06-01T12:00:00-06:00"
  },
  "notifications": {
    "email": "accepted",
    "whatsapp": "accepted"
  }
}
```

**RF cubiertos:** RF-03, RF-04, RF-05, RF-06, RF-07, RF-08, RF-09 y RF-13.

## 4. Algoritmo de disponibilidad y conflictos

Este pseudocódigo es descriptivo y no ejecutable.

```text
FUNCTION evaluateCandidate(candidate, service, now):
    REQUIRE service is active in candidate.branch
    REQUIRE candidate.start uses a 15-minute grid
    REQUIRE candidate.start is between 09:00 and 19:00 local time
    IF candidate.origin is public:
        REQUIRE candidate.start is at least exactly 60 minutes after now
    IF candidate.origin is administrative:
        REQUIRE candidate.start is not before now
    REQUIRE candidate.start is within exactly 90 periods of 24 hours after now

    candidate.end = candidate.start + service.durationMinutes

    FOR EACH block that applies globally or to candidate.branch:
        IF halfOpenIntervalsOverlap(candidate, block):
            RETURN unavailable because blocked

    FOR EACH scheduled appointment near candidate:
        IF halfOpenIntervalsOverlap(candidate, appointment):
            RETURN unavailable because occupied

        IF appointment.end <= candidate.start:
            requiredGap = 5 minutes when branches match, otherwise 25 minutes
            IF candidate.start < appointment.end + requiredGap:
                RETURN unavailable because required separation is missing

        IF candidate.end <= appointment.start:
            requiredGap = 5 minutes when branches match, otherwise 25 minutes
            IF appointment.start < candidate.end + requiredGap:
                RETURN unavailable because required separation is missing

    RETURN available
```

Reglas complementarias:

- el fin de una cita puede superar las 19:00 si su inicio es válido;
- el horario de comida de 13:00 a 14:00 no bloquea citas;
- canceladas, completadas, no presentadas y retiradas no ocupan disponibilidad futura;
- la separación exacta se aplica primero y el siguiente inicio debe caer en la cuadrícula de 15 minutos;
- para una modificación, la cita actual se excluye temporalmente al evaluar su nuevo horario;
- para crear o mover una cita, la comprobación se repite bajo el bloqueo transaccional de la agenda.

**RF cubiertos:** RF-02, RF-03, RF-06, RF-10 y RF-11.

### 4.1 Cálculo de alternativas

```text
FUNCTION findAlternatives(requestedStart, service, branch, now):
    candidates = every 15-minute start on the same calendar day
    valid = candidates where evaluateCandidate(...) returns available
    order valid by:
        1. absolute distance from requestedStart, ascending
        2. start time, descending when the distance is equal
    RETURN first 3 candidates
```

Solo se calculan alternativas cuando la fecha y hora solicitadas son válidas, pero existe una cita, un bloqueo o falta la separación requerida. Los errores de formato, jornada, intervalo, anticipación u horizonte conservan su mensaje específico y no producen alternativas.

**RF cubiertos:** RF-11; soporte de RF-03 y RF-06.

## 5. Contratos web y de aplicación

### 5.1 Convenciones comunes

- los códigos privados y referencias secretas se reciben en el cuerpo de una solicitud, nunca en la URL;
- todas las fechas se intercambian con zona u offset explícito y se interpretan con reglas de Ciudad de México;
- React y FastAPI se publican bajo el mismo origen; la API no habilita acceso cruzado general desde dominios externos;
- las respuestas visibles y mensajes de validación se presentan en español;
- los errores no incluyen trazas, consultas, credenciales ni identificadores internos;
- resultados posibles: éxito, validación inválida, conflicto, no encontrado o credencial inválida, no autenticado, no autorizado, límite excedido y fallo parcial de notificación;
- equivalencias HTTP previstas: 200/201, 400/422, 409, 404 genérico, 401, 403 y 429;
- una operación principal exitosa sigue siendo exitosa aunque uno o ambos canales de notificación fallen.
- toda creación pública o administrativa obtiene automáticamente una referencia secreta antes de confirmar; un reintento de la misma confirmación conserva esa referencia.
- un canal aceptado por el proveedor no se presenta como entregado; una confirmación posterior lo cambia a entregado y un fallo inmediato o tardío lo cambia a fallido sin revertir la operación principal.

**RF cubiertos:** RF-01 a RF-13 de forma transversal.  
**RNF cubiertos:** RNF-01, RNF-02, RNF-03 y RNF-04.

### 5.2 Operaciones públicas

| Operación | Entrada principal | Salida de éxito | Errores controlados | Cobertura |
|---|---|---|---|---|
| Consultar servicios | Sucursal | Servicios activos disponibles | Validación; límite excedido | RF-01 |
| Consultar disponibilidad | Sucursal, servicio y fecha | Inicios válidos | Validación; límite excedido | RF-02 |
| Emitir referencia de confirmación | Contexto de solicitud | Referencia secreta y vencimiento | Límite excedido | RF-03 |
| Crear cita | Referencia, datos de clienta, sucursal, servicio, fecha, hora y aceptación | Confirmación, código privado y estado por canal | Validación; conflicto con alternativas; referencia inválida; límite | RF-03, RF-04, RF-11 |
| Repetir confirmación | Misma referencia y misma solicitud | Mismo resultado original, sin nueva cita ni nuevos envíos | Referencia inválida o vencida | RF-03, RF-04 |
| Consultar cita | Código privado | Solo la cita correspondiente | Respuesta genérica; límite; bloqueo de credencial | RF-05 |
| Modificar cita | Código, teléfono y nuevos fecha, hora, sucursal o servicio | Cita actualizada y estado por canal | Credencial genérica; anticipación; conflicto con alternativas; límite | RF-06, RF-04, RF-11 |
| Cancelar cita | Código y teléfono | Cita cancelada y estado por canal | Credencial genérica; anticipación; estado no permitido; límite | RF-07, RF-04 |

La repetición de una confirmación devolverá los resultados de entrega registrados en el primer procesamiento y no volverá a contactar a los proveedores.

### 5.3 Operaciones administrativas

Todas exigen una identidad autenticada y autorización suficiente provista por la spec 002.

| Operación | Entrada principal | Salida de éxito | Errores controlados | Cobertura |
|---|---|---|---|---|
| Gestionar servicios | Rol propietario y datos válidos del servicio | Servicio creado o actualizado | Validación; nombre duplicado; no autorizado | RF-01 |
| Buscar agenda | Fecha, rango y filtros opcionales | Lista autorizada de citas | Validación; no autorizado | RF-08 |
| Ver detalle | Identificador o búsqueda exacta autorizada | Datos necesarios de la cita | No encontrado; no autorizado | RF-08 |
| Crear cita | Referencia secreta, datos completos, confirmación de autorización y primer inicio no anterior al momento actual | Cita, código y estado por canal | Validación; conflicto; no autorizado | RF-03, RF-04, RF-11 |
| Modificar cita | Cita y fecha, hora, sucursal, servicio o datos de contacto permitidos | Cita actualizada; si cambia el contacto, reenvío del mismo código a los contactos nuevos | Validación; conflicto; estado no permitido; no autorizado | RF-06, RF-04, RF-11 |
| Cancelar cita | Cita y motivo opcional | Cita cancelada y estado por canal | Estado no permitido; no autorizado | RF-07, RF-04 |
| Registrar resultado | Cita y resultado | Estado completado o no asistió | Estado no permitido; no autorizado | RF-09 |
| Gestionar bloqueos | Alcance e intervalo | Bloqueo creado, editado o eliminado | Validación; no autorizado | RF-10 |
| Reenviar código | Cita seleccionada | Resultado de correo y WhatsApp | Cita no elegible; no autorizado; fallos por canal | RF-12 |
| Reintentar notificación fallida | Entrega fallida seleccionada | Nuevo intento auditable al contacto vigente | Entrega no elegible; no autorizado; fallos por canal | RF-04 |

Fuera de la pantalla única que confirma una cita recién creada, la interfaz administrativa no mostrará el código privado. El reenvío posterior será una acción explícita y auditable que usa el código cifrado sin revelarlo a la persona administradora.

### 5.4 Operaciones internas programadas

| Operación | Momento | Resultado | Cobertura |
|---|---|---|---|
| Retirar citas vencidas | A las 00:00 y antes de admitir tráfico en cada arranque | Estadística mensual actualizada y cita/datos personales retirados | RF-13 |
| Procesar recordatorios | Al alcanzar 24 horas antes del inicio y al recuperarse de una interrupción | Un intento independiente por canal o una omisión definitiva cuando resten 60 minutos o menos | RF-04 |
| Limpiar referencias | Al vencer 24 horas y no ser necesarias para idempotencia | Referencias expiradas eliminadas de forma segura | RF-03 |
| Limpiar eventos de protección | Fuera de su ventana útil | Huellas operativas eliminadas | RF-05, RNF-04 |

Los procesos serán idempotentes: repetirlos no duplicará estadísticas ni alterará una segunda vez una cita.

Toda consulta pública o administrativa aplicará además el límite temporal de RF-13 en el momento de acceso. Así, una cita vencida permanece inaccesible aunque una ejecución física se retrase; al arrancar, la aplicación completará el retiro pendiente antes de declararse saludable y admitir tráfico.

## 6. Flujos transaccionales críticos

### 6.1 Creación o modificación de cita

1. Validar formato, aviso y credenciales aplicables.
2. Aplicar el límite de solicitudes correspondiente.
3. Abrir una transacción; bloquear `schedule_guard` si se crea o cambia fecha, hora, sucursal o servicio. Una corrección exclusiva de nombre o contacto bloquea solo la cita y no ocupa la agenda.
4. Cuando cambie la agenda, recargar y bloquear el servicio seleccionado, además de bloqueos y citas relevantes.
5. Evaluar nuevamente disponibilidad y vigencia solo cuando cambie la agenda; una corrección exclusiva de datos conserva el acuerdo original.
6. Crear o actualizar la cita y sus entregas pendientes.
7. Confirmar la transacción.
8. Intentar correo y WhatsApp de manera independiente.
9. Registrar cada resultado y responder con el estado de la operación principal y de ambos canales.

**RF cubiertos:** RF-02, RF-03, RF-04, RF-06 y RF-11.

### 6.2 Cancelación

1. Validar credenciales o autorización administrativa.
2. Evaluar la anticipación con el reloj oficial.
3. Cambiar el estado de forma atómica sin borrar la cita.
4. Crear entregas pendientes y confirmar la transacción.
5. Intentar ambos canales y registrar resultados independientes.

**RF cubiertos:** RF-04 y RF-07.

### 6.3 Retiro y estadísticas

1. Seleccionar un lote de citas cuyo plazo ya venció.
2. Convertir `scheduled` en `unrecorded_result` para el conteo final.
3. Incrementar la estadística mensual mediante una operación idempotente.
4. Eliminar la cita y sus datos operativos y personales, dejando únicamente los conteos disociados aprobados.
5. Retirar versiones antiguas del aviso solo cuando ninguna aceptación restante las use.

**RF cubiertos:** RF-13.

### 6.4 Recordatorio previo

1. Al confirmar una creación o cambio de horario, calcular la diferencia con el reloj oficial dentro de la misma transacción.
2. Cuando cambie el horario, invalidar primero cualquier recordatorio pendiente del horario anterior. Si faltan más de 24 horas para el nuevo horario, guardar uno nuevo con vencimiento exactamente 24 horas antes; si faltan 24 horas o menos, no programarlo.
3. Un proceso interno reclama en PostgreSQL los recordatorios vencidos mediante un arrendamiento breve, sin permitir que otro proceso reclame el mismo registro y recuperando después de su vencimiento una reclamación abandonada antes del inicio registrado.
4. En una transacción breve, bloquear y releer la cita; continuar solo si permanece programada, conserva el horario y faltan más de 60 minutos. Si el sistema se recupera tarde y ya no supera ese límite, marcar el recordatorio como omitido de forma definitiva.
5. Preparar el resumen aprobado sin código privado, crear un intento por correo y otro por WhatsApp hacia los contactos vigentes y registrar atómicamente el inicio del envío antes de cerrar la transacción.
6. Contactar a cada proveedor fuera de la transacción y registrar sus resultados independientes.
7. Si una modificación o cancelación se confirma después del inicio registrado, conservar el resultado posible del recordatorio y emitir la notificación ordinaria de la operación posterior.
8. Un reintento manual exige propietario o personal autorizado, último resultado fallido, más de 60 minutos restantes, menos de tres reintentos y cinco minutos desde el anterior; cada solicitud consume el límite administrativo correspondiente de la spec 002.

**RF cubiertos:** RF-04-CA-14 a RF-04-CA-25.  
**RNF cubiertos:** RNF-01 y RNF-02.

## 7. Decisiones técnicas justificadas

### DT-01. Monolito modular

**Decisión:** una sola aplicación desplegable con módulos separados por responsabilidades.  
**Justificación:** el MVP pertenece a un solo negocio y comparte transacciones fuertes entre agenda, citas y notificaciones.  
**Alternativa descartada:** microservicios, porque introducirían coordinación distribuida, más infraestructura y fallos adicionales sin un requisito que lo justifique.  
**RF cubiertos:** RF-01 a RF-13.

### DT-02. PostgreSQL como persistencia y coordinador de agenda

**Decisión:** guardar datos de negocio en PostgreSQL y serializar las escrituras de agenda mediante una fila de guardia.  
**Justificación:** satisface la constitución y evita dobles reservas aun con solicitudes concurrentes.  
**Alternativa descartada:** confiar en una consulta previa o únicamente en la interfaz; ambas permiten carreras. Una restricción simple de solapamiento tampoco expresa por sí sola separaciones variables de 5 o 25 minutos.  
**RF cubiertos:** RF-02, RF-03, RF-06, RF-10 y RF-11.

### DT-03. Tiempo absoluto más zona de negocio

**Decisión:** persistir instantes absolutos y evaluar reglas con la zona `America/Mexico_City`.  
**Justificación:** mantiene comparaciones consistentes y respeta la hora civil de Ciudad de México.  
**Alternativa descartada:** guardar fechas y horas locales sin zona, porque serían ambiguas y frágiles ante cambios de reglas horarias.  
**RF cubiertos:** RF-02, RF-03, RF-06, RF-07, RF-10, RF-11 y RF-13.

### DT-04. Código privado cifrado más huella de búsqueda

**Decisión:** generar un secreto aleatorio con al menos 128 bits, almacenar una copia cifrada autenticadamente para el reenvío y una huella con clave para búsqueda exacta.  
**Justificación:** RF-12 exige reenviar el mismo código, pero no mostrarlo ni conservarlo expuesto. Las claves viven fuera del repositorio y de la base de datos.  
**Alternativa descartada:** texto plano, por exposición; solo hash, porque impediría reenviar el mismo código.  
**RF cubiertos:** RF-03, RF-05 y RF-12.

### DT-05. Registro transaccional y proveedores de entregas

**Decisión:** guardar cita y entregas pendientes en la misma transacción; usar simuladores en desarrollo, Resend sin rastreo para correo y, cerca del lanzamiento, intentar WhatsApp Cloud API de Meta directamente. Un envío aceptado por el proveedor permanecerá como aceptado hasta confirmar entrega; un fallo inmediato o tardío quedará como fallido y podrá originar un reintento administrativo auditable al contacto vigente. Antes de publicar se verificará la conservación de datos de ambos proveedores, se elegirá su configuración mínima disponible y se sustituirá cualquier proveedor que no permita cumplir la política de privacidad aprobada.  
**Justificación:** los adaptadores aislados permiten registrar cada canal después del commit, recibir cambios posteriores de estado, probar fallos gratuitamente y cambiar de proveedor sin tocar las reglas; la verificación previa al lanzamiento evita entregar datos personales a un servicio con una conservación incompatible. Una modificación o cancelación ordinaria nunca incluye el código; la corrección administrativa de un contacto usa un mensaje separado que reenvía el mismo código conforme a RF-06.  
**Alternativa descartada:** enviar antes del commit, revertir la cita por un fallo, automatizar WhatsApp Web de forma no oficial o acoplar el dominio a un proveedor.  
**RF cubiertos:** RF-03, RF-04, RF-06, RF-07 y RF-12.

### DT-06. Protección mediante ventanas temporales en PostgreSQL

**Decisión:** implementar ventanas móviles y bloqueos con eventos mínimos en PostgreSQL, protegidos contra concurrencia por clave.  
**Justificación:** conserva exactitud, evita añadir otra dependencia y basta para el volumen inicial.  
**Alternativa descartada:** incorporar Redis desde el MVP sin evidencia de necesidad.  
**RF cubiertos:** RF-05.  
**RNF cubierto:** RNF-04.

### DT-07. Instantáneas inmutables

**Decisión:** copiar en la cita nombre, duración y precio del servicio, además de la versión del aviso aceptada.  
**Justificación:** el acuerdo histórico no debe cambiar cuando el catálogo o el aviso se actualicen.  
**Alternativa descartada:** resolver siempre los valores desde sus registros vigentes.  
**RF cubiertos:** RF-01, RF-03, RF-06 y RF-13.

### DT-08. Interfaz pública sin secretos en URLs

**Decisión:** consultas y cambios con código privado usarán cuerpos de solicitud y controles para impedir su registro.  
**Justificación:** las URLs suelen quedar en historial, analítica, proxies y trazas.  
**Alternativa descartada:** enlaces con el código completo en parámetros de URL.  
**RF cubiertos:** RF-05, RF-06 y RF-07.  
**RNF cubierto:** RNF-01.

### DT-09. Stack, despliegue y costo operativo

**Decisión:** FastAPI/Python, React/TypeScript/Vite, SQLAlchemy/Alembic, pytest/Playwright y PostgreSQL; un repositorio y un despliegue en Railway donde FastAPI sirve el resultado compilado de React y la API bajo el mismo dominio. En producción, los respaldos estarán cifrados, tendrán acceso restringido, se crearán al menos cada 6 horas y se conservarán como máximo 7 días; se generará otro antes de cada cambio de esquema. Toda restauración ocurrirá de forma aislada y ejecutará el retiro de RF-13 antes de admitir tráfico. Una comprobación técnica verificará aplicación y PostgreSQL sin exponer detalles y producirá una alerta para el responsable del proyecto mediante un mecanismo incluido en el presupuesto aprobado.  
**Justificación:** FastAPI proporciona una frontera explícita para validación, seguridad y casos de uso; React con TypeScript y Vite permite construir las interfaces públicas y administrativas interactivas manteniendo sus errores detectables durante el desarrollo; SQLAlchemy y Alembic permiten expresar transacciones y evolucionar de forma controlada el esquema obligatorio de PostgreSQL; pytest cubre reglas de dominio e integración y Playwright verifica los recorridos completos en el navegador. Mantener todo en un repositorio y servir la interfaz compilada desde FastAPI conserva las capas separadas, pero reduce servidores, CORS, configuración y costo. La frecuencia de respaldo limita a seis horas la pérdida prevista de datos y la comprobación de salud permite detectar indisponibilidad. El objetivo es $100 MXN mensuales, con alerta cercana a $85 y sin ampliar recursos o plan sin aprobación.  
**Alternativa descartada:** Next.js, Jinja2 como interfaz principal, frontend/backend desplegados por separado o un VPS autoadministrado; agregan cambio de stack, limitan la interfaz o elevan complejidad operativa. También se descartan respaldos indefinidos o restauraciones públicas sin retirar previamente los datos vencidos.  
**RF cubiertos:** RF-01 a RF-13 de forma transversal; no modifica su comportamiento.
**RNF cubierto:** RNF-05.

### DT-10. Versiones y gestión reproducible de dependencias

**Decisión:** usar Python `>=3.14,<3.15` con `pip` y Node.js `24.x` LTS con `npm`. Las dependencias directas y transitivas de Python quedarán fijadas en `requirements.txt` y `requirements-dev.txt`; el frontend conservará `package-lock.json` y se instalará de forma reproducible con `npm ci`. Las versiones exactas se comprobarán y fijarán únicamente dentro de la primera tarea que tenga autorización para instalarlas.  
**Justificación:** Python 3.14 es estable y el stack aprobado declara compatibilidad; Node 24 tiene soporte LTS. `pip` y `npm` evitan introducir gestores adicionales y sus archivos fijados permiten repetir desarrollo, pruebas y despliegue.  
**Alternativa descartada:** añadir Poetry, uv, pnpm o Yarn desde el inicio, porque duplicaría herramientas sin una necesidad demostrada para este MVP. También se descartan versiones `Current`, preliminares o sin soporte de seguridad.  
**RF cubiertos:** RF-01 a RF-13 de forma transversal; no modifica su comportamiento.

### DT-11. Programación durable de recordatorios sin una cola externa

**Decisión:** persistir cada recordatorio en PostgreSQL y procesarlo desde el mismo despliegue mediante un ejecutor periódico que reclama lotes con bloqueo transaccional y arrendamientos breves recuperables. La unicidad por cita y horario, más una clave estable por canal, impide duplicados entre procesos o reinicios. Una reclamación abandonada antes del inicio registrado vuelve a ser elegible; una interrupción posterior conserva la entrega como pendiente hasta reconciliarla mediante la clave idempotente o una respuesta auténtica del proveedor, y solo un resultado finalmente fallido habilita el reintento manual. El ejecutor no contiene reglas de negocio: consulta un caso de uso independiente de FastAPI, del proveedor y del mecanismo que lo despierta.  
**Justificación:** permite sobrevivir reinicios y ejecutar la recuperación tardía aprobada sin añadir Redis, un corredor de mensajes, otro servicio permanente ni una dependencia de programación; mantiene el objetivo de costo y la separación exigida por la constitución.  
**Alternativa descartada:** temporizadores solo en memoria, porque se pierden al reiniciar, y una cola o servicio cron separado desde el MVP, porque eleva costo y operación sin necesidad demostrada.  
**RF cubiertos:** RF-04-CA-14 a RF-04-CA-25.  
**RNF cubiertos:** RNF-01, RNF-02 y RNF-05.

### DT-12. Interfaz adaptable y accesibilidad verificable

**Decisión:** construir la interfaz con HTML semántico y composición fluida orientada primero a pantallas pequeñas. Los puntos de ajuste responderán al contenido y se verificarán al menos a 320, 390, 768 y 1280 píxeles CSS; la página no generará desplazamiento horizontal general y las tablas administrativas usarán desplazamiento interno solo cuando no exista una presentación más clara. Los controles táctiles tendrán un área operable objetivo de al menos 44 por 44 píxeles CSS, excepto enlaces integrados en texto. El foco visible, el orden de teclado, los nombres accesibles, las etiquetas, los errores asociados, el zoom y los estados que no dependan solo del color formarán parte de los componentes compartidos.

**Justificación:** una base común evita corregir cada pantalla al final, conserva todas las funciones en celulares y convierte RNF-06 en verificaciones repetibles. `@axe-core/playwright` será una dependencia exclusiva de desarrollo: analizará los estados principales dentro de Playwright, no se incluirá en el artefacto de producción ni generará costo de alojamiento. Cada recorrido principal deberá terminar sin infracciones reportadas por Axe; la revisión manual cubrirá los aspectos que una herramienta automática no puede comprobar.

**Alternativa descartada:** crear una versión móvil separada, ocultar funciones administrativas en pantallas pequeñas o depender únicamente de una inspección visual final; duplicaría mantenimiento o dejaría requisitos sin evidencia constante.

**RF cubiertos:** RF-01 a RF-12 como capa de presentación, sin modificar su comportamiento.

**RNF cubierto:** RNF-06.

## 8. Modelo de amenazas y controles

| Riesgo | Control previsto | Verificación | Cobertura |
|---|---|---|---|
| Adivinar o enumerar citas | Códigos y referencias con al menos 128 bits, huellas con clave, respuestas genéricas y límites móviles. | Pruebas de aislamiento, errores equivalentes y bordes de bloqueo. | RF-03, RF-05, RF-06 y RF-07; RNF-01 y RNF-04 |
| Exponer secretos en URLs o diagnósticos | Secretos solo en cuerpos, cifrado autenticado, sanitización y ausencia de contactos completos. | Inspección automatizada de URLs, respuestas, logs, errores y entregas. | RF-03 a RF-05 y RF-12; RNF-01 |
| Manipular entradas o estados | Validación en la entrada y el dominio, consultas parametrizadas y restricciones PostgreSQL. | Pruebas con entradas hostiles y estados estructuralmente inválidos. | RF-01 a RF-13; RNF-01 y RNF-02 |
| Producir dobles reservaciones | Revalidación dentro de la transacción y bloqueo de `schedule_guard`. | Creaciones, movimientos y bloqueos concurrentes en PostgreSQL real. | RF-02, RF-03, RF-06 y RF-10; RNF-02 |
| Acceder a administración sin permiso | Ningún contrato administrativo se conecta antes de la spec 002 y cada operación exige autorización. | Pruebas de ausencia de sesión, rol insuficiente y mínimo privilegio. | RF-01, RF-03 y RF-06 a RF-12; RNF-01 |
| Abusar de accesos públicos | Ventanas móviles por huellas de IP y credencial, sin ampliar bloqueos mediante rechazos. | Pruebas exactas y concurrentes de 60, 10 y 5 solicitudes o fallos. | RF-05; RNF-04 |
| Perder una cita por fallo de mensajería | Cita y entregas se confirman antes de contactar proveedores; cada canal falla de forma independiente. | Fallo inmediato, tardío y cruzado sin revertir la operación. | RF-03, RF-04, RF-06, RF-07 y RF-12 |
| Enviar un recordatorio duplicado, obsoleto o demasiado tarde | Registro durable único, arrendamiento recuperable, comprobación final, inicio atómico, corte de 60 minutos y límites de reintento. | Reinicios, reprogramaciones, cancelaciones y procesos concurrentes con reloj controlado. | RF-04-CA-14 a RF-04-CA-25; RNF-01 y RNF-02 |
| Conservar datos vencidos o restaurarlos | Límite aplicado en cada acceso, retiro diario y al arrancar, restauración aislada y respaldos de siete días. | Pruebas de vencimiento exacto, retiro idempotente y restauración. | RF-05 y RF-13; RNF-01 y RNF-05 |
| Perder datos o no detectar una caída | Respaldos cada seis horas, respaldo previo a migraciones, comprobación de salud y alerta operativa. | Ejercicio de restauración y fallos controlados de aplicación y PostgreSQL. | RF-13; RNF-05 |
| Filtrar datos mediante proveedores | Configuración mínima de conservación, ausencia de rastreo y sustitución del proveedor incompatible. | Revisión documentada y prueba controlada previa a publicación. | RF-04, RF-12 y RF-13; RNF-01 |

Los controles de sesión, CSRF y autenticación administrativa pertenecen al plan de la spec 002. Esta spec solo mantiene cerrada esa frontera hasta disponer de una identidad autorizada.

## 9. Estrategia de pruebas

### 9.1 Principios

- cada regla crítica tendrá una prueba automatizada con pytest en la capa más cercana al dominio;
- las reglas respaldadas por PostgreSQL tendrán pruebas de integración contra PostgreSQL real y migraciones Alembic aplicadas;
- cada contrato público y administrativo tendrá pruebas de autorización, validación y sanitización;
- se usarán únicamente datos ficticios;
- el reloj, secretos, Resend y WhatsApp se sustituirán por dobles controlados en pruebas;
- la suite incluirá solicitudes concurrentes reales para las operaciones de agenda;
- las interfaces se comprobarán desde 320 píxeles CSS con Playwright, Axe, teclado y tamaños representativos, sin sustituir la revisión manual en dispositivos reales;
- ningún RF se considerará cubierto solo por una prueba de interfaz.

### 9.2 Pruebas unitarias de dominio

- validación completa de servicios, Unicode visible, espacios externos, caracteres de control y nombre canónico;
- límites exactos de 5, 600, 20,000.00, descripción 250 y sus valores inválidos vecinos;
- servicio inactivo conservado en una cita existente; obligación de elegir uno activo al reprogramar; conservación del precio si cambia fecha, hora, sucursal o contacto, y actualización de duración/precio al cambiar servicio;
- cuadrícula de 15 minutos y horario de inicio de 09:00 a 19:00;
- anticipación pública exacta de 60 minutos, excepción administrativa y horizonte exacto de 90 periodos de 24 horas;
- duración que cruza las 19:00 y citas durante 13:00–14:00;
- intervalos semiabiertos, solapamiento y separaciones exactas de 5 y 25 minutos;
- orden de alternativas, incluido empate a favor del horario posterior;
- reglas por estado para modificar, cancelar, completar y marcar no presentación;
- motivo opcional de cancelación, validación a 250 caracteres y visibilidad exclusivamente administrativa;
- elegibilidad del recordatorio con los bordes exactos de más de 24 horas y más de 60 minutos, reprogramación, cancelación y límite de tres reintentos separados por cinco minutos;
- cálculo exacto del retiro a 30 días y cambio a resultado no registrado.

**RF cubiertos:** RF-01, RF-02, RF-06, RF-07, RF-09, RF-10, RF-11 y RF-13.

### 9.3 Pruebas de integración con PostgreSQL

- restricciones de datos y unicidad canónica;
- transacción de cita más entregas pendientes;
- recordatorio durable único por cita y horario, reclamación concurrente única, invalidación al reprogramar o cancelar y recuperación después de una interrupción;
- transiciones válidas de entrega entre pendiente, aceptada, entregada y fallida, incluido un fallo tardío y su reintento enlazado;
- dos creaciones simultáneas para el mismo horario: solo una se confirma;
- movimientos concurrentes entre sucursales respetando 25 minutos;
- cita y bloqueo creados simultáneamente sin dejar una combinación inválida;
- idempotencia de referencia bajo repeticiones simultáneas;
- agregación y retiro repetidos sin duplicar estadísticas;
- limpieza de referencias y eventos vencidos;
- cifrado recuperable para reenvío y búsqueda exacta por huella, sin texto plano.

**RF cubiertos:** RF-01, RF-02, RF-03, RF-04, RF-05, RF-06, RF-10, RF-11, RF-12 y RF-13.

### 9.4 Pruebas de contrato y casos de uso

- respuestas y códigos de estado para cada operación pública;
- mismo resultado al repetir una confirmación, sin nueva cita ni nuevas entregas;
- nombre, apellido, teléfono y correo con todas sus normalizaciones, formatos válidos y bordes inválidos aprobados;
- aceptación del aviso, versión inmutable, autorización de contacto y declaración de persona adulta responsable en los dos orígenes;
- fallo de un canal y de ambos sin revertir crear, modificar o cancelar; varias citas futuras con el mismo teléfono permitidas si la agenda lo admite;
- aceptación del proveedor sin afirmar entrega, confirmación posterior, fallo tardío y reintento administrativo auditable al contacto vigente;
- recordatorios de citas públicas y administrativas a los contactos vigentes, sin código privado, con canales independientes, omisión tardía, ausencia de reintentos automáticos y límite concurrente en el inicio registrado del envío;
- autorización del propietario y personal para reintentar solo el canal fallido, máximo tres veces, con cinco minutos de separación, más de 60 minutos restantes y consumo del límite de la spec 002;
- código incorrecto y cita inexistente con respuesta pública indistinguible;
- consulta pública con teléfono y correo exactamente enmascarados y sin datos de otra cita;
- modificación pública que exige código y teléfono;
- campos públicos limitados a fecha, hora, sucursal y servicio; campos de contacto reservados a administración;
- cambio administrativo de teléfono o correo que conserva y reenvía el mismo código a los contactos nuevos;
- cancelación exactamente una hora antes aceptada y un instante después rechazada;
- modificación o cancelación administrativa permitida hasta el instante anterior al inicio y rechazada desde el inicio exacto;
- administración rechazada sin identidad o permiso suficiente;
- búsqueda administrativa exacta por código, teléfono y fecha, y parcial por nombre o apellido sin distinguir mayúsculas ni acentos;
- reenvío del mismo código mientras siga vigente, independientemente del estado final, sin mostrarlo y solo a los contactos registrados;
- bloqueos globales y de sucursal, cruces de medianoche, redundancias entre alcances y ausencia de traslado causado por un bloqueo;
- cita marcada como no asistió desde el minuto cinco exacto y nueva cita administrativa si la clienta llega después;
- límite 60/60 segundos, 10/15 minutos y 5 fallos/15 minutos, incluidos bordes y concurrencia;
- solicitudes rechazadas por límite que no incrementan el contador y coexistencia de límites aplicando la denegación que dure más.

**RF cubiertos:** RF-03, RF-04, RF-05, RF-06, RF-07, RF-08, RF-09, RF-10, RF-11 y RF-12.  
**RNF cubiertos:** RNF-01, RNF-02, RNF-03 y RNF-04.

### 9.5 Pruebas de extremo a extremo con Playwright

- clienta consulta catálogo y disponibilidad, crea cita, recibe código y consulta solo su cita;
- clienta modifica fecha, horario o servicio y recibe ambos avisos;
- clienta cambia de sucursal y la agenda recalcula la separación entre ubicaciones;
- clienta cancela dentro del plazo y la cita permanece con estado cancelado;
- una cita pública y otra administrativa elegibles generan un solo recordatorio por canal; una reprogramación o cancelación impide el envío obsoleto y un fallo no modifica la cita;
- administradora gestiona servicio, agenda, bloqueos, resultados y reenvío con permisos de la spec 002;
- una cita de Texcoco impide horarios incompatibles en Chiconcuac para el mismo profesional;
- la interfaz mantiene mensajes en español y no expone secretos ni detalles internos.
- los recorridos públicos y administrativos se ejecutan en Chromium, Firefox y WebKit a tamaños representativos desde 320 píxeles CSS, sin desplazamiento horizontal general, contenido perdido ni controles superpuestos;
- los estados principales no presentan infracciones de Axe y conservan operación por teclado, foco visible, etiquetas y errores asociados, zoom y significado independiente del color.

**RF cubiertos:** RF-01 a RF-12.  
**RNF cubiertos:** RNF-01, RNF-02, RNF-03 y RNF-06.

### 9.6 Pruebas de retiro y privacidad

- conservar la cita hasta el instante exacto definido;
- retirar después del vencimiento y conservar únicamente el agregado mensual;
- eliminar una versión antigua del aviso solo después de desaparecer su última aceptación;
- verificar que logs, errores, entregas y estadísticas no contengan código, teléfono, correo o nombre completos, y que una restauración aislada retire los datos ya vencidos antes de admitir tráfico;
- verificar que los datos de contacto solo se usen para mensajes transaccionales, que no existan analítica, rastreo ni cookies no esenciales y que la configuración y conservación documentadas de los proveedores sean compatibles antes de publicar;
- verificar el retiro diario a las 00:00, el retiro previo al tráfico durante el arranque, respaldos con separación máxima de 6 horas y conservación máxima de 7 días;
- verificar que la comprobación de salud detecte la indisponibilidad de PostgreSQL y responda sin datos ni detalles internos;
- verificar que ninguna fixture o evidencia use datos personales reales.

**RF cubiertos:** RF-03, RF-05 y RF-13.  
**RNF cubiertos:** RNF-01, RNF-02, RNF-03 y RNF-05.

### 9.7 Matriz mínima de cobertura por requisito

| Requisito | Módulos/contratos principales | Pruebas obligatorias |
|---|---|---|
| RF-01 | Catálogo, persistencia, administración | Unitarias, integración, contrato, E2E |
| RF-02 | Agenda, disponibilidad, guardia | Unitarias, concurrencia, contrato, E2E |
| RF-03 | Citas, privacidad, referencia idempotente | Unitarias, integración, contrato, E2E |
| RF-04 | Notificaciones, recordatorios y entregas | Unitarias de tiempo, integración, concurrencia, contrato, autorización y E2E |
| RF-05 | Acceso público y protección contra abuso | Unitarias, integración, seguridad, contrato, E2E |
| RF-06 | Citas y disponibilidad | Unitarias, concurrencia, contrato, E2E |
| RF-07 | Citas y notificaciones | Unitarias de borde, contrato, E2E |
| RF-08 | Agenda administrativa | Autorización, contrato, E2E |
| RF-09 | Resultado administrativo | Unitarias de estado, autorización, E2E |
| RF-10 | Bloqueos y disponibilidad | Unitarias, concurrencia, autorización, E2E |
| RF-11 | Alternativas | Unitarias de orden, contrato, E2E |
| RF-12 | Reenvío y cifrado | Integración, autorización, contrato, E2E |
| RF-13 | Retención y estadísticas | Unitarias de tiempo, integración e idempotencia |

### 9.8 Verificación de la constitución

| Principios | Verificación prevista |
|---|---|
| 1–4 | Revisión humana del alcance, dependencias justificadas, trazabilidad con la spec y dependencias dirigidas hacia el dominio. |
| 5–7 y 14 | Suite automatizada, PostgreSQL real, restricciones de integridad, concurrencia y matriz RF-01 a RF-13 en verde. |
| 8–10 | Pruebas de autenticación/autorización, sanitización, aislamiento público y escaneo para impedir secretos o `.env` versionados. |
| 11–12 | Aprobación humana del plan y cambios pequeños conforme a la secuencia de la sección 10, sin refactors ajenos. |
| 13 | Comprobación de identificadores, logs y mensajes técnicos en inglés, y contenido visible en español. |
| 15 | Playwright y Axe desde 320 píxeles CSS, navegación por teclado y revisión manual en Android e iPhone antes de publicar. |

### 9.9 Comandos de verificación previstos

Estos comandos serán obligatorios cuando las tareas correspondientes hayan creado sus configuraciones. Antes de eso son contratos del plan y no deben ejecutarse ni sustituirse por comandos inventados:

| Verificación | Comando desde la raíz del repositorio |
|---|---|
| Migraciones | `python -m alembic -c backend/alembic.ini upgrade head` |
| Pruebas unitarias | `python -m pytest backend/tests/unit` |
| Integración PostgreSQL | `python -m pytest backend/tests/integration` |
| Contratos | `python -m pytest backend/tests/contract` |
| Suite backend completa | `python -m pytest backend/tests` |
| Tipos del frontend | `npm --prefix frontend run typecheck` |
| Compilación del frontend | `npm --prefix frontend run build` |
| Recorridos E2E | `npm --prefix frontend run test:e2e` |

Una tarea no podrá declarar una verificación aprobada si su comando no existe, no termina correctamente o depende de secretos incluidos en el repositorio.

## 10. Secuencia propuesta de implementación

Cada etapa debe terminar con sus pruebas antes de avanzar.

1. **Puertas previas:** aprobar este plan, autorizar la instalación del stack en una tarea posterior y aprobar el plan de la spec 002 antes de conectar operaciones administrativas.
2. **Fundamentos:** dominio temporal, servicios, esquema inicial y reloj controlable. **RF:** RF-01, soporte de RF-02 y RF-13.
3. **Agenda:** disponibilidad, separaciones, bloqueos, guardia transaccional y alternativas. **RF:** RF-02, RF-10 y RF-11.
4. **Reserva pública:** referencia idempotente, creación, código privado y consentimiento. **RF:** RF-03 y RF-05.
5. **Cambios de cita:** consulta, modificación, cancelación y estados finales. **RF:** RF-05, RF-06, RF-07 y RF-09.
6. **Mensajería:** correo, WhatsApp, resultados independientes, recordatorio durable y reenvío. **RF:** RF-04 y RF-12.
7. **Administración:** contratos de agenda y servicios conectados a permisos de la spec 002. **RF:** RF-01, RF-03, RF-06, RF-07, RF-08, RF-09, RF-10 y RF-12.
8. **Retención y protección:** retiro diario y al arrancar, estadísticas, límites, limpieza, respaldos y comprobación de salud. **RF:** RF-05 y RF-13; **RNF:** RNF-04 y RNF-05.
9. **Verificación final:** suite completa, criterios de aceptación, seguridad, adaptabilidad, accesibilidad, compatibilidad y revisión de trazabilidad. **RF:** RF-01 a RF-13; **RNF:** RNF-01 a RNF-06.

## 11. Verificaciones para considerar implementada la spec

- todos los criterios de aceptación de RF-01 a RF-13 tienen al menos una prueba identificable;
- todas las pruebas unitarias, de integración, contrato y extremo a extremo requeridas pasan;
- las operaciones concurrentes no producen dobles reservas ni separaciones inválidas;
- no aparecen secretos o datos personales completos en URLs, logs, errores o estadísticas; los respaldos cumplen el máximo de 7 días y una restauración retira datos vencidos antes de admitir tráfico;
- las acciones administrativas fallan de forma segura sin autorización de la spec 002;
- los fallos de correo o WhatsApp quedan visibles sin revertir la operación principal;
- los estados aceptado, entregado y fallido no se confunden, y un fallo tardío puede reintentarse de forma auditable sin generar ni revelar otro código;
- cada cita pública o administrativa elegible produce un solo recordatorio por canal sin código privado; reinicios, reprogramaciones, cancelaciones y concurrencia respetan los umbrales, omisiones y reintentos aprobados sin modificar la cita;
- los simuladores permiten desarrollar y automatizar pruebas, pero RF-04 y RF-12 solo se consideran implementados después de comprobar en un entorno controlado los envíos reales de correo y WhatsApp, incluidos el éxito y el fallo independiente de cada canal;
- el retiro se ejecuta a las 00:00 y antes del tráfico tras un arranque; la frecuencia y conservación de respaldos y la comprobación de salud cumplen RNF-05;
- las interfaces públicas y administrativas cumplen RNF-06 en la matriz automatizada de tamaños y navegadores, sin infracciones de Axe en los recorridos principales, y existe evidencia manual satisfactoria en un Android y un iPhone reales antes de publicar;
- la validación jurídica pendiente se trata como puerta de salida a producción, no como requisito ya resuelto por este plan.

## 12. Puertas y riesgos todavía vigentes

1. **Plan de la spec 002:** la frontera de autorización está definida, pero las operaciones administrativas no pueden considerarse completas sin implementar y probar la autenticación correspondiente.
2. **Activación de proveedores:** Resend y WhatsApp permanecerán simulados durante el desarrollo. Antes de publicar se comprobarán su configuración y conservación de datos. Se intentará Meta directamente al final; si resulta desproporcionadamente complejo o algún proveedor no cumple la política de privacidad, se elegirá un intermediario compatible o se propondrá una modificación explícita de la spec para aprobación.
3. **Presupuesto:** $100 MXN mensuales es un objetivo, no un límite garantizado por Railway. Se configurará una alerta cercana a $85 y se comprobará que los respaldos cada 6 horas y la supervisión caben en el presupuesto. Si no caben, se detendrá el despliegue para solicitar una decisión; no se ampliará el gasto sin aprobación.
4. **Validación jurídica:** el aviso de privacidad requiere revisión jurídica antes de publicar el sistema, tal como ya está registrado en la spec.

Ninguna de estas decisiones cambia los requisitos funcionales aprobados; son puertas técnicas u operativas previas a la implementación o publicación.
