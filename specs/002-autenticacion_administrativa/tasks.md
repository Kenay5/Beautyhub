# Tareas — 002 Autenticación y autorización administrativa

**Estado:** aprobadas explícitamente por el responsable del proyecto el 9 de septiembre de 2026; listas para ejecución conforme a la spec y al plan aprobados.  
**Fuentes:** `specs/002-autenticacion_administrativa/spec.md`, `specs/002-autenticacion_administrativa/plan.md` y las fronteras aprobadas de `specs/001-manita_gato/`.  
**Regla de ejecución:** avanzar en orden. Cada tarea representa aproximadamente 20–30 minutos; si durante la implementación excede ese tamaño, deberá dividirse sin ampliar el alcance. Las puertas de aprobación y publicación son comprobaciones, no estimaciones técnicas.  
**Alcance cruzado:** estas tareas implementan identidad y autorización; no repiten la lógica de citas asignada en `specs/001-manita_gato/tasks.md`.

## Orden coordinado con la spec 001

1. Completar primero `T001` a `T093H` de la spec 001 para disponer de la base común, las citas públicas y las notificaciones simuladas.
2. Completar `T001` a `T098` de esta spec 002 para disponer de identidad, sesiones, autorización, historial y límites verificables.
3. Regresar a `T094` a `T123A` de la spec 001 y conectar las operaciones administrativas con la autorización ya probada.
4. Completar `T124` a `T142` de la spec 001 y después `T099` a `T109` de esta spec para cerrar retención, restauración, proveedores y puertas de publicación.
5. Ejecutar `T143` a `T150` de la spec 001 y finalmente `T110` de esta spec como verificación integrada. Dentro de cada tramo se conserva el orden escrito y ninguna mención autoriza instalar dependencias, configurar secretos reales o publicar.

## 1. Puertas y base técnica

- [ ] **T001 — Obtener autorización para instalar dependencias**
  - **RF/criterios:** soporte de RF-03, RF-05 y RF-07; RF-05-CA-06 y RF-07-CA-01.
  - **Hecho cuando:** existe aprobación explícita para las cuatro dependencias nuevas y las ya aprobadas en el plan 001, sin instalar ninguna adicional.

- [ ] **T002 — Verificar dependencias y lista comprometida**
  - **RF/criterios:** RF-05-CA-06; RF-07-CA-01, CA-14 y CA-24.
  - **Hecho cuando:** versiones, compatibilidad, licencias, fuente oficial, 100,000 huellas, fecha, checksum y revisión máxima de 90 días quedan registrados.

- [ ] **T003 — Preparar fronteras y suites administrativas**
  - **RF/criterios:** soporte transversal de RF-01 a RF-12.
  - **Hecho cuando:** dominio, aplicación, web, infraestructura, React y las suites unitarias, PostgreSQL, contrato, seguridad, concurrencia y Playwright tienen límites explícitos.

- [ ] **T004 — Reutilizar reloj controlable y zona oficial**
  - **RF/criterios:** RF-01-CA-07; RF-02-CA-01; RF-03-CA-03; RF-04-CA-03 y CA-04; RF-06-CA-02; RF-07-CA-14; RF-08-CA-02; RF-11-CA-06 y CA-07.
  - **Hecho cuando:** dominio y pruebas controlan el instante y calculan todos los plazos con `America/Mexico_City`.

- [ ] **T005 — Configurar claves externas y separación criptográfica**
  - **RF/criterios:** RF-01-CA-13; RF-02-CA-07; RF-05-CA-04; RF-07-CA-13 y CA-24; RNF-01.
  - **Hecho cuando:** una clave raíz versionada se carga solo desde secretos externos, deriva subclaves por propósito y su ausencia impide arrancar de forma segura.

- [ ] **T006 — Centralizar errores y logs sanitizados**
  - **RF/criterios:** RF-03-CA-08; RF-11-CA-02; RF-12-CA-06 y CA-09; RNF-01.
  - **Hecho cuando:** errores y logs en inglés no contienen contraseñas, códigos, tokens, correos completos, datos de clientas ni detalles internos.

- [ ] **T007 — Preparar el simulador del proveedor de correo**
  - **RF/criterios:** RF-02-CA-09; RF-12-CA-07 a CA-10.
  - **Hecho cuando:** pruebas simulan aceptación, rechazo, incertidumbre y fallo tardío sin red, secretos ni datos personales reales.

- [ ] **T008 — Establecer verificaciones ejecutables de la spec 002**
  - **RF/criterios:** soporte transversal de RF-01 a RF-12 y RNF-01 a RNF-04.
  - **Hecho cuando:** cada grupo de pruebas tiene un comando documentado y ningún comando exige secretos incorporados al repositorio.

## 2. PostgreSQL e invariantes

- [ ] **T009 — Persistir cuentas y configuración inicial única**
  - **RF/criterios:** RF-01-CA-01, CA-03 a CA-05, CA-09, CA-11 y CA-12; RF-09-CA-01 a CA-06.
  - **Hecho cuando:** roles, estados y bootstrap irreversible permiten como máximo un propietario y una cuenta de personal pendiente o activa, sin credenciales predeterminadas.

- [ ] **T010 — Persistir reclamaciones y reservas de correo**
  - **RF/criterios:** RF-01-CA-02 y CA-14 a CA-16; RF-08-CA-02, CA-03, CA-07 y CA-08.
  - **Hecho cuando:** correo vigente y reservado usan huella única y valor cifrado, con máximo una reserva por cuenta.

- [ ] **T011 — Persistir enlaces y configuraciones pendientes**
  - **RF/criterios:** RF-01-CA-07 a CA-12; RF-02-CA-01 y CA-04; RF-06-CA-02, CA-04 y CA-10; RF-07-CA-07 a CA-10 y CA-23; RF-08-CA-02, CA-05 y CA-07.
  - **Hecho cuando:** propósito, huella, plazos, estado y configuración pendiente permiten un solo enlace vigente por cuenta y propósito.

- [ ] **T012 — Persistir TOTP, periodos y códigos de recuperación**
  - **RF/criterios:** RF-03-CA-12; RF-07-CA-01 a CA-05, CA-10 y CA-13 a CA-23.
  - **Hecho cuando:** existe máximo un factor activo, periodos y códigos se consumen una sola vez y ningún secreto queda recuperable salvo el TOTP cifrado autorizado.

- [ ] **T013 — Persistir sesiones administrativas**
  - **RF/criterios:** RF-03-CA-07; RF-04-CA-01 a CA-08.
  - **Hecho cuando:** cada sesión guarda solo huellas, cuenta, creación, actividad humana, expiración absoluta, CSRF e invalidación, con máximo una activa por cuenta.

- [ ] **T014 — Persistir fallos y bloqueos de cuenta**
  - **RF/criterios:** RF-03-CA-03 a CA-12; RF-06-CA-09, CA-12 y CA-13.
  - **Hecho cuando:** eventos mínimos, `lock_until` y restricción posterior a recuperación se actualizan bajo bloqueo de fila y sin guardar credenciales.

- [ ] **T015 — Persistir límites móviles y guardias concurrentes**
  - **RF/criterios:** RNF-01 y RNF-02; apoyo de RF-03, RF-06, RF-07 y RF-10.
  - **Hecho cuando:** categoría, sujeto con huella, solicitud e instante permiten serializar cada límite sin almacenar IP legible.

- [ ] **T016 — Persistir historial administrativo**
  - **RF/criterios:** RF-09-CA-02 y CA-03; RF-11-CA-01 a CA-08.
  - **Hecho cuando:** cada evento admite actor opcional, acción, resultado, instante y referencia interna mínima sin datos privados copiados.

- [ ] **T017 — Persistir entregas idempotentes de seguridad**
  - **RF/criterios:** RF-02-CA-09; RF-12-CA-01 a CA-10.
  - **Hecho cuando:** destinatario cifrado temporal, plantilla, clave idempotente, estado y error sanitizado se guardan sin secreto o enlace completo.

- [ ] **T018 — Aplicar restricciones y estados válidos**
  - **RF/criterios:** RF-01-CA-03 a CA-05 y CA-11; RF-03-CA-08; RF-11-CA-02 y CA-05; RNF-02 y RNF-03.
  - **Hecho cuando:** PostgreSQL rechaza duplicados, transiciones inválidas, relaciones rotas y campos prohibidos aun bajo concurrencia.

- [ ] **T019 — Verificar migraciones desde cero y desde la spec 001**
  - **RF/criterios:** soporte de RF-01 a RF-12; RNF-02.
  - **Hecho cuando:** migraciones suben y bajan en bases de prueba nuevas y existentes sin modificar datos ni reglas de citas.

- [ ] **T020 — Probar invariantes concurrentes en PostgreSQL**
  - **RF/criterios:** RF-01-CA-03, CA-04, CA-11, CA-15 y CA-16; RF-04-CA-02; RF-07-CA-15 y CA-20; RF-08-CA-08; RNF-02.
  - **Hecho cuando:** carreras reales permiten un solo propietario, personal, correo, activación, sesión o consumo incompatible.

## 3. Validación y primitivas de seguridad

- [ ] **T021 — Validar y normalizar correos administrativos**
  - **RF/criterios:** RF-01-CA-02.
  - **Hecho cuando:** pruebas cubren caracteres, segmentos, puntos, espacios, longitudes y comparación sin mayúsculas definidos en la spec.

- [ ] **T022 — Validar contraseñas y lista comprometida**
  - **RF/criterios:** RF-05-CA-01, CA-03, CA-06 y CA-07.
  - **Hecho cuando:** se aplican solo longitud, espacios y bloqueo local aprobados, y una lista ausente, corrupta o vencida falla de forma segura.

- [ ] **T023 — Crear y verificar huellas Argon2id**
  - **RF/criterios:** RF-03-CA-01 y CA-02; RF-05-CA-04; RF-06-CA-03.
  - **Hecho cuando:** salts distintos verifican, solo se persiste la huella, ninguna contraseña puede recuperarse o mostrarse, las huellas antiguas se fortalecen tras éxito y cuentas inexistentes ejecutan trabajo señuelo acotado.

- [ ] **T024 — Cifrar valores y crear huellas por propósito**
  - **RF/criterios:** RF-01-CA-13; RF-02-CA-07; RF-03-CA-08; RF-07-CA-13, CA-20 y CA-24; RF-12-CA-06.
  - **Hecho cuando:** TOTP y correo usan cifrado autenticado; enlaces, sesiones, recuperación, correo normalizado e IP usan huellas no reversibles separadas.

- [ ] **T025 — Generar y comprobar TOTP estándar**
  - **RF/criterios:** RF-03-CA-12; RF-07-CA-01, CA-14, CA-15 y CA-17.
  - **Hecho cuando:** seis dígitos cada 30 segundos aceptan solo periodos anterior, actual y siguiente, un periodo consumido no repite éxito y ningún TOTP se envía por correo, SMS o WhatsApp.

- [ ] **T026 — Generar y comprobar códigos de recuperación**
  - **RF/criterios:** RF-03-CA-12; RF-07-CA-02, CA-03, CA-16 y CA-20.
  - **Hecho cuando:** se crean diez códigos únicos de 16 caracteres, se normalizan exactamente como la spec y solo se consumen tras éxito completo.

- [ ] **T027 — Implementar el ciclo común de enlaces temporales**
  - **RF/criterios:** RF-01-CA-07, CA-09 a CA-12; RF-02-CA-01, CA-04 y CA-06; RF-06-CA-02, CA-04 y CA-10; RF-07-CA-07, CA-08 y CA-23; RF-08-CA-02, CA-05 y CA-07.
  - **Hecho cuando:** emisión, sustitución, vencimiento exacto y consumo atómico respetan propósito y plazo sin dejar estado parcial.

- [ ] **T028 — Proteger tokens, QR y navegación del navegador**
  - **RF/criterios:** RF-02-CA-05; RF-07-CA-24; RF-12-CA-06; RNF-01.
  - **Hecho cuando:** tokens opacos de 256 bits viajan en fragmento y cuerpo, el QR se genera localmente y deja de consultarse al salir del flujo, y URL, `Referer`, historial y almacenamiento web quedan limpios.

- [ ] **T029 — Invalidar estados pendientes de forma coherente**
  - **RF/criterios:** RF-01-CA-10; RF-04-CA-08; RF-07-CA-08 y CA-23; RF-08-CA-05 y CA-07.
  - **Hecho cuando:** abandono, vencimiento, sustitución o invalidación descartan solo lo pendiente y conservan cuenta, correo, factor y credenciales vigentes.

- [ ] **T030 — Ejecutar pruebas unitarias de las primitivas**
  - **RF/criterios:** RF-01-CA-02, CA-07 y CA-13; RF-03-CA-02 y CA-12; RF-05; RF-07-CA-13 a CA-17, CA-20 y CA-24; RNF-01.
  - **Hecho cuando:** reloj, aleatoriedad, normalización, Argon2id, lista, cifrado, huellas, TOTP, códigos y enlaces pasan con bordes controlados.

## 4. Propietario e invitación del personal

- [ ] **T031 — Registrar el correo del propietario por proceso protegido**
  - **RF/criterios:** RF-01-CA-01 a CA-03 y CA-13 a CA-16.
  - **Hecho cuando:** el comando autorizado solicita el correo sin argumento de shell y crea atómicamente una sola cuenta propietaria inactiva.

- [ ] **T032 — Emitir y reemitir el enlace inicial**
  - **RF/criterios:** RF-01-CA-07 y CA-09; RF-12-CA-07 a CA-09.
  - **Hecho cuando:** existe como máximo un enlace opaco de 30 minutos y un fallo conserva la cuenta inactiva y permite otro enlace distinto.

- [ ] **T033 — Preparar la activación inicial sin consumir el enlace**
  - **RF/criterios:** RF-01-CA-08 y CA-10; RF-05; RF-07-CA-01, CA-02 y CA-24.
  - **Hecho cuando:** solo un enlace vigente permite preparar contraseña y TOTP sin activar la cuenta ni conservar secretos al abandonar.

- [ ] **T034 — Activar al propietario de forma atómica**
  - **RF/criterios:** RF-01-CA-08, CA-10 a CA-12; RF-07-CA-02, CA-16 y CA-23; RNF-02.
  - **Hecho cuando:** contraseña, factor, diez códigos, enlace consumido y bootstrap cerrado se confirman juntos, sin sesión y con un solo ganador concurrente.

- [ ] **T035 — Autorizar y crear una invitación de personal**
  - **RF/criterios:** RF-01-CA-04, CA-06, CA-14 a CA-16; RF-02-CA-01, CA-03 y CA-07; RF-10-CA-01 y CA-04.
  - **Hecho cuando:** solo el propietario reclama un correo disponible y deja exactamente una cuenta pendiente sin acceso.

- [ ] **T036 — Conservar la invitación pendiente ante fallo de entrega**
  - **RF/criterios:** RF-02-CA-03 y CA-09; RF-12-CA-07 a CA-09.
  - **Hecho cuando:** el enlace fallido no funciona, la cuenta sigue pendiente y el propietario puede reenviar o cancelar tras un error sanitizado.

- [ ] **T037 — Reenviar o cancelar una invitación pendiente**
  - **RF/criterios:** RF-01-CA-05; RF-02-CA-04, CA-06, CA-08 y CA-09.
  - **Hecho cuando:** reenviar sustituye el enlace por otro de 24 horas y cancelar invalida enlace, cuenta pendiente y reclamación.

- [ ] **T038 — Activar al personal con credenciales propias**
  - **RF/criterios:** RF-01-CA-15; RF-02-CA-02 a CA-04 y CA-07; RF-07-CA-01, CA-02 y CA-16.
  - **Hecho cuando:** el titular confirma contraseña, TOTP y diez códigos sin que el propietario conozca secretos y sin crear una sesión.

- [ ] **T039 — Uniformar invitaciones inválidas o vencidas**
  - **RF/criterios:** RF-02-CA-04 y CA-05.
  - **Hecho cuando:** enlace inválido, usado, cancelado, sustituido o vencido muestra el mismo mensaje y no revela estado interno.

- [ ] **T040 — Probar altas e invitaciones concurrentes**
  - **RF/criterios:** RF-01-CA-03, CA-04, CA-11, CA-15 y CA-16; RF-02-CA-03 y CA-04; RNF-02.
  - **Hecho cuando:** PostgreSQL permite una sola combinación válida ante dobles altas, invitaciones, correos o activaciones.

- [ ] **T041 — Verificar la activación del propietario con Playwright**
  - **RF/criterios:** RF-01-CA-01, CA-07 a CA-13; RF-05; RF-07-CA-01, CA-02, CA-16 y CA-24.
  - **Hecho cuando:** datos ficticios recorren registro protegido, activación, códigos de una sola vista y cierre irreversible con mensajes en español.

- [ ] **T042 — Verificar la invitación del personal con Playwright**
  - **RF/criterios:** RF-02-CA-01 a CA-09; RF-07-CA-01, CA-02, CA-16 y CA-24.
  - **Hecho cuando:** propietario invita y el personal activa; reenvío, cancelación, vencimiento y fallo de entrega producen los resultados aprobados.

## 5. Login y sesiones

- [ ] **T043 — Validar login y uniformar errores**
  - **RF/criterios:** RF-03-CA-01, CA-02 y CA-12.
  - **Hecho cuando:** se exige correo, contraseña y exactamente un segundo factor, y toda cuenta o credencial inválida recibe un resultado indistinguible.

- [ ] **T044 — Consumir el segundo factor solo al completar el login**
  - **RF/criterios:** RF-03-CA-08 y CA-12; RF-07-CA-03, CA-15 y CA-20.
  - **Hecho cuando:** una solicitud rechazada cuenta una sola falla y conserva el factor; el éxito consume una sola vez y no registra secretos.

- [ ] **T045 — Contar fallos y bloquear en el quinto**
  - **RF/criterios:** RF-03-CA-03 y CA-08; RF-12-CA-02 y CA-03.
  - **Hecho cuando:** el quinto fallo dentro de 15 minutos fija exactamente 15 minutos de bloqueo, audita y prepara los avisos exigidos.

- [ ] **T046 — Mantener y vencer el bloqueo correctamente**
  - **RF/criterios:** RF-03-CA-04 a CA-06 y CA-10.
  - **Hecho cuando:** durante el bloqueo se niegan login y operaciones sensibles sin verificar credenciales ni mover el plazo, una sesión abierta conserva operaciones ordinarias autorizadas y al vencer comienza una ventana nueva.

- [ ] **T047 — Crear login correcto y sustituir la sesión previa**
  - **RF/criterios:** RF-03-CA-07 y CA-09; RF-04-CA-02; RNF-02.
  - **Hecho cuando:** se limpian fallos, se crea sesión del rol real y dos logins concurrentes dejan exactamente una sesión activa.

- [ ] **T048 — Emitir cookie y token CSRF protegidos**
  - **RF/criterios:** RF-04-CA-01; RNF-01.
  - **Hecho cuando:** cookie `__Host-` aplica `Secure`, `HttpOnly`, `SameSite=Strict`, ruta `/` y sin `Domain`, y CSRF distinto se guarda como huella.

- [ ] **T049 — Validar CSRF y origen en mutaciones**
  - **RF/criterios:** RF-04-CA-07; RF-10-CA-05; RNF-01.
  - **Hecho cuando:** CSRF ausente o distinto y origen no permitido reciben 403 antes de cualquier efecto.

- [ ] **T050 — Aplicar expiración por inactividad y máxima**
  - **RF/criterios:** RF-04-CA-03 y CA-04.
  - **Hecho cuando:** actividad humana prolonga solo la ventana de 30 minutos y ninguna actividad supera las ocho horas absolutas.

- [ ] **T051 — Cerrar sesión de forma idempotente**
  - **RF/criterios:** RF-04-CA-05; RF-11-CA-01.
  - **Hecho cuando:** sesión y cookie quedan invalidadas, repetir no revive estado y el cierre se registra sin secretos.

- [ ] **T052 — Invalidar sesiones y temporales al cambiar seguridad**
  - **RF/criterios:** RF-04-CA-06 y CA-08.
  - **Hecho cuando:** cambiar contraseña, correo, TOTP o códigos cierra sesiones e invalida enlaces y configuraciones incompatibles.

- [ ] **T053 — Revalidar sesión y cuenta en cada solicitud**
  - **RF/criterios:** RF-04-CA-07; RF-09-CA-01.
  - **Hecho cuando:** sesión inexistente, vencida o invalidada y cuenta no activa no producen contexto administrativo ni filtran su estado.

- [ ] **T054 — Aplicar cabeceras y estado seguro en React**
  - **RF/criterios:** RF-03-CA-08; RF-04-CA-03 a CA-07; RF-12-CA-06; RNF-01.
  - **Hecho cuando:** respuestas usan las cabeceras aprobadas y React reacciona en español sin almacenar credenciales ni decidir autorización.

- [ ] **T055 — Probar login, bloqueo, sesiones y CSRF**
  - **RF/criterios:** RF-03-CA-01 a CA-12; RF-04-CA-01 a CA-08; RF-10-CA-05; RNF-01 y RNF-02.
  - **Hecho cuando:** pruebas unitarias, PostgreSQL, contrato y seguridad cubren errores genéricos, tiempos exactos, sustitución, cookie, CSRF e invalidación.

- [ ] **T056 — Verificar login y sesión con Playwright**
  - **RF/criterios:** RF-03 y RF-04.
  - **Hecho cuando:** navegador recorre éxito, quinto fallo, bloqueo, actividad, ambos vencimientos, nueva sesión y cierre con mensajes en español.

## 6. Contraseña, factores y correo propio

- [ ] **T057 — Cambiar la contraseña desde una sesión**
  - **RF/criterios:** RF-03-CA-03, CA-08 y CA-12; RF-05-CA-02, CA-05, CA-07 y CA-08.
  - **Hecho cuando:** contraseña actual, TOTP y nueva válida cambian atómicamente, cierran sesiones, invalidan temporales, auditan y avisan; formularios aceptan pegado/autocompletado y cualquier fallo conserva credenciales.

- [ ] **T058 — Solicitar recuperación con respuesta genérica**
  - **RF/criterios:** RF-06-CA-01.
  - **Hecho cuando:** cualquier correo válido recibe el mismo 202 y solo una cuenta activa puede originar una intención interna.

- [ ] **T059 — Emitir y entregar el enlace de recuperación**
  - **RF/criterios:** RF-06-CA-02 y CA-04; RF-12-CA-07 a CA-09.
  - **Hecho cuando:** existe máximo un enlace vigente de 30 minutos y un fallo lo invalida sin revelar la cuenta.

- [ ] **T060 — Completar recuperación sin iniciar sesión**
  - **RF/criterios:** RF-06-CA-03 a CA-05.
  - **Hecho cuando:** contraseña válida sustituye la anterior, consume el enlace, cierra sesiones, audita y confirma sin crear sesión.

- [ ] **T061 — Conservar bloqueo y permitir recuperación**
  - **RF/criterios:** RF-03-CA-11; RF-06-CA-08 y CA-09.
  - **Hecho cuando:** solicitar y terminar recuperación no elimina fallos ni modifica `lock_until`.

- [ ] **T062 — Forzar recuperación del personal como propietario**
  - **RF/criterios:** RF-06-CA-06 y CA-07; RF-10-CA-01 y CA-04.
  - **Hecho cuando:** solo el propietario cierra sesiones y envía el enlace sin elegir, ver o recuperar la contraseña del personal.

- [ ] **T063 — Resolver fallo, vencimiento o repetición de recuperación forzada**
  - **RF/criterios:** RF-06-CA-10 y CA-11; RF-12-CA-10.
  - **Hecho cuando:** la contraseña previa permanece inutilizable y cada fallo, vencimiento u orden nueva invalida el enlace anterior; el propietario puede emitir otro distinto con 30 minutos completos.

- [ ] **T064 — Aplicar la restricción posterior a recuperación**
  - **RF/criterios:** RF-06-CA-12 y CA-13; RF-07-CA-19.
  - **Hecho cuando:** se niega reemplazo perdido tras recuperar y solo un login completo con el factor anterior retira la restricción.

- [ ] **T065 — Usar y mostrar códigos de recuperación**
  - **RF/criterios:** RF-03-CA-12; RF-07-CA-02, CA-03, CA-16 y CA-20.
  - **Hecho cuando:** el lote se muestra una vez, un código correcto se consume al final y uno incorrecto conserva todos y cuenta una falla.

- [ ] **T066 — Regenerar códigos desde una sesión**
  - **RF/criterios:** RF-07-CA-04, CA-21 y CA-22; RF-04-CA-06 y CA-08.
  - **Hecho cuando:** contraseña y TOTP sustituyen el lote completo, cierran sesiones y avisan; cualquier fallo cuenta una sola vez y conserva el lote anterior.

- [ ] **T067 — Iniciar reemplazo de TOTP desde sesión**
  - **RF/criterios:** RF-07-CA-05 y CA-23.
  - **Hecho cuando:** contraseña y TOTP o recuperación válidos preparan el factor nuevo sin cambiar el anterior, sus códigos o sesiones ni consumir la credencial comprobada.

- [ ] **T068 — Confirmar reemplazo de TOTP desde sesión**
  - **RF/criterios:** RF-07-CA-10, CA-11 y CA-15; RF-04-CA-06 y CA-08.
  - **Hecho cuando:** factor y lote nuevos sustituyen los anteriores, la credencial previa se consume condicionalmente y sesiones se cierran en un resultado atómico.

- [ ] **T069 — Solicitar reemplazo de factor perdido**
  - **RF/criterios:** RF-07-CA-06, CA-07 y CA-18.
  - **Hecho cuando:** la respuesta es siempre genérica y solo correo, contraseña, cuenta activa no bloqueada y sin restricción originan como máximo un enlace vigente de 30 minutos.

- [ ] **T070 — Completar reemplazo perdido de forma segura**
  - **RF/criterios:** RF-07-CA-08 a CA-11 y CA-23.
  - **Hecho cuando:** el factor anterior permanece activo hasta la confirmación atómica del nuevo y el flujo no concede sesión.

- [ ] **T071 — Impedir toda omisión del segundo factor**
  - **RF/criterios:** RF-07-CA-12 y CA-19; RF-06-CA-12.
  - **Hecho cuando:** sin contraseña, TOTP y códigos no existe recuperación automática ni administrativa, y una respuesta pública no revela el motivo.

- [ ] **T072 — Solicitar cambio del correo propio**
  - **RF/criterios:** RF-01-CA-02; RF-08-CA-01, CA-02 y CA-06.
  - **Hecho cuando:** contraseña y TOTP permiten reservar un correo normalizado disponible sin cambiar el correo vigente ni otra cuenta.

- [ ] **T073 — Emitir y sustituir confirmaciones de correo**
  - **RF/criterios:** RF-01-CA-14 a CA-16; RF-08-CA-02 y CA-07.
  - **Hecho cuando:** existe una reserva y un enlace de 30 minutos; otra solicitud invalida y libera los anteriores antes de reservar.

- [ ] **T074 — Resolver vencimiento o fallo del cambio de correo**
  - **RF/criterios:** RF-08-CA-05 y CA-07; RF-12-CA-07 a CA-09.
  - **Hecho cuando:** correo anterior permanece vigente, reserva se libera y enlace inválido, vencido o no entregado no cambia la cuenta.

- [ ] **T075 — Confirmar el cambio de correo y avisar**
  - **RF/criterios:** RF-01-CA-15; RF-08-CA-03 y CA-04; RF-12-CA-01.
  - **Hecho cuando:** se revalida unicidad, cambia el correo, cierra sesiones y avisa exactamente una vez al anterior y una al nuevo.

- [ ] **T076 — Probar reclamaciones concurrentes de correo**
  - **RF/criterios:** RF-01-CA-16; RF-08-CA-08; RNF-02.
  - **Hecho cuando:** PostgreSQL permite un solo ganador cuando invitaciones, activaciones o cambios reclaman simultáneamente el mismo correo.

- [ ] **T077 — Verificar contraseña y recuperación con Playwright**
  - **RF/criterios:** RF-05; RF-06.
  - **Hecho cuando:** navegador recorre cambio propio, solicitud genérica, recuperación, orden forzada, fallos y restricción posterior con datos ficticios.

- [ ] **T078 — Verificar TOTP y códigos con Playwright**
  - **RF/criterios:** RF-07-CA-01 a CA-24.
  - **Hecho cuando:** configuración, uso, regeneración, ambos reemplazos, abandono, QR y pérdida total muestran el comportamiento aprobado.

- [ ] **T079 — Verificar cambio de correo con contrato y Playwright**
  - **RF/criterios:** RF-08-CA-01 a CA-08; RF-12-CA-01 y CA-07 a CA-09.
  - **Hecho cuando:** éxito, sustitución, vencimiento, fallo, intento ajeno y carrera tienen respuestas sanitizadas y contenido español.

## 7. Personal, autorización e historial

- [ ] **T080 — Desactivar y reemplazar al personal**
  - **RF/criterios:** RF-01-CA-05; RF-09-CA-01, CA-05 y CA-06; RF-10-CA-01 y CA-04.
  - **Hecho cuando:** solo el propietario desactiva cuenta, sesiones, enlaces, TOTP y códigos atómicamente, y una autorización futura exige cuenta nueva.

- [ ] **T081 — Conservar y retirar datos del personal desactivado**
  - **RF/criterios:** RF-09-CA-02 y CA-03; RF-11-CA-06 y CA-07.
  - **Hecho cuando:** historial conserva referencia interna y al aniversario de 12 meses del último evento se retiran los datos identificables previstos.

- [ ] **T082 — Construir contexto y política de autorización**
  - **RF/criterios:** RF-01-CA-06; RF-04-CA-07; RF-09-CA-04; RF-10-CA-01 a CA-05.
  - **Hecho cuando:** backend decide con cuenta, rol y sesión; propietario y personal pueden reintentar notificaciones fallidas de citas solo a contactos registrados y sin ver el código, el personal conserva únicamente su alcance operativo y nadie administra otra cuenta sin permiso.

- [ ] **T083 — Denegar sin efectos parciales ni confianza en React**
  - **RF/criterios:** RF-10-CA-05; RF-11-CA-08.
  - **Hecho cuando:** solicitud manual o interfaz alterada recibe 401/403, no cambia negocio y registra la denegación mínima si existe actor.

- [ ] **T084 — Registrar eventos administrativos exigidos**
  - **RF/criterios:** RF-03-CA-08; RF-11-CA-01, CA-08 y CA-09.
  - **Hecho cuando:** identidad, seguridad, mutaciones de la spec 001 y denegaciones generan eventos; consultas ordinarias no los generan.

- [ ] **T085 — Minimizar e impedir modificaciones del historial**
  - **RF/criterios:** RF-11-CA-02 y CA-05.
  - **Hecho cuando:** no hay secretos, IP ni datos de clientas, y permisos ordinarios no pueden actualizar o borrar fuera de retención.

- [ ] **T086 — Consultar historial solo como propietario**
  - **RF/criterios:** RF-11-CA-03 y CA-04; RF-10-CA-04.
  - **Hecho cuando:** propietario filtra por cuenta, tipo y periodo en la zona oficial, mientras personal no puede listar ni consultar eventos.

- [ ] **T087 — Aplicar conservación exacta de 12 meses**
  - **RF/criterios:** RF-09-CA-03; RF-11-CA-06 y CA-07.
  - **Hecho cuando:** el proceso idempotente conserva hasta el aniversario calendario exacto y retira después eventos y datos identificables vencidos.

- [ ] **T088 — Conservar referencias mínimas tras eliminar una cita**
  - **RF/criterios:** RF-11-CA-02 y CA-08.
  - **Hecho cuando:** eliminar la cita no rompe el evento y este no retiene nombre, contacto, código privado u otro dato personal.

- [ ] **T089 — Probar la matriz de autorización por contrato**
  - **RF/criterios:** RF-09-CA-04; RF-10-CA-01 a CA-05; RF-11-CA-04 y CA-08.
  - **Hecho cuando:** cada capacidad se prueba con propietario, personal y persona no autenticada, incluido el reintento restringido de notificaciones de citas y la ausencia de efectos parciales.

- [ ] **T090 — Verificar personal, permisos e historial con Playwright**
  - **RF/criterios:** RF-09; RF-10; RF-11.
  - **Hecho cuando:** navegador recorre desactivación, reemplazo, menús por rol, reintento permitido de una notificación fallida de cita, denegaciones y consulta del historial con contenido español y sin mostrar el código privado.

## 8. Límites, avisos y restauración

- [ ] **T091 — Limitar solicitudes públicas por origen**
  - **RF/criterios:** RNF-01 a RNF-03; apoyo de RF-01, RF-03, RF-06 y RF-07.
  - **Hecho cuando:** el proxy confiable produce una huella de IP y recuperación, reemplazo, login y disponibilidad comparten 20 solicitudes por 15 minutos.

- [ ] **T092 — Limitar solicitudes administrativas por cuenta**
  - **RF/criterios:** RNF-01 y RNF-02; apoyo de RF-10.
  - **Hecho cuando:** se permiten 120 solicitudes por minuto y un 429 no cierra, prolonga ni modifica la sesión.

- [ ] **T093 — Limitar envíos manuales de seguridad**
  - **RF/criterios:** RNF-01 y RNF-02; apoyo de RF-02, RF-06 a RF-08 y RF-12.
  - **Hecho cuando:** todos los mensajes manuales de seguridad comparten 10 intentos por cuenta en 15 minutos.

- [ ] **T094 — Limitar notificaciones manuales de citas**
  - **RF/criterios:** RNF-01 y RNF-02; integración con RF-10-CA-01 y CA-02 y la spec 001.
  - **Hecho cuando:** existen 30 acciones por cuenta en 15 minutos, cada reintento manual de una notificación fallida cuenta una vez y correo más WhatsApp de una misma acción cuentan una sola vez.

- [ ] **T095 — Resolver límites superpuestos bajo concurrencia**
  - **RF/criterios:** RF-03-CA-03 a CA-05; RNF-01 y RNF-02.
  - **Hecho cuando:** solo continúa quien tiene capacidad en todos los límites, avisos automáticos de seguridad y recordatorios automáticos de citas están exentos, sus reintentos manuales no lo están y 429 no altera fallos ni bloqueos.

- [ ] **T096 — Crear avisos con destinatarios exactos**
  - **RF/criterios:** RF-12-CA-01 a CA-06.
  - **Hecho cuando:** titular, propietario y ambos correos reciben únicamente sus avisos sin secretos; una acción confirmada, bloqueo o desactivación no se revierte si el aviso falla.

- [ ] **T097 — Resolver entregas de enlaces y reintentos**
  - **RF/criterios:** RF-02-CA-09; RF-12-CA-07 a CA-10.
  - **Hecho cuando:** aceptación, rechazo, incertidumbre, fallo tardío y reintento distinto terminan en un enlace y estado seguro coherentes; la respuesta pública sigue genérica, la identificada informa sin detalles y una recuperación forzada conserva la contraseña anterior inutilizable.

- [ ] **T098 — Probar avisos y límites con PostgreSQL y concurrencia**
  - **RF/criterios:** RF-12; RNF-01 y RNF-02.
  - **Hecho cuando:** bordes temporales, ráfagas, doble canal, idempotencia y resultados del proveedor no superan límites ni duplican entregas.

- [ ] **T099 — Invalidar artefactos después de restaurar un respaldo**
  - **RF/criterios:** RF-01-CA-10; RF-04-CA-07 y CA-08; RF-07-CA-08 y CA-23; RF-08-CA-05 y CA-07; RNF-01 y RNF-02.
  - **Hecho cuando:** antes del tráfico se invalidan sesiones, enlaces, configuraciones y reservas restauradas; una contraseña ordinaria conserva su estado y una ya inutilizada por recuperación forzada no revive.

- [ ] **T100 — Ejecutar retenciones al restaurar**
  - **RF/criterios:** RF-09-CA-03; RF-11-CA-06 y CA-07; integración con RF-13 de la spec 001.
  - **Hecho cuando:** historial, datos identificables del personal y citas vencidas se depuran antes de permitir acceso al estado restaurado.

- [ ] **T101 — Proteger respaldo y rotación de claves**
  - **RF/criterios:** RF-01-CA-13; RF-07-CA-13 y CA-24; RNF-01.
  - **Hecho cuando:** una copia externa autorizada restaura y rota valores cifrados ficticios sin revelar claves ni perder datos.

- [ ] **T102 — Ensayar restauración conjunta de ambas specs**
  - **RF/criterios:** soporte transversal de RF-01 a RF-12; RNF-01 y RNF-02.
  - **Hecho cuando:** migraciones, clave, invalidación y retenciones se verifican aisladamente y un fallo mantiene el servicio fuera de tráfico.

## 9. Contratos, publicación y cierre

- [ ] **T103 — Verificar contratos web públicos y autenticados**
  - **RF/criterios:** RF-01 a RF-10; RF-12-CA-06 a CA-10.
  - **Hecho cuando:** entradas, salidas y 400/401/403/409/422/429 usan JSON técnico en inglés, contenido español y no revelan existencia, trazas o secretos.

- [ ] **T104 — Verificar interfaz y almacenamiento del navegador**
  - **RF/criterios:** RF-01 a RF-12; RF-03-CA-08; RF-07-CA-24; RF-12-CA-06.
  - **Hecho cuando:** recorridos administrativos son comprensibles en español y URL, historial, logs y almacenamiento web no contienen secretos.

- [ ] **T105 — Verificar el contrato operativo de Resend**
  - **RF/criterios:** RF-02-CA-09; RF-12-CA-07 a CA-10; RNF-01 y RNF-04.
  - **Hecho cuando:** idempotencia, webhooks, estados, reintentos y conservación compatible están comprobados antes del adaptador real.

- [ ] **T106 — Conectar y probar el proveedor real de forma controlada**
  - **RF/criterios:** RF-02; RF-06; RF-07; RF-08; RF-09; RF-12; RNF-01.
  - **Hecho cuando:** configuración externa selecciona el proveedor, dominio no importa su SDK y éxito/fallo usan identidades de prueba autorizadas sin filtrar secretos.

- [ ] **T107 — Revisar lista comprometida y capacidad Argon2id**
  - **RF/criterios:** RF-03-CA-02; RF-05-CA-04 y CA-06; RNF-01 y RNF-04.
  - **Hecho cuando:** actualización local es repetible y parámetros medidos resisten la concurrencia prevista sin debilitar seguridad ni exceder presupuesto.

- [ ] **T108 — Verificar costo, secretos y dependencias del despliegue**
  - **RF/criterios:** RF-01 a RF-12; RNF-01, RNF-03 y RNF-04.
  - **Hecho cuando:** objetivo de 100 MXN y alerta de 85 MXN permanecen, licencias/versiones están fijadas y el escaneo no encuentra secretos ni acceso privado público.

- [ ] **T109 — Cerrar la puerta jurídica antes de publicar**
  - **RF/criterios:** RNF-01 y RNF-04; dependencia de publicación de la spec 001.
  - **Hecho cuando:** el responsable registra la validación jurídica del aviso de privacidad aplicable a la web terminada.

- [ ] **T110 — Ejecutar verificación final y obtener aprobación**
  - **RF/criterios:** RF-01 a RF-12 y sus 128 criterios; RNF-01 a RNF-04.
  - **Hecho cuando:** unitarias, PostgreSQL, migraciones, contrato, seguridad, concurrencia y Playwright pasan; la matriz tiene 128 evidencias y el responsable autoriza por separado implementación, secretos reales y publicación.

## 10. Matriz primaria de los 128 criterios EARS

Cada criterio aparece exactamente una vez en esta matriz. Las menciones adicionales dentro de las tareas representan integración o pruebas complementarias, no requisitos nuevos ni responsabilidades duplicadas.

| Criterio EARS | Tarea primaria |
|---|---|
| RF-01-CA-01 | T031 |
| RF-01-CA-02 | T021 |
| RF-01-CA-03 | T009 |
| RF-01-CA-04 | T035 |
| RF-01-CA-05 | T080 |
| RF-01-CA-06 | T082 |
| RF-01-CA-07 | T032 |
| RF-01-CA-08 | T033 |
| RF-01-CA-09 | T032 |
| RF-01-CA-10 | T029 |
| RF-01-CA-11 | T034 |
| RF-01-CA-12 | T034 |
| RF-01-CA-13 | T005 |
| RF-01-CA-14 | T010 |
| RF-01-CA-15 | T075 |
| RF-01-CA-16 | T076 |
| RF-02-CA-01 | T035 |
| RF-02-CA-02 | T038 |
| RF-02-CA-03 | T036 |
| RF-02-CA-04 | T037 |
| RF-02-CA-05 | T039 |
| RF-02-CA-06 | T037 |
| RF-02-CA-07 | T035 |
| RF-02-CA-08 | T037 |
| RF-02-CA-09 | T036 |
| RF-03-CA-01 | T043 |
| RF-03-CA-02 | T043 |
| RF-03-CA-03 | T045 |
| RF-03-CA-04 | T046 |
| RF-03-CA-05 | T046 |
| RF-03-CA-06 | T046 |
| RF-03-CA-07 | T047 |
| RF-03-CA-08 | T044 |
| RF-03-CA-09 | T047 |
| RF-03-CA-10 | T046 |
| RF-03-CA-11 | T061 |
| RF-03-CA-12 | T044 |
| RF-04-CA-01 | T048 |
| RF-04-CA-02 | T047 |
| RF-04-CA-03 | T050 |
| RF-04-CA-04 | T050 |
| RF-04-CA-05 | T051 |
| RF-04-CA-06 | T052 |
| RF-04-CA-07 | T053 |
| RF-04-CA-08 | T052 |
| RF-05-CA-01 | T022 |
| RF-05-CA-02 | T057 |
| RF-05-CA-03 | T022 |
| RF-05-CA-04 | T023 |
| RF-05-CA-05 | T057 |
| RF-05-CA-06 | T022 |
| RF-05-CA-07 | T057 |
| RF-05-CA-08 | T057 |
| RF-06-CA-01 | T058 |
| RF-06-CA-02 | T059 |
| RF-06-CA-03 | T060 |
| RF-06-CA-04 | T027 |
| RF-06-CA-05 | T060 |
| RF-06-CA-06 | T062 |
| RF-06-CA-07 | T062 |
| RF-06-CA-08 | T061 |
| RF-06-CA-09 | T061 |
| RF-06-CA-10 | T063 |
| RF-06-CA-11 | T063 |
| RF-06-CA-12 | T064 |
| RF-06-CA-13 | T064 |
| RF-07-CA-01 | T025 |
| RF-07-CA-02 | T026 |
| RF-07-CA-03 | T065 |
| RF-07-CA-04 | T066 |
| RF-07-CA-05 | T067 |
| RF-07-CA-06 | T069 |
| RF-07-CA-07 | T069 |
| RF-07-CA-08 | T070 |
| RF-07-CA-09 | T070 |
| RF-07-CA-10 | T068 |
| RF-07-CA-11 | T068 |
| RF-07-CA-12 | T071 |
| RF-07-CA-13 | T024 |
| RF-07-CA-14 | T025 |
| RF-07-CA-15 | T025 |
| RF-07-CA-16 | T026 |
| RF-07-CA-17 | T025 |
| RF-07-CA-18 | T069 |
| RF-07-CA-19 | T071 |
| RF-07-CA-20 | T065 |
| RF-07-CA-21 | T066 |
| RF-07-CA-22 | T066 |
| RF-07-CA-23 | T067 |
| RF-07-CA-24 | T028 |
| RF-08-CA-01 | T072 |
| RF-08-CA-02 | T073 |
| RF-08-CA-03 | T075 |
| RF-08-CA-04 | T075 |
| RF-08-CA-05 | T074 |
| RF-08-CA-06 | T072 |
| RF-08-CA-07 | T074 |
| RF-08-CA-08 | T076 |
| RF-09-CA-01 | T080 |
| RF-09-CA-02 | T081 |
| RF-09-CA-03 | T081 |
| RF-09-CA-04 | T082 |
| RF-09-CA-05 | T080 |
| RF-09-CA-06 | T080 |
| RF-10-CA-01 | T082 |
| RF-10-CA-02 | T082 |
| RF-10-CA-03 | T082 |
| RF-10-CA-04 | T082 |
| RF-10-CA-05 | T083 |
| RF-11-CA-01 | T084 |
| RF-11-CA-02 | T085 |
| RF-11-CA-03 | T086 |
| RF-11-CA-04 | T086 |
| RF-11-CA-05 | T085 |
| RF-11-CA-06 | T087 |
| RF-11-CA-07 | T087 |
| RF-11-CA-08 | T088 |
| RF-11-CA-09 | T084 |
| RF-12-CA-01 | T096 |
| RF-12-CA-02 | T096 |
| RF-12-CA-03 | T096 |
| RF-12-CA-04 | T096 |
| RF-12-CA-05 | T096 |
| RF-12-CA-06 | T096 |
| RF-12-CA-07 | T097 |
| RF-12-CA-08 | T097 |
| RF-12-CA-09 | T097 |
| RF-12-CA-10 | T097 |

## 11. Puertas de ejecución

1. El plan y este archivo de tareas 002 fueron aprobados explícitamente el 9 de septiembre de 2026; comenzar la implementación conserva la puerta separada indicada abajo.
2. T001 debe cerrarse antes de instalar dependencias; aprobar estas tareas no concede esa autorización.
3. T002 precede al uso de la lista comprometida y ninguna contraseña legible se incorporará al proyecto.
4. T005 y T101 preceden al uso de datos persistentes reales; ningún secreto se escribe en repositorio, documentación o pruebas.
5. T105 debe cerrar compatibilidad del proveedor antes de T106.
6. T108, T109 y T110 deben completarse antes de solicitar publicación.
7. Implementación, configuración de secretos reales y publicación requieren aprobaciones separadas.
