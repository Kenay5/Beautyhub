# Tareas — 001 Manita de Gato MVP

**Estado:** listas para ejecución conforme a la spec y al plan aprobados.  
**Fuentes:** `specs/001-manita_gato/spec.md` y `specs/001-manita_gato/plan.md`.  
**Regla de ejecución:** avanzar de arriba hacia abajo. Cada tarea está limitada a una pieza verificable de aproximadamente 20–30 minutos; si durante la implementación resulta mayor, deberá dividirse antes de continuar. Instalar dependencias y ejecutar tareas administrativas conservan sus puertas de aprobación explícitas. Los checkboxes de aprobación o revisión externa son puertas y no estimaciones de trabajo técnico.
**Orden cruzado:** cuando se intercale esta lista con la spec 002, seguir la guía única de `specs/002-autenticacion_administrativa/tasks.md`; dentro de cada tramo se conserva el orden de este archivo.

## 1. Puertas y base del proyecto

- [ ] **T001 — Obtener autorización para instalar el stack aprobado**
  - **RF:** soporte transversal para RF-01 a RF-13.
  - **Hecho cuando:** existe aprobación explícita para instalar únicamente las dependencias enumeradas en el plan.

- [ ] **T002 — Preparar la estructura modular del backend**
  - **RF:** soporte transversal para RF-01 a RF-13.
  - **Hecho cuando:** los límites de dominio, casos de uso, entrada web e infraestructura existen y el dominio no importa FastAPI, PostgreSQL ni proveedores.

- [ ] **T003 — Preparar la estructura del frontend público y administrativo**
  - **RF:** soporte transversal para RF-01 a RF-12.
  - **Hecho cuando:** React distingue áreas pública y administrativa y produce una compilación servible por la misma aplicación.

- [ ] **T004 — Configurar pytest para dominio e integración**
  - **RF:** soporte transversal para RF-01 a RF-13.
  - **Hecho cuando:** pytest ejecuta pruebas mínimas de dominio y PostgreSQL sin usar datos personales reales.

- [ ] **T004A — Configurar Playwright para pruebas web**
  - **RF:** soporte transversal para RF-01 a RF-12.
  - **Hecho cuando:** Playwright abre la aplicación de prueba y completa una comprobación mínima con datos ficticios.

- [ ] **T005 — Configurar variables externas y sanitización básica**
  - **RF:** soporte transversal para RF-03 a RF-13.
  - **Hecho cuando:** secretos y conexiones se leen fuera del código y una verificación confirma que no se versionan `.env`, claves ni tokens.

- [ ] **T006 — Crear reloj y generador de secretos sustituibles**
  - **RF:** RF-03, RF-05, RF-06, RF-07, RF-09, RF-11, RF-12 y RF-13.
  - **Hecho cuando:** dominio y pruebas pueden controlar el instante actual y la generación criptográfica sin depender del reloj real.

- [ ] **T007 — Configurar PostgreSQL real para integración**
  - **RF:** soporte transversal para RF-01 a RF-13.
  - **Hecho cuando:** una prueba abre una transacción en PostgreSQL, la revierte y deja la base de pruebas limpia.

## 2. Esquema e integridad persistente

- [ ] **T008 — Migrar servicios y versiones del aviso**
  - **RF:** RF-01, RF-03 y RF-13.
  - **Hecho cuando:** la migración crea ambas entidades con sus campos, relaciones y restricciones básicas aprobadas.

- [ ] **T009 — Migrar citas e instantáneas del servicio**
  - **RF:** RF-03, RF-05, RF-06, RF-07, RF-08, RF-09 y RF-13.
  - **Hecho cuando:** la cita persiste contacto, consentimiento, agenda, estado e instantánea sin depender de valores futuros del servicio.

- [ ] **T010 — Migrar referencias secretas de confirmación**
  - **RF:** RF-03 y RF-04.
  - **Hecho cuando:** la referencia tiene huella única, vencimiento, consumo y relación opcional con una única cita confirmada.

- [ ] **T011 — Migrar entregas de notificación**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** cada evento registra por separado correo y WhatsApp sin guardar el código ni contactos completos en diagnósticos.

- [ ] **T011A — Migrar la programación durable de recordatorios**
  - **RF:** RF-04-CA-14 a RF-04-CA-25.
  - **Hecho cuando:** PostgreSQL conserva vencimiento, horario, estado y arrendamiento recuperable con un recordatorio único por cita y horario y una entrega única por recordatorio y canal, y permite invalidar u omitir sin eliminar el historial mínimo de entregas.

- [ ] **T012 — Migrar bloqueos y guardia de agenda**
  - **RF:** RF-02, RF-03, RF-06, RF-10 y RF-11.
  - **Hecho cuando:** existen bloqueos globales o por sucursal y una única fila de guardia utilizable dentro de transacciones.

- [ ] **T013 — Migrar estadísticas mensuales disociadas**
  - **RF:** RF-13.
  - **Hecho cuando:** la clave impide duplicar un conteo para mes, servicio, sucursal y estado.

- [ ] **T014 — Migrar eventos mínimos de protección pública**
  - **RF:** RF-05.
  - **Hecho cuando:** pueden guardarse categoría, instante, resultado y huella con clave sin persistir IP o credencial en texto plano.

- [ ] **T015 — Verificar restricciones y reversibilidad de migraciones**
  - **RF:** RF-01 a RF-13 según las entidades afectadas.
  - **Hecho cuando:** las migraciones suben y bajan en una base limpia y PostgreSQL rechaza los estados estructuralmente inválidos definidos en el plan.

## 3. Catálogo de servicios

- [ ] **T016 — Validar nombre y descripción de servicio**
  - **RF:** RF-01.
  - **Hecho cuando:** pruebas cubren espacios externos, Unicode visible, controles, nombre vacío y límites de 1, 100 y 250 caracteres.

- [ ] **T017 — Validar duración del servicio**
  - **RF:** RF-01.
  - **Hecho cuando:** solo pasan múltiplos de 5 entre 5 y 600 minutos y las pruebas cubren sus vecinos inválidos.

- [ ] **T018 — Validar precio y sucursales del servicio**
  - **RF:** RF-01.
  - **Hecho cuando:** se aceptan 0.01–20,000.00 MXN con dos decimales y al menos una de las dos sucursales, rechazando los bordes inválidos.

- [ ] **T019 — Proteger la unicidad canónica del nombre**
  - **RF:** RF-01.
  - **Hecho cuando:** dominio y PostgreSQL rechazan duplicados ignorando mayúsculas, minúsculas y espacios externos.

- [ ] **T020 — Implementar creación interna de servicios**
  - **RF:** RF-01.
  - **Hecho cuando:** el caso de uso crea un servicio válido y no expone todavía una operación pública administrativa.

- [ ] **T020A — Implementar edición interna de servicios**
  - **RF:** RF-01.
  - **Hecho cuando:** el caso de uso actualiza únicamente los campos aprobados y vuelve a aplicar todas sus validaciones.

- [ ] **T021 — Implementar activación y desactivación interna**
  - **RF:** RF-01.
  - **Hecho cuando:** un servicio cambia de estado sin eliminarse y las citas existentes conservan su instantánea.

- [ ] **T022 — Publicar catálogo activo por sucursal**
  - **RF:** RF-01 y RF-03.
  - **Hecho cuando:** el contrato público devuelve solamente servicios activos disponibles en la sucursal elegida.

## 4. Dominio temporal y disponibilidad

- [ ] **T023 — Modelar instantes en la zona oficial**
  - **RF:** RF-02, RF-03, RF-06, RF-07, RF-09, RF-10, RF-11 y RF-13.
  - **Hecho cuando:** pruebas convierten y comparan instantes con `America/Mexico_City` sin fechas locales ambiguas.

- [ ] **T024 — Generar la cuadrícula diaria de inicios**
  - **RF:** RF-02.
  - **Hecho cuando:** solo se generan intervalos de 15 minutos entre 09:00 y 19:00, incluyendo ambos extremos.

- [ ] **T025 — Permitir comida y finalización posterior a las 19:00**
  - **RF:** RF-02.
  - **Hecho cuando:** pruebas aceptan citas durante 13:00–14:00 y una cita iniciada a las 19:00 que termina después.

- [ ] **T026 — Implementar intervalos semiabiertos**
  - **RF:** RF-02 y RF-10.
  - **Hecho cuando:** el inicio está ocupado, el final exacto está libre y los bordes con bloqueos pasan las pruebas.

- [ ] **T027 — Detectar superposición con el profesional único**
  - **RF:** RF-02.
  - **Hecho cuando:** una cita incompatible en cualquier sucursal impide otra atención simultánea en ambas.

- [ ] **T028 — Aplicar separación de 5 minutos en la misma sucursal**
  - **RF:** RF-02.
  - **Hecho cuando:** las pruebas rechazan una separación menor y aceptan el primer inicio de 15 minutos igual o posterior al mínimo.

- [ ] **T029 — Aplicar separación de 25 minutos entre sucursales**
  - **RF:** RF-02.
  - **Hecho cuando:** las pruebas rechazan una separación menor y aceptan el primer inicio de 15 minutos igual o posterior al traslado y tolerancia.

- [ ] **T030 — Evaluar vecinos anterior y posterior**
  - **RF:** RF-02 y RF-06.
  - **Hecho cuando:** una cita insertada o movida respeta la separación necesaria respecto de las citas de ambos lados.

- [ ] **T031 — Resolver citas que atraviesan medianoche**
  - **RF:** RF-02.
  - **Hecho cuando:** una cita conserva la ocupación y separación posterior aunque su final pertenezca al día siguiente.

- [ ] **T032 — Excluir estados finales de la ocupación futura**
  - **RF:** RF-02, RF-07 y RF-09.
  - **Hecho cuando:** cancelada, completada, no asistió y resultado no registrado no bloquean horarios futuros.

- [ ] **T033 — Validar anticipación pública y horizonte**
  - **RF:** RF-03 y RF-06.
  - **Hecho cuando:** pruebas aceptan exactamente 60 minutos y 90 periodos de 24 horas y rechazan un instante fuera de cada límite.

- [ ] **T034 — Validar inicio administrativo inmediato**
  - **RF:** RF-03 y RF-06.
  - **Hecho cuando:** el primer intervalo administrativo no es anterior al momento actual y mantiene cuadrícula, horizonte y disponibilidad.

- [ ] **T035 — Aplicar actividad y sucursal del servicio al candidato**
  - **RF:** RF-01, RF-02, RF-03 y RF-06.
  - **Hecho cuando:** una reservación o reprogramación rechaza servicios inactivos o no disponibles en la sucursal.

- [ ] **T036 — Calcular hasta tres alternativas del mismo día**
  - **RF:** RF-11.
  - **Hecho cuando:** se devuelven como máximo tres opciones válidas ordenadas por distancia absoluta.

- [ ] **T037 — Resolver empates y ausencia de alternativas**
  - **RF:** RF-11.
  - **Hecho cuando:** un empate prioriza el horario posterior y un día sin opciones solicita elegir otra fecha.

- [ ] **T038 — Separar horario inválido de horario ocupado**
  - **RF:** RF-11.
  - **Hecho cuando:** formato, jornada, cuadrícula, anticipación u horizonte inválidos producen su error sin calcular alternativas.

- [ ] **T039 — Serializar una creación concurrente de agenda**
  - **RF:** RF-02 y RF-03.
  - **Hecho cuando:** una prueba con PostgreSQL confirma solo una de dos reservaciones simultáneas incompatibles y no deja cambios parciales.

- [ ] **T040 — Serializar movimientos y cambios de servicio**
  - **RF:** RF-01, RF-02 y RF-06.
  - **Hecho cuando:** pruebas concurrentes conservan una agenda válida al mover citas o modificar la vigencia de un servicio.

- [ ] **T041 — Exponer consulta pública de disponibilidad**
  - **RF:** RF-02.
  - **Hecho cuando:** el contrato devuelve los inicios válidos para sucursal, servicio y fecha con errores sanitizados.

## 5. Creación pública de citas

- [ ] **T042 — Validar nombre y apellido de la adulta responsable**
  - **RF:** RF-03.
  - **Hecho cuando:** pruebas cubren 1–100 caracteres, Unicode, espacios internos, apóstrofos, guiones y caracteres rechazados.

- [ ] **T043 — Normalizar el teléfono mexicano**
  - **RF:** RF-03.
  - **Hecho cuando:** todos los formatos permitidos producen 10 dígitos y se rechazan otros prefijos, extensiones, letras o longitudes.

- [ ] **T044 — Validar y normalizar el correo obligatorio**
  - **RF:** RF-03.
  - **Hecho cuando:** los formatos y límites exactos de la spec cuentan con pruebas válidas e inválidas.

- [ ] **T045 — Registrar consentimiento y versión del aviso**
  - **RF:** RF-03 y RF-13.
  - **Hecho cuando:** la cita conserva versión, instante, origen, autorización de contacto y declaración de persona adulta responsable; si el origen es administrativo, conserva también la cuenta responsable.

- [ ] **T046 — Proteger la inmutabilidad de versiones del aviso**
  - **RF:** RF-03 y RF-13.
  - **Hecho cuando:** una versión aceptada no puede editarse ni eliminarse mientras una cita la referencie.

- [ ] **T047 — Generar código privado y huella de búsqueda**
  - **RF:** RF-03, RF-05 y RF-12.
  - **Hecho cuando:** el código tiene al menos 128 bits, es opaco, único y no contiene datos personales; la búsqueda usa su huella.

- [ ] **T048 — Cifrar el código para su reenvío posterior**
  - **RF:** RF-03 y RF-12.
  - **Hecho cuando:** puede recuperarse únicamente con la clave externa autorizada y ni base, índices ni logs contienen el código en claro.

- [ ] **T049 — Emitir una referencia secreta de confirmación**
  - **RF:** RF-03.
  - **Hecho cuando:** se devuelve una referencia sin datos personales, de al menos 128 bits y con vencimiento exacto a 24 horas.

- [ ] **T050 — Rechazar referencias ausentes o vencidas**
  - **RF:** RF-03.
  - **Hecho cuando:** no se crea ni recupera una cita al faltar la referencia o al alcanzarse exactamente su vencimiento.

- [ ] **T051 — Crear el agregado de cita programada**
  - **RF:** RF-01 y RF-03.
  - **Hecho cuando:** una cita válida conserva contacto, sucursal, horario e instantánea vigente de nombre, duración y precio.

- [ ] **T052 — Confirmar cita y entregas en una transacción**
  - **RF:** RF-02, RF-03 y RF-04.
  - **Hecho cuando:** cita y dos entregas pendientes se confirman juntas después de revalidar agenda y servicio bajo la guardia.

- [ ] **T053 — Hacer idempotente el reintento de confirmación**
  - **RF:** RF-03 y RF-04.
  - **Hecho cuando:** repetir la misma referencia devuelve cita, código y resultados originales sin crear ni enviar nuevamente.

- [ ] **T054 — Proteger la idempotencia concurrente**
  - **RF:** RF-03 y RF-04.
  - **Hecho cuando:** dos confirmaciones simultáneas con la misma referencia devuelven el mismo resultado y crean como máximo una cita.

- [ ] **T055 — Exponer emisión pública de referencia**
  - **RF:** RF-03.
  - **Hecho cuando:** el contrato genera una referencia secreta y distingue vencimiento y límite sin exponer datos internos.

- [ ] **T055A — Exponer confirmación pública de cita**
  - **RF:** RF-03, RF-04 y RF-11.
  - **Hecho cuando:** el contrato acepta solo los campos aprobados y distingue validación, conflicto, referencia y límite.

- [ ] **T056 — Construir selección pública de sucursal y servicio**
  - **RF:** RF-01 y RF-03.
  - **Hecho cuando:** la clienta elige valores de listas activas y no puede escribir libremente el servicio.

- [ ] **T057 — Construir selección pública de fecha y horario**
  - **RF:** RF-02, RF-03 y RF-11.
  - **Hecho cuando:** la pantalla muestra disponibilidad o alternativas del mismo día y explica en español los horarios inválidos.

- [ ] **T058 — Construir datos personales y consentimiento público**
  - **RF:** RF-03.
  - **Hecho cuando:** todos los datos obligatorios y las tres confirmaciones de privacidad y responsabilidad se validan antes del envío.

- [ ] **T059 — Construir la confirmación pública única**
  - **RF:** RF-03 y RF-04.
  - **Hecho cuando:** la pantalla posterior a crear o reintentar muestra una sola cita, su resumen, código y estado de cada canal.

- [ ] **T060 — Verificar el recorrido público de creación**
  - **RF:** RF-01, RF-02, RF-03, RF-04 y RF-11.
  - **Hecho cuando:** Playwright reserva con datos ficticios y comprueba código, resumen y aislamiento respecto de otras citas.

## 6. Consulta pública y protección contra abuso

- [ ] **T061 — Consultar exclusivamente por huella de código**
  - **RF:** RF-05.
  - **Hecho cuando:** un código válido devuelve únicamente su cita y no existe búsqueda pública por datos personales.

- [ ] **T062 — Enmascarar teléfono y correo**
  - **RF:** RF-05.
  - **Hecho cuando:** las pruebas reproducen exactamente los formatos ocultos definidos, incluidos correos con una sola letra.

- [ ] **T063 — Aplicar vigencia pública de 30 días**
  - **RF:** RF-05 y RF-13.
  - **Hecho cuando:** cualquier estado es consultable hasta las 23:59:59 del límite y deja de serlo a las 00:00 siguientes.

- [ ] **T064 — Uniformar errores de credenciales públicas**
  - **RF:** RF-05, RF-06 y RF-07.
  - **Hecho cuando:** código inexistente, mal formado, vencido o combinado con teléfono incorrecto producen una respuesta indistinguible.

- [ ] **T065 — Contar fallos móviles de credenciales**
  - **RF:** RF-05.
  - **Hecho cuando:** el quinto fallo en 15 minutos bloquea la IP y un éxito no borra fallos todavía vigentes.

- [ ] **T066 — Aplicar y vencer el bloqueo de credenciales**
  - **RF:** RF-05.
  - **Hecho cuando:** solicitudes bloqueadas no prolongan ni incrementan el bloqueo y otras IP o administración siguen disponibles.

- [ ] **T067 — Limitar catálogo y disponibilidad a 60 por minuto**
  - **RF:** RF-01, RF-02 y RF-05.
  - **Hecho cuando:** la solicitud 60 se acepta, la 61 se rechaza y los rechazos no amplían la ventana móvil.

- [ ] **T068 — Limitar operaciones públicas de cita a 10 por 15 minutos**
  - **RF:** RF-03, RF-05, RF-06 y RF-07.
  - **Hecho cuando:** la operación 10 se acepta, la 11 se rechaza antes de consultar o modificar datos y no amplía la ventana.

- [ ] **T069 — Combinar límites sin reducir la denegación**
  - **RF:** RF-05.
  - **Hecho cuando:** al coincidir límite general y bloqueo de credenciales se aplica el vencimiento que mantenga el acceso denegado más tiempo.

- [ ] **T070 — Exponer consulta pública sin secretos en URL**
  - **RF:** RF-05.
  - **Hecho cuando:** el código viaja únicamente en el cuerpo, la respuesta está sanitizada y ningún log o URL lo contiene.

- [ ] **T071 — Construir la pantalla pública de consulta**
  - **RF:** RF-05.
  - **Hecho cuando:** muestra el resumen y contactos ocultos de una sola cita y presenta acciones solo cuando están permitidas.

- [ ] **T072 — Verificar aislamiento público entre citas**
  - **RF:** RF-05.
  - **Hecho cuando:** pruebas de contrato cubren otras citas, respuestas genéricas y ausencia de secretos.

- [ ] **T072A — Verificar límites públicos bajo concurrencia**
  - **RF:** RF-05.
  - **Hecho cuando:** pruebas concurrentes cubren los bordes de cada ventana y confirman que los rechazos no las amplían.

## 7. Modificación y cancelación públicas

- [ ] **T073 — Autorizar modificación pública por código y teléfono**
  - **RF:** RF-06.
  - **Hecho cuando:** solo una cita programada con credenciales correctas y al menos 60 minutos restantes puede continuar.

- [ ] **T074 — Restringir campos de modificación pública**
  - **RF:** RF-06.
  - **Hecho cuando:** solo fecha, horario, sucursal o servicio se aceptan y cualquier cambio de contacto o nombre se rechaza.

- [ ] **T075 — Revalidar una reprogramación pública**
  - **RF:** RF-01, RF-02, RF-06 y RF-11.
  - **Hecho cuando:** se excluye la cita actual, se revalida agenda, servicio, anticipación y horizonte, y se conservan cambios en forma atómica.

- [ ] **T076 — Aplicar instantáneas al modificar**
  - **RF:** RF-01 y RF-06.
  - **Hecho cuando:** fecha, hora o sucursal conservan precio; cambiar servicio actualiza duración y precio vigentes sin cambiar el código.

- [ ] **T077 — Exponer modificación pública y alternativas**
  - **RF:** RF-04, RF-06 y RF-11.
  - **Hecho cuando:** el contrato devuelve cita modificada o error genérico/conflicto con alternativas sin volver a mostrar el código.

- [ ] **T078 — Construir la pantalla pública de modificación**
  - **RF:** RF-06 y RF-11.
  - **Hecho cuando:** solo ofrece campos permitidos y muestra en español éxito, límites o alternativas.

- [ ] **T079 — Validar motivo opcional de cancelación**
  - **RF:** RF-07.
  - **Hecho cuando:** se aceptan hasta 250 caracteres Unicode visibles, se retiran espacios y vacío equivale a ausencia.

- [ ] **T080 — Cancelar públicamente de forma atómica**
  - **RF:** RF-02 y RF-07.
  - **Hecho cuando:** credenciales y límite temporal válidos cambian a cancelada, conservan la cita y liberan disponibilidad sin cambios parciales.

- [ ] **T081 — Exponer cancelación pública**
  - **RF:** RF-04 y RF-07.
  - **Hecho cuando:** el contrato acepta exactamente una hora antes, rechaza un instante después y nunca revela el motivo ni el código.

- [ ] **T082 — Construir confirmación pública de cancelación**
  - **RF:** RF-04 y RF-07.
  - **Hecho cuando:** la pantalla confirma estado y canales sin volver a mostrar el código privado.

- [ ] **T083 — Verificar estados finales en cambios públicos**
  - **RF:** RF-06 y RF-07.
  - **Hecho cuando:** pruebas impiden modificar, cancelar o reactivar cualquier cita con estado final.

## 8. Notificaciones transaccionales y recordatorios simulados

- [ ] **T084 — Definir puertos y resultados por canal**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** correo y WhatsApp comparten un resultado controlado de éxito o fallo sin que el dominio dependa del proveedor.

- [ ] **T084A — Modelar estados de una entrega**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** solo se permiten transiciones válidas entre pendiente, aceptada por el proveedor, entregada y fallida.

- [ ] **T085 — Preparar plantilla de creación**
  - **RF:** RF-04.
  - **Hecho cuando:** ambos canales reciben servicio, fecha, hora, sucursal, duración, estado, precio y código.

- [ ] **T086 — Preparar plantillas de modificación y cancelación**
  - **RF:** RF-04, RF-06 y RF-07.
  - **Hecho cuando:** ambos mensajes contienen el resumen aprobado y no revelan nuevamente el código.

- [ ] **T086A — Preparar el mensaje separado por corrección de contacto**
  - **RF:** RF-04 y RF-06.
  - **Hecho cuando:** el mensaje dirigido al teléfono o correo nuevo contiene el mismo código sin incorporarlo a la confirmación ordinaria de modificación.

- [ ] **T087 — Implementar simulador de correo**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** las pruebas controlan éxito o fallo y registran el resultado sin realizar envíos reales.

- [ ] **T088 — Implementar simulador de WhatsApp**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** las pruebas controlan éxito, teléfono sin WhatsApp o fallo y registran el resultado sin envíos reales.

- [ ] **T089 — Despachar canales independientemente tras el commit**
  - **RF:** RF-04.
  - **Hecho cuando:** cada aceptación o fallo inmediato conserva la operación principal y registra ambos resultados sanitizados sin afirmar entrega.

- [ ] **T089A — Procesar confirmaciones y fallos tardíos**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** una actualización auténtica del proveedor cambia la entrega correspondiente sin modificar la cita ni otra entrega.

- [ ] **T090 — Conectar notificaciones de creación**
  - **RF:** RF-03 y RF-04.
  - **Hecho cuando:** crear una cita inicia exactamente un intento por canal después del commit.

- [ ] **T091 — Conectar notificaciones de modificación y cancelación**
  - **RF:** RF-04, RF-06 y RF-07.
  - **Hecho cuando:** cada cambio confirmado inicia un intento por canal y un fallo no revierte cita ni estado.

- [ ] **T092 — Verificar que un reintento no renotifica**
  - **RF:** RF-03 y RF-04.
  - **Hecho cuando:** repetir una confirmación devuelve resultados originales incluso si fallaron, sin nuevos intentos.

- [ ] **T093 — Mostrar fallos parciales sin detalles internos**
  - **RF:** RF-04.
  - **Hecho cuando:** contratos y pantallas identifican el canal fallido sin exponer proveedor, credenciales o trazas.

- [ ] **T093A — Preparar el reintento interno de una entrega fallida**
  - **RF:** RF-04.
  - **Hecho cuando:** el caso de uso crea un intento enlazado y auditable al contacto vigente sin alterar la cita ni generar otro código.

- [ ] **T093B — Decidir la elegibilidad inicial del recordatorio**
  - **RF:** RF-04-CA-14 y RF-04-CA-16.
  - **Hecho cuando:** una cita pública o administrativa con más de 24 horas programa un único recordatorio a las 24 horas previas y una con exactamente 24 horas o menos no lo programa.

- [ ] **T093C — Sustituir o invalidar recordatorios al cambiar la cita**
  - **RF:** RF-04-CA-15, RF-04-CA-16 y RF-04-CA-20.
  - **Hecho cuando:** reprogramar invalida el pendiente anterior y crea como máximo el nuevo elegible, mientras cancelar impide el pendiente sin cambios parciales.

- [ ] **T093D — Preparar la plantilla segura del recordatorio**
  - **RF:** RF-04-CA-17 y RF-04-CA-18.
  - **Hecho cuando:** correo y WhatsApp usan los contactos vigentes e incluyen solo servicio, fecha, horario, sucursal, duración y precio, sin código ni enlace que permita recuperarlo.

- [ ] **T093E — Reclamar y procesar recordatorios vencidos**
  - **RF:** RF-04-CA-17, RF-04-CA-19 y RF-04-CA-24.
  - **Hecho cuando:** procesos concurrentes reclaman una sola vez cada recordatorio, recuperan una reclamación abandonada antes del inicio registrado, procesan un vencido con más de 60 minutos restantes y omiten definitivamente uno con 60 minutos o menos.

- [ ] **T093F — Resolver cambios concurrentes y resultados por canal**
  - **RF:** RF-04-CA-20 a RF-04-CA-22 y RF-04-CA-25.
  - **Hecho cuando:** una transacción breve registra el inicio antes de contactar al proveedor, los cambios confirmados antes lo impiden, los posteriores conservan el posible envío y generan su notificación ordinaria, y ningún resultado modifica la cita.

- [ ] **T093G — Restringir reintentos manuales de recordatorios**
  - **RF:** RF-04-CA-22 a RF-04-CA-25; integración con RF-10-CA-02 y límites de la spec 002.
  - **Hecho cuando:** propietario o personal reintentan solo el canal fallido, al contacto vigente, más de 60 minutos antes, hasta tres veces, separados por cinco minutos y consumiendo el límite administrativo una vez por solicitud.

- [ ] **T093H — Probar recordatorios con PostgreSQL y concurrencia**
  - **RF:** RF-04-CA-14 a RF-04-CA-25.
  - **Hecho cuando:** pruebas con reloj controlado cubren ambos orígenes, bordes de 24 horas y 60 minutos, reinicio, reprogramación, cancelación, fallos independientes, reintentos y procesos simultáneos sin duplicados.

## 9. Puerta y operaciones administrativas

- [ ] **T094 — Aprobar el plan de la spec 002 y disponer de su frontera de autorización**
  - **RF:** puerta para RF-01, RF-03, RF-06, RF-07, RF-08, RF-09, RF-10 y RF-12.
  - **Hecho cuando:** el plan 002 está aprobado y las pruebas pueden representar propietario, personal, no autenticado y no autorizado.

- [ ] **T095 — Proteger todos los contratos administrativos**
  - **RF:** RF-01, RF-03, RF-06, RF-07, RF-08, RF-09, RF-10 y RF-12.
  - **Hecho cuando:** existe una frontera reutilizable que niega acceso sin identidad o permiso suficiente antes de invocar cualquier caso de uso.

- [ ] **T096 — Exponer gestión de servicios solo al propietario**
  - **RF:** RF-01.
  - **Hecho cuando:** propietario crea, edita, activa o desactiva y personal recibe una denegación segura.

- [ ] **T097 — Listar y filtrar agenda administrativa**
  - **RF:** RF-08.
  - **Hecho cuando:** una identidad autorizada filtra citas de ambas sucursales por fecha, sucursal y estado.

- [ ] **T098 — Buscar agenda por valores exactos**
  - **RF:** RF-08.
  - **Hecho cuando:** código, teléfono normalizado y fecha requieren coincidencia exacta y el código se busca por huella.

- [ ] **T099 — Buscar por nombre o apellido**
  - **RF:** RF-08.
  - **Hecho cuando:** espacios externos, coincidencias parciales, mayúsculas y acentos se comportan como indica la spec.

- [ ] **T100 — Mostrar detalle administrativo sin código**
  - **RF:** RF-08.
  - **Hecho cuando:** se muestran los campos aprobados y el código privado nunca forma parte de la respuesta.

- [ ] **T101 — Crear citas administrativamente**
  - **RF:** RF-03, RF-04 y RF-11.
  - **Hecho cuando:** se registra autorización de la adulta responsable y se permite el primer intervalo no anterior al momento actual.

- [ ] **T102 — Modificar agenda administrativamente**
  - **RF:** RF-01, RF-02, RF-06 y RF-11.
  - **Hecho cuando:** antes del inicio se cambian fecha, hora, sucursal o servicio con revalidación; desde el inicio se rechaza.

- [ ] **T103 — Corregir datos personales administrativamente**
  - **RF:** RF-03 y RF-06.
  - **Hecho cuando:** nombre, apellido, teléfono y correo se revalidan y la cita conserva el mismo código sin mostrarlo.

- [ ] **T103A — Reenviar el código después de corregir un contacto**
  - **RF:** RF-04 y RF-06.
  - **Hecho cuando:** el mismo código se envía mediante el mensaje separado a los contactos actualizados y ambos resultados quedan registrados.

- [ ] **T104 — Cancelar administrativamente**
  - **RF:** RF-04 y RF-07.
  - **Hecho cuando:** antes del inicio se conserva motivo solo administrativo y se rechaza desde el inicio exacto.

- [ ] **T105 — Marcar una cita completada**
  - **RF:** RF-09.
  - **Hecho cuando:** solo una cita programada puede completarse desde su final exacto y nunca antes.

- [ ] **T106 — Marcar una cita como no asistió**
  - **RF:** RF-02 y RF-09.
  - **Hecho cuando:** se permite desde cinco minutos exactos después del inicio, libera disponibilidad y no admite reactivación.

- [ ] **T107 — Proteger la llegada posterior a una inasistencia**
  - **RF:** RF-03 y RF-09.
  - **Hecho cuando:** la cita original conserva su estado final y una atención nueva exige otra cita administrativa disponible.

## 10. Bloqueos administrativos

- [ ] **T108 — Validar intervalo y alcance de bloqueos**
  - **RF:** RF-10.
  - **Hecho cuando:** inicio y fin usan cuadrícula y zona oficial, fin es posterior y el alcance es global o una sucursal.

- [ ] **T109 — Permitir bloqueos largos y entre días**
  - **RF:** RF-10.
  - **Hecho cuando:** pruebas aceptan bloqueos que cruzan medianoche o varios días sin duración máxima.

- [ ] **T110 — Aplicar bloqueos globales y de sucursal**
  - **RF:** RF-02 y RF-10.
  - **Hecho cuando:** el global bloquea ambas sucursales y el local solo su sucursal sin representar ubicación del profesional.

- [ ] **T111 — Rechazar bloqueos contra citas programadas**
  - **RF:** RF-02 y RF-10.
  - **Hecho cuando:** crear o editar un bloqueo conflictivo falla sin mover ni cancelar la cita.

- [ ] **T112 — Rechazar bloqueos redundantes**
  - **RF:** RF-10.
  - **Hecho cuando:** pruebas cubren superposición del mismo alcance y cruces redundantes entre global y sucursal.

- [ ] **T113 — Editar y eliminar bloqueos**
  - **RF:** RF-02 y RF-10.
  - **Hecho cuando:** editar revalida todas las reglas y eliminar libera el periodo sin alterar citas.

- [ ] **T114 — Serializar bloqueos con la agenda**
  - **RF:** RF-02, RF-03 y RF-10.
  - **Hecho cuando:** una cita y un bloqueo concurrentes dejan como máximo una combinación válida y ninguna escritura parcial.

- [ ] **T115 — Exponer gestión administrativa de bloqueos**
  - **RF:** RF-10.
  - **Hecho cuando:** contratos autorizados crean, editan y eliminan con errores de validación, conflicto o permiso controlados.

## 11. Recuperación administrativa del código

- [ ] **T116 — Validar elegibilidad del reenvío**
  - **RF:** RF-05 y RF-12.
  - **Hecho cuando:** solo una cita todavía vigente puede reenviarse y una cita retirada o código expirado se rechaza.

- [ ] **T117 — Reenviar el mismo código a contactos registrados**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** una acción autorizada descifra el código sin mostrarlo y lo entrega únicamente al teléfono y correo almacenados.

- [ ] **T118 — Registrar fallos independientes de recuperación**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** cualquier fallo conserva cita y código, registra ambos canales e informa al administrador sin detalles internos.

- [ ] **T118A — Exponer el reintento de una notificación fallida**
  - **RF:** RF-04.
  - **Hecho cuando:** el contrato permite a propietario y personal reintentar solo una entrega elegible al contacto registrado y nunca muestra ni genera un código privado.

- [ ] **T119 — Construir la lista y búsqueda de agenda administrativa**
  - **RF:** RF-08.
  - **Hecho cuando:** la interfaz lista y filtra ambas sucursales y presenta coincidencias exactas o parciales según el campo.

- [ ] **T119A — Construir el detalle administrativo de una cita**
  - **RF:** RF-08, RF-09 y RF-12.
  - **Hecho cuando:** muestra los datos aprobados sin el código y ofrece únicamente acciones permitidas por estado y rol.

- [ ] **T120 — Construir gestión administrativa de servicios**
  - **RF:** RF-01.
  - **Hecho cuando:** el propietario gestiona campos y sucursales desde listas controladas y el personal no ve acciones no autorizadas.

- [ ] **T121 — Construir creación administrativa de citas**
  - **RF:** RF-03.
  - **Hecho cuando:** la interfaz reúne los campos, confirmaciones y límites aprobados para registrar una cita administrativa.

- [ ] **T121A — Construir modificación administrativa de citas**
  - **RF:** RF-06.
  - **Hecho cuando:** la interfaz permite los campos administrativos aprobados y explica en español cualquier rechazo.

- [ ] **T121B — Construir cancelación administrativa de citas**
  - **RF:** RF-07.
  - **Hecho cuando:** la interfaz solicita el motivo opcional y confirma la cancelación sin mostrar el código.

- [ ] **T121C — Construir registro administrativo de resultado**
  - **RF:** RF-09.
  - **Hecho cuando:** la interfaz ofrece completar o marcar no asistencia únicamente cuando el instante y estado lo permiten.

- [ ] **T122 — Construir gestión administrativa de bloqueos**
  - **RF:** RF-10.
  - **Hecho cuando:** la interfaz crea, edita y elimina bloqueos únicos con alcance e intervalo válidos.

- [ ] **T122A — Construir recuperación administrativa del código**
  - **RF:** RF-12.
  - **Hecho cuando:** la interfaz solicita explícitamente el reenvío a los contactos registrados sin revelar el código.

- [ ] **T122B — Construir reintento administrativo de notificación**
  - **RF:** RF-04.
  - **Hecho cuando:** propietario o personal pueden reintentar una entrega fallida elegible bajo sus límites y el nuevo estado se muestra sin código ni detalles internos.

- [ ] **T123 — Verificar autorización de servicios y agenda**
  - **RF:** RF-01 y RF-08.
  - **Hecho cuando:** pruebas cubren propietario, personal, permiso insuficiente y ausencia de sesión en servicios, lista, búsqueda y detalle.

- [ ] **T123A — Verificar autorización de acciones administrativas**
  - **RF:** RF-03, RF-04, RF-06, RF-07, RF-09, RF-10 y RF-12.
  - **Hecho cuando:** pruebas cubren permiso suficiente, insuficiente y ausencia de sesión para cada acción restante.

## 12. Retiro, limpieza y privacidad

- [ ] **T124 — Calcular el instante de retiro operativo**
  - **RF:** RF-05 y RF-13.
  - **Hecho cuando:** usa la última fecha programada, incluso cancelada o modificada, y respeta exactamente 23:59:59/00:00 en la zona oficial.

- [ ] **T125 — Convertir citas sin resultado antes del retiro**
  - **RF:** RF-09 y RF-13.
  - **Hecho cuando:** una cita aún programada cambia a resultado no registrado justo antes de contabilizarse y retirarse.

- [ ] **T126 — Agregar la estadística mensual**
  - **RF:** RF-13.
  - **Hecho cuando:** se incrementa solo mes, servicio, sucursal y estado sin nombre, contacto, código ni identificador de cita.

- [ ] **T127 — Retirar cita y datos asociados**
  - **RF:** RF-05, RF-08, RF-12 y RF-13.
  - **Hecho cuando:** tras el límite no puede consultarse ni gestionarse y en el almacenamiento operativo solo permanece el conteo disociado.

- [ ] **T128 — Hacer idempotente el proceso de retiro**
  - **RF:** RF-13.
  - **Hecho cuando:** ejecutar dos veces el mismo lote no duplica estadísticas ni intenta retirar otra vez la cita.

- [ ] **T128A — Denegar inmediatamente el acceso a citas vencidas**
  - **RF:** RF-05, RF-08, RF-12 y RF-13.
  - **Hecho cuando:** toda consulta u operación trata la cita como retirada desde las 00:00 aunque la limpieza física aún no haya concluido.

- [ ] **T128B — Programar el retiro diario a medianoche**
  - **RF:** RF-09 y RF-13.
  - **Hecho cuando:** el proceso idempotente se inicia cada día a las 00:00 de `America/Mexico_City` y registra un fallo sanitizado si no termina.

- [ ] **T128C — Ejecutar retiros pendientes antes del tráfico inicial**
  - **RF:** RF-09 y RF-13.
  - **Hecho cuando:** un arranque con citas vencidas completa su retiro antes de declarar saludable la aplicación.

- [ ] **T129 — Limpiar referencias y eventos vencidos**
  - **RF:** RF-03 y RF-05.
  - **Hecho cuando:** referencias fuera de su utilidad y huellas de protección fuera de sus ventanas se eliminan sin afectar citas vigentes.

- [ ] **T130 — Retirar versiones antiguas del aviso sin referencias**
  - **RF:** RF-03 y RF-13.
  - **Hecho cuando:** una versión se elimina solo después de desaparecer su última aceptación asociada.

- [ ] **T131 — Verificar privacidad de logs y diagnósticos**
  - **RF:** RF-03, RF-04, RF-05, RF-08, RF-12 y RF-13.
  - **Hecho cuando:** una inspección automatizada no encuentra códigos, referencias, teléfonos, correos o nombres completos en logs, errores, entregas o estadísticas.

- [ ] **T132 — Verificar finalidades y rastreo del MVP**
  - **RF:** RF-03, RF-04 y RF-13.
  - **Hecho cuando:** no existen promociones, analítica, píxeles o cookies no esenciales y los contactos solo alimentan mensajes transaccionales.

- [ ] **T133 — Documentar la restauración aislada**
  - **RF:** RF-13.
  - **Hecho cuando:** el procedimiento exige restaurar sin tráfico, retirar datos vencidos y verificar el resultado antes de habilitar la aplicación.

- [ ] **T133A — Probar la restauración aislada**
  - **RF:** RF-13.
  - **Hecho cuando:** un ejercicio controlado restaura un respaldo, retira lo vencido y solo entonces supera la comprobación de disponibilidad.

- [ ] **T134 — Configurar respaldos cifrados cada seis horas**
  - **RF:** RF-13.
  - **Hecho cuando:** la configuración comprobada limita la separación a seis horas, el acceso autorizado y la conservación a siete días sin ampliar el presupuesto.

- [ ] **T134A — Respaldar antes de una migración de producción**
  - **RF:** RF-13.
  - **Hecho cuando:** el procedimiento de despliegue impide aplicar una migración sin confirmar primero un respaldo recuperable.

- [ ] **T134B — Implementar comprobación técnica de salud**
  - **RF:** soporte transversal para RF-01 a RF-13.
  - **Hecho cuando:** una comprobación confirma aplicación y PostgreSQL sin revelar versiones, consultas, credenciales ni datos internos.

- [ ] **T134C — Configurar alerta por fallo de salud**
  - **RF:** soporte transversal para RF-01 a RF-13.
  - **Hecho cuando:** un fallo controlado de aplicación o PostgreSQL avisa al responsable del proyecto mediante un mecanismo incluido en el presupuesto aprobado.

## 13. Proveedores reales y puertas de publicación

- [ ] **T135 — Verificar conservación de datos de Resend**
  - **RF:** RF-04, RF-12 y RF-13.
  - **Hecho cuando:** su política y configuración mínima quedan documentadas como compatibles o el proveedor queda rechazado antes de publicar.

- [ ] **T136 — Verificar conservación de datos del proveedor de WhatsApp**
  - **RF:** RF-04, RF-12 y RF-13.
  - **Hecho cuando:** su política y configuración mínima quedan documentadas como compatibles o el proveedor queda rechazado antes de publicar.

- [ ] **T137 — Configurar credenciales y cliente real de correo**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** Resend o el sustituto aprobado usa credenciales externas y puede aceptar una solicitud ficticia controlada.

- [ ] **T137A — Traducir respuestas del proveedor de correo**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** aceptación y rechazo inmediatos producen los estados internos correctos sin exponer la respuesta del proveedor.

- [ ] **T137B — Recibir estados tardíos de correo**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** una notificación auténtica del proveedor actualiza únicamente la entrega correspondiente a entregada o fallida.

- [ ] **T138 — Comprobar correo real en entorno controlado**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** se verifican entrega, fallo controlado y plantilla de recordatorio sin código privado, sin datos personales reales ni reversión de la operación.

- [ ] **T139 — Configurar credenciales y cliente real de WhatsApp**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** Meta o el sustituto aprobado usa credenciales externas y puede aceptar una solicitud ficticia controlada.

- [ ] **T139A — Enviar plantillas mediante el proveedor de WhatsApp**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** creación, modificación, cancelación, recordatorio y reenvío usan la plantilla correspondiente a través del mismo puerto del simulador.

- [ ] **T139B — Traducir respuestas inmediatas de WhatsApp**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** aceptación y rechazo inmediatos producen los estados internos correctos sin exponer detalles del proveedor.

- [ ] **T139C — Recibir estados tardíos de WhatsApp**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** una notificación auténtica del proveedor actualiza únicamente la entrega correspondiente a entregada o fallida.

- [ ] **T140 — Comprobar WhatsApp real en entorno controlado**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** se verifican entrega, número sin WhatsApp, fallo controlado y plantilla de recordatorio sin código privado, sin datos personales reales ni reversión.

- [ ] **T141 — Comprobar fallos cruzados de canales reales**
  - **RF:** RF-04 y RF-12.
  - **Hecho cuando:** correo solo, WhatsApp solo y fallo de ambos conservan la operación y muestran únicamente el estado permitido.

- [ ] **T142 — Mantener la puerta jurídica en la lista de publicación**
  - **RF:** RF-03, RF-04, RF-05 y RF-13.
  - **Hecho cuando:** la lista impide publicar mientras no exista una decisión jurídica externa aprobada e incorporada a una spec; obtener el dictamen no forma parte de esta implementación.

## 14. Verificación final

- [ ] **T143 — Verificar recorrido E2E de consulta y modificación**
  - **RF:** RF-04, RF-05, RF-06 y RF-11.
  - **Hecho cuando:** Playwright consulta una sola cita, modifica campos permitidos y comprueba resumen, alternativas y avisos.

- [ ] **T144 — Verificar recorrido E2E de cancelación**
  - **RF:** RF-02, RF-04 y RF-07.
  - **Hecho cuando:** Playwright cancela dentro del límite, confirma el estado y verifica que el horario queda disponible.

- [ ] **T145 — Verificar recorrido E2E entre sucursales**
  - **RF:** RF-02, RF-03, RF-06 y RF-11.
  - **Hecho cuando:** una cita en una sucursal impide en la otra los horarios incompatibles y un cambio recalcula 25 minutos.

- [ ] **T146 — Verificar E2E de servicios y consulta administrativa**
  - **RF:** RF-01 y RF-08.
  - **Hecho cuando:** una sesión autorizada gestiona un servicio y consulta ambas sucursales sin mostrar el código privado.

- [ ] **T146A — Verificar E2E de acciones administrativas de cita**
  - **RF:** RF-03, RF-06, RF-07 y RF-09.
  - **Hecho cuando:** una sesión autorizada crea, modifica, cancela y registra el resultado usando citas ficticias independientes.

- [ ] **T146B — Verificar E2E de bloqueos y reenvíos**
  - **RF:** RF-04, RF-10 y RF-12.
  - **Hecho cuando:** una sesión autorizada gestiona un bloqueo y reenvía o reintenta una entrega sin mostrar el código.

- [ ] **T146C — Verificar E2E del recordatorio previo**
  - **RF:** RF-04-CA-14 a RF-04-CA-25.
  - **Hecho cuando:** Playwright confirma un recordatorio sin código para una cita elegible y comprueba reprogramación, cancelación, canal fallido y reintento permitido con reloj y proveedores controlados.

- [ ] **T147 — Ejecutar la suite completa**
  - **RF:** RF-01 a RF-13.
  - **Hecho cuando:** pruebas unitarias, PostgreSQL, contratos y Playwright pasan sin omisiones ni datos personales reales.

- [ ] **T148 — Auditar seguridad y secretos**
  - **RF:** RF-01 a RF-13 de forma transversal.
  - **Hecho cuando:** entradas se validan, administración está protegida y no hay secretos o datos privados expuestos.

- [ ] **T148A — Auditar idioma y zona horaria**
  - **RF:** RF-01 a RF-13 de forma transversal.
  - **Hecho cuando:** contenido visible está en español y todos los bordes temporales usan `America/Mexico_City`.

- [ ] **T149 — Cerrar la matriz de trazabilidad**
  - **RF:** RF-01 a RF-13.
  - **Hecho cuando:** la matriz de este archivo apunta cada criterio EARS a pruebas realmente existentes y no queda ningún RF sin evidencia.

- [ ] **T150 — Realizar revisión humana final**
  - **RF:** RF-01 a RF-13.
  - **Hecho cuando:** el responsable comprende los cambios, confirma las verificaciones y registra riesgos o puertas de publicación todavía pendientes.

## 15. Matriz inicial de criterios EARS

Esta matriz evita esperar hasta el cierre para detectar criterios sin tarea. T149 deberá sustituir estas referencias previstas por las pruebas realmente implementadas.

| Requisito | Criterios | Tareas responsables |
|---|---|---|
| RF-01 | CA-01–CA-02; CA-03; CA-04; CA-05; CA-06; CA-07–CA-09 | T016; T019; T017; T018; T021/T022/T035; T021/T035/T076 |
| RF-02 | CA-01; CA-02–CA-03; CA-04; CA-05; CA-06; CA-07; CA-08; CA-09; CA-10–CA-11; CA-12; CA-13 | T024; T025; T028; T029; T027–T030; T110; T032; T031; T039/T040/T052/T075/T114; T026; T028/T029 |
| RF-03 | CA-01; CA-02; CA-03; CA-04; CA-05; CA-06–CA-07; CA-08; CA-09–CA-10; CA-11; CA-12; CA-13; CA-14; CA-15; CA-16; CA-17; CA-18; CA-19; CA-20 | T042; T043; T044; T045/T058; T045/T101; T035/T051/T056; T033; T051/T052; T047; T052/T055A; T045/T101; T046; T034/T101; T049; T053; T054; T050/T053; T049/T050 |
| RF-04 | CA-01; CA-02–CA-05; CA-06; CA-07; CA-08–CA-09; CA-10; CA-11; CA-12; CA-13; CA-14; CA-15; CA-16; CA-17; CA-18; CA-19; CA-20–CA-21; CA-22; CA-23; CA-24; CA-25 | T059; T085/T086/T090/T091; T053/T059; T077/T082; T088/T089/T093; T092; T084A/T089A/T138/T140; T089A/T093A/T118A; T086A/T093A/T103A/T118A; T011A/T093B; T011A/T093C; T093B/T093C; T093D/T093E; T093D; T093E; T093C/T093F; T093F/T093G; T093G/T118A/T122B; T011A/T093E/T093H; T093F/T093G |
| RF-05 | CA-01–CA-02; CA-03; CA-04; CA-05; CA-06; CA-07; CA-08; CA-09; CA-10; CA-11 | T061/T071; T062; T071; T064/T070; T063/T124/T128A; T065; T066; T064/T065; T065; T066 |
| RF-06 | CA-01; CA-02; CA-03; CA-04; CA-05; CA-06–CA-08; CA-09; CA-10; CA-11; CA-12; CA-13; CA-14; CA-15 | T073; T095/T102; T073; T102; T103; T076; T103A; T075/T102; T083; T064/T077; T075/T102; T074; T102/T103 |
| RF-07 | CA-01; CA-02; CA-03; CA-04; CA-05; CA-06; CA-07; CA-08; CA-09 | T080; T095/T104; T080/T081; T079/T080; T079; T080/T083/T104; T081/T100; T064/T081; T104 |
| RF-08 | CA-01–CA-02; CA-03; CA-04; CA-05; CA-06 | T097; T098/T099; T100; T095; T098/T099 |
| RF-09 | CA-01; CA-02; CA-03; CA-04; CA-05; CA-06; CA-07; CA-08 | T105; T106; T105/T106/T125; T125; T083/T105/T106; T105; T106; T107 |
| RF-10 | CA-01; CA-02; CA-03; CA-04; CA-05–CA-07; CA-08–CA-09; CA-10–CA-12 | T108/T110; T108; T109; T111; T110; T113; T112 |
| RF-11 | CA-01; CA-02; CA-03; CA-04 | T036; T037; T037; T038 |
| RF-12 | CA-01–CA-02; CA-03; CA-04 | T116/T117/T122A; T116; T118 |
| RF-13 | CA-01–CA-02; CA-03; CA-04; CA-05–CA-06; CA-07; CA-08 | T063/T124/T127/T128A; T125; T126/T127/T128; T124; T128A; T128B/T128C |

| Requisito no funcional | Tareas responsables |
|---|---|
| RNF-01 | T005, T047, T048, T064, T070, T072, T093D, T093G, T095, T131, T132 y T148 |
| RNF-02 | T011A, T015, T026–T040, T052, T075, T080, T093E–T093H, T114, T128 y T147 |
| RNF-03 | T023, T024, T033, T034, T063, T124, T128B y T148A |
| RNF-04 | T014, T065–T069 y T072A |
| RNF-05 | T128B, T128C, T133, T133A y T134–T134C |
