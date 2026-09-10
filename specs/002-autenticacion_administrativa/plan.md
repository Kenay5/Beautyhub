# Plan de implementación — 002 Autenticación y autorización administrativa

**Estado:** aprobado explícitamente por el responsable del proyecto el 9 de septiembre de 2026.  
**Spec cubierta:** `specs/002-autenticacion_administrativa/spec.md`, activa y aprobada.  
**Dependencia funcional:** `specs/001-manita_gato/spec.md`, sin redefinir sus reglas de citas.  
**Dependencia técnica:** `specs/001-manita_gato/plan.md`, cuyo stack, despliegue y límites de costo se reutilizan cuando son compatibles.

## 1. Propósito, alcance y límites

Este plan describe cómo implementar las dos cuentas administrativas, su autenticación, segundo factor, sesiones, recuperación, autorización, avisos de seguridad e historial. Explica el mecanismo técnico sin ampliar ni reducir el comportamiento aprobado.

Incluye:

- una única cuenta de propietario y, como máximo, una cuenta de personal pendiente o activa;
- configuración inicial protegida, invitaciones, contraseñas, TOTP y códigos de recuperación;
- sesiones revocables, autorización por rol y protección contra abuso;
- cambios de correo, recuperación, historial y avisos de seguridad;
- integración de la identidad administrativa con las operaciones de la spec 001.

No incluye:

- cuentas o autenticación de clientas;
- permisos personalizados, inicio social, passkeys o dispositivos confiables;
- cambios a disponibilidad, citas, servicios, precios, notificaciones o retención definidos por la spec 001;
- la revisión jurídica pendiente que bloquea la publicación de la spec 001;
- instalación de dependencias, implementación o generación de `tasks.md`.

**Cobertura:** RF-01 a RF-12 y sus 128 criterios EARS, de forma transversal.

En todo el documento, una cobertura escrita como `RF-xx` comprende todos los criterios `RF-xx-CA-yy` de ese requisito; cuando solo aplica una parte se enumeran los criterios o el intervalo correspondiente. La sección 21 desglosa siempre los 128 criterios de forma individual.

## 2. Integración con la spec 001

La spec 002 produce un contexto de seguridad inmutable para cada solicitud administrativa: `account_id`, `role`, `session_id` y vigencia. Los casos de uso de la spec 001 reciben ese contexto mediante un puerto de autorización y nunca aceptan el rol desde el navegador.

| Integración | Regla conservada | Cobertura 002 |
|---|---|---|
| Agenda, citas, resultados y bloqueos | Propietario y personal operan según RF-10; la spec 001 conserva todas sus validaciones temporales y de datos. | RF-01-CA-06; RF-10-CA-01, CA-02 y CA-05; RF-11-CA-08 y CA-09 |
| Servicios y precios | Solo el propietario puede crearlos, editarlos, activarlos o desactivarlos. | RF-10-CA-01, CA-03 y CA-05 |
| Códigos privados y notificaciones de citas | Ninguna sesión administrativa permite consultar o mostrar el código; el reenvío y los reintentos de notificaciones fallidas usan los mecanismos protegidos de la spec 001 y únicamente los contactos registrados. | RF-10-CA-02; RF-11-CA-02 y CA-08 |
| Datos privados | Toda operación vuelve a autenticar la sesión y autorizar el rol en el backend. | RF-04-CA-07; RF-10-CA-01 a CA-05 |
| Historial | Solo se registra una mutación o denegación por permisos; las consultas ordinarias no generan eventos. | RF-11-CA-08 y CA-09 |
| Notificaciones | Se reutilizan el puerto de correo, los estados de entrega y el adaptador de Resend; WhatsApp no se usa para seguridad. | RF-02-CA-01, CA-06 y CA-09; RF-06-CA-02 y CA-06; RF-07-CA-07 y CA-11; RF-12-CA-01 a CA-10 |

La implementación de una operación administrativa de la spec 001 permanecerá cerrada hasta que la sesión y la política de la spec 002 estén conectadas y probadas.

## 3. Arquitectura y estructura lógica

Se conserva el monolito modular aprobado:

```text
React administrativo
        |
FastAPI: contratos, cookies y cabeceras
        |
Casos de uso de identidad y acceso
        |
Dominio: autenticación, autorización, sesiones y retención
        |
Puertos: PostgreSQL, reloj, criptografía y correo
```

El dominio y los casos de uso no importan FastAPI, React, SQLAlchemy, PostgreSQL ni el SDK del proveedor de correo.

### 3.1 Módulos

| Módulo lógico | Responsabilidad | RF y criterios EARS |
|---|---|---|
| Cuentas administrativas | Estados, roles, propietario único, personal único y correos reclamados. | RF-01-CA-01 a CA-06 y CA-14 a CA-16; RF-09-CA-01 a CA-06 |
| Configuración inicial | Registrar solo el correo del propietario, emitir el enlace y cerrar el proceso tras activarlo. | RF-01-CA-01 y CA-07 a CA-13 |
| Invitaciones | Reservar correo, activar, reenviar o cancelar la invitación del personal. | RF-02-CA-01 a CA-09 |
| Credenciales | Argon2id, validación de longitud y lista local de contraseñas bloqueadas. | RF-03-CA-01 a CA-12; RF-05-CA-01 a CA-08; RF-06-CA-01 a CA-13 |
| Segundo factor | Configuración TOTP, tolerancia, periodos usados y recuperación. | RF-07-CA-01 a CA-24 |
| Sesiones | Una sesión por cuenta, actividad humana, expiración e invalidación global. | RF-04-CA-01 a CA-08 |
| Enlaces de seguridad | Emisión, entrega, vencimiento, sustitución y consumo atómico. | RF-01-CA-07 a CA-12; RF-02; RF-04-CA-08; RF-06; RF-07-CA-07 a CA-12 y CA-18 a CA-24; RF-08; RF-09-CA-01; RF-12-CA-07 a CA-10 |
| Correo administrativo | Correo vigente, reservas y cambio confirmado sin duplicar avisos. | RF-01-CA-02 y CA-14 a CA-16; RF-08-CA-01 a CA-08 |
| Autorización | Políticas de propietario, personal y persona no autenticada. | RF-01-CA-03 a CA-06; RF-09-CA-04 y CA-05; RF-10-CA-01 a CA-05; RF-11-CA-03 y CA-04 |
| Protección contra abuso | Fallos compartidos, bloqueos y cuatro límites móviles. | RF-03-CA-02 a CA-12; RNF-01 |
| Historial | Eventos mínimos, consulta exclusiva, inmutabilidad y retiro a 12 meses. | RF-09-CA-02 y CA-03; RF-11-CA-01 a CA-09 |
| Avisos de seguridad | Destinatarios, deduplicación, fallos y conservación de la acción segura. | RF-12-CA-01 a CA-10; soporte de RF-02, RF-05, RF-06, RF-07, RF-08 y RF-09 |

### 3.2 Flujo de datos

1. FastAPI valida forma, origen y límite de volumen.
2. El caso de uso carga la cuenta o sesión y solicita decisiones al dominio.
3. El dominio produce una transición y eventos, sin conocer la base ni el correo.
4. El adaptador PostgreSQL revalida y confirma atómicamente la transición.
5. Las entregas se solicitan por un puerto idempotente; sus resultados se registran sin secretos.
6. React recibe únicamente el resultado y los datos autorizados, con mensajes visibles en español.

**Cobertura:** RF-01 a RF-12; cada flujo detallado identifica sus criterios en las secciones 6 a 17.

### 3.3 Estructura de archivos propuesta

Estas rutas son propuestas; este plan no las crea:

| Ruta prevista | Responsabilidad | Cobertura |
|---|---|---|
| `backend/app/domain/authentication/` | Contraseñas, fallos, TOTP y recuperación. | RF-03, RF-05, RF-06 y RF-07 |
| `backend/app/domain/authorization/` | Políticas puras por rol. | RF-01, RF-09, RF-10 y RF-11 |
| `backend/app/domain/sessions/` | Ciclo y actividad de sesiones. | RF-04 |
| `backend/app/domain/audit/` | Eventos mínimos y retención. | RF-09 y RF-11 |
| `backend/app/application/admin_access/` | Casos de uso y puertos. | RF-01 a RF-12 |
| `backend/app/infrastructure/security/` | Argon2id, TOTP, cifrado, huellas y lista bloqueada. | RF-01, RF-03, RF-05 a RF-08 |
| `backend/app/infrastructure/persistence/` | Repositorios y coordinación PostgreSQL. | RF-01 a RF-12 |
| `backend/app/infrastructure/notifications/` | Adaptador de correo y entrega idempotente reutilizados. | RF-02, RF-05 a RF-09 y RF-12 |
| `backend/app/web/admin_auth/` | Contratos FastAPI, cookies, CSRF y errores. | RF-01 a RF-12 |
| `backend/app/cli/` | Configuración inicial protegida del propietario. | RF-01 |
| `backend/migrations/` | Tablas, índices, restricciones y revisiones. | RF-01 a RF-12 |
| `backend/resources/blocked_passwords.sha1` | Huellas locales ordenadas, sin contraseñas legibles. | RF-05-CA-06 |
| `backend/resources/blocked_passwords.metadata.json` | Fuente, versión, fecha, conteo y checksum del conjunto. | RF-05-CA-06 |
| `backend/tests/unit/admin_access/` | Dominio y tiempo controlado. | RF-01 a RF-12 |
| `backend/tests/integration/admin_access/` | PostgreSQL, migraciones y proveedores simulados. | RF-01 a RF-12 |
| `backend/tests/contract/admin_access/` | Contratos, autorización y sanitización. | RF-01 a RF-12 |
| `frontend/src/admin/auth/` | Inicio, activación, recuperación y seguridad propia. | RF-01 a RF-08 |
| `frontend/src/admin/access/` | Navegación y controles por rol sin sustituir al backend. | RF-09, RF-10 y RF-11 |
| `frontend/tests/e2e/admin_access/` | Recorridos Playwright. | RF-01 a RF-12 |

## 4. Modelo de datos relacional

Los nombres son lógicos; Alembic concretará tipos e índices en una tarea posterior.

| Entidad | Datos e invariantes | Cobertura |
|---|---|---|
| `admin_accounts` | Identificador; rol `owner` o `staff`; estado; referencia al correo vigente; huella Argon2id opcional hasta activación; marcas de restricción y retención. Exactamente un propietario; a lo sumo un personal pendiente o activo. | RF-01; RF-02; RF-05; RF-06; RF-09 |
| `admin_email_claims` | Huella con clave del correo normalizado, valor cifrado para entrega, tipo `current` o `reserved` y cuenta. Unicidad global de la huella; máximo un correo vigente y una reserva por cuenta. | RF-01-CA-02 y CA-14 a CA-16; RF-08 |
| `owner_bootstrap_state` | Fila única, estado abierto/cerrado, propietario asociado y fechas. Nunca almacena credenciales. | RF-01-CA-01 y CA-07 a CA-13 |
| `security_links` | Propósito, huella del token, cuenta o invitación, emisión, expiración, estado y entrega. Token de 256 bits; máximo uno vigente por cuenta y propósito. | RF-01, RF-02, RF-04, RF-06, RF-07, RF-08, RF-09 y RF-12 |
| `pending_security_setups` | Configuración TOTP cifrada todavía no confirmada, flujo y estado; se elimina al confirmar, fallar, vencerse o invalidarse. | RF-01-CA-08 y CA-10; RF-02-CA-02; RF-07-CA-05, CA-08 a CA-10, CA-23 y CA-24 |
| `totp_factors` | Secreto cifrado autenticadamente, versión de clave, parámetros del estándar, estado y fecha de confirmación. Máximo uno activo por cuenta. | RF-07-CA-01 y CA-05 a CA-24 |
| `totp_period_uses` | Cuenta, factor y contador consumido. Unicidad por cuenta, factor y periodo; el registro aparece solo al completar correctamente la operación. | RF-03-CA-12; RF-07-CA-14, CA-15, CA-21 y CA-22 |
| `recovery_codes` | Cuenta, huella con clave, posición, estado y uso. Diez activos tras cada generación; nunca conserva el texto. | RF-03-CA-12; RF-07-CA-02 a CA-05, CA-10, CA-13, CA-16 y CA-20 a CA-23 |
| `admin_sessions` | Huella del token, cuenta, creación, última actividad humana, expiración absoluta, huella CSRF e invalidación. Máximo una sesión activa por cuenta. | RF-03-CA-07; RF-04-CA-01 a CA-08 |
| `credential_failure_events` | Cuenta, solicitud, categoría e instante; sin credenciales. Cada solicitud rechazada aporta como máximo un evento. | RF-03-CA-03 a CA-12; RF-07-CA-18 y CA-22 |
| `account_security_state` | `lock_until`, identificador del quinto fallo y restricción posterior a recuperación. Se actualiza bajo bloqueo de cuenta. | RF-03-CA-03 a CA-11; RF-06-CA-09, CA-12 y CA-13 |
| `rate_limit_events` | Categoría, huella con clave de IP o cuenta, instante y solicitud idempotente. Nunca guarda IP legible. | RNF-01, cuatro límites de volumen |
| `rate_limit_guards` | Una fila por sujeto y límite para serializar conteos concurrentes. | RNF-01 y RNF-02 |
| `admin_audit_events` | Actor opcional, acción, resultado, instante y referencia interna opcional; sin secretos ni datos de clientas. Solo inserción ordinaria. | RF-11-CA-01 a CA-09; RF-09-CA-02 y CA-03 |
| `security_notification_deliveries` | Evento, destinatario cifrado temporalmente, plantilla, clave idempotente, estado y error sanitizado. Nunca copia secretos completos. | RF-02-CA-09; RF-12-CA-01 a CA-10 |

### 4.1 Invariantes protegidas en PostgreSQL

- índice único parcial para permitir como máximo un rol propietario y una fila única de configuración inicial; la comprobación de disponibilidad pública exige que el correo del único propietario ya esté registrado, con lo que se cumple su existencia antes de abrir el sistema;
- índice único parcial para como máximo un personal en estado pendiente o activo;
- unicidad de `admin_email_claims.lookup_digest`, incluida una reserva de cambio;
- máximo una sesión activa por cuenta y un enlace vigente por propósito;
- máximo un factor TOTP activo y una configuración pendiente aplicable;
- unicidad de periodo TOTP consumido y de código de recuperación consumido;
- referencias obligatorias entre eventos, cuentas y elementos internos sin copiar datos privados;
- enums y restricciones para estados, propósitos y resultados;
- escrituras sensibles bajo transacción y bloqueo de las filas de cuenta o guardia correspondientes.

Las reglas que cruzan tablas se comprueban de nuevo dentro de la misma transacción. La interfaz nunca es la única barrera.

**Cobertura:** RF-01-CA-03 a CA-05 y CA-09 a CA-16; RF-02-CA-03, CA-04, CA-06 y CA-08; RF-03-CA-03, CA-09 y CA-12; RF-04-CA-01, CA-02, CA-06 y CA-08; RF-06-CA-04, CA-05 y CA-10; RF-07-CA-03, CA-08, CA-10, CA-15, CA-20 a CA-23; RF-08-CA-03, CA-05, CA-07 y CA-08; RF-09-CA-01 y CA-06; RF-11-CA-05 a CA-08; RNF-02.

## 5. Modelo de amenazas y controles

| Amenaza | Control | Verificación | Cobertura |
|---|---|---|---|
| Robo de PostgreSQL | Argon2id; cifrado autenticado; huellas HMAC; claves fuera de la base. | Inspección de esquema, volcados y pruebas de no recuperación. | RF-01-CA-13; RF-02-CA-07; RF-05-CA-04; RF-07-CA-13 y CA-24; RNF-01 |
| Enumeración de cuentas | Respuestas y tiempos equivalentes, cálculo Argon2 señuelo y límites por IP. | Contratos comparativos para cuenta existente e inexistente. | RF-03-CA-02; RF-06-CA-01; RF-07-CA-18 |
| Fuerza bruta | Argon2id, bloqueo 5/15 y límites móviles serializados. | Bordes, ventanas y concurrencia. | RF-03-CA-03 a CA-05; RNF-01 y RNF-02 |
| Robo o fijación de sesión | Token aleatorio, cookie `__Host-`, rotación al autenticar, huella en DB y una sesión. | Reutilización, fijación, expiración y revocación. | RF-04-CA-01 a CA-07 |
| CSRF | SameSite estricto, Origin/Referer, token sincronizador y cabecera obligatoria. | Solicitudes cruzadas y token ausente/incorrecto. | RF-04; RF-10; RNF-01 |
| XSS y filtración en navegador | CSP, salida escapada, `no-store`, `no-referrer`, secretos solo en memoria y limpieza inmediata de URL. | Cabeceras, inyección y almacenamiento del navegador. | RF-07-CA-24; RNF-01 |
| Reutilizar enlace o código | Huella, vencimiento del servidor, bloqueo de fila y consumo atómico. | Dos consumos simultáneos y límites exactos. | RF-01-CA-09 a CA-12; RF-02-CA-04; RF-03-CA-12; RF-06-CA-04 y CA-10; RF-07-CA-03, CA-08, CA-10, CA-15 y CA-20; RF-08-CA-07 y CA-08 |
| Sustituir correo concurrentemente | Registro único de reclamaciones, reserva y revalidación al confirmar. | Carreras entre invitación, alta y cambios. | RF-01-CA-14 a CA-16; RF-08-CA-02, CA-03, CA-07 y CA-08 |
| Elevar privilegios | Rol obtenido exclusivamente de la sesión y política en cada caso de uso. | Matriz negativa completa. | RF-01-CA-06; RF-09-CA-04; RF-10-CA-01 a CA-05; RF-11-CA-03 y CA-04 |
| Filtrar secretos por logs, correo o historial | Redacción central, plantillas permitidas y escaneo automatizado. | Captura de respuestas, logs, auditoría y mensajes. | RF-03-CA-08; RF-11-CA-02; RF-12-CA-06 y CA-09 |
| Pérdida simultánea de factores | No existe omisión automática; se conserva la barrera aprobada. | Flujo negativo sin contraseña, TOTP ni recuperación. | RF-07-CA-12 y CA-19 |
| Fallo o repetición de correo | Intención idempotente en PostgreSQL; enlaces fallidos invalidados; acciones confirmadas no revierten. | Fallo inmediato, tardío e incierto. | RF-02-CA-09; RF-12-CA-04 a CA-10 |
| Retención excesiva | Filtro por vencimiento, proceso de siguiente expiración y limpieza al arrancar. | Reloj controlado y purga idempotente. | RF-09-CA-02 y CA-03; RF-11-CA-06 y CA-07 |

## 6. Configuración inicial protegida del propietario

Se utilizará un comando administrativo ejecutado únicamente dentro del entorno autorizado del despliegue. Pedirá el correo de forma interactiva para evitar incluirlo en el historial del shell.

1. Obtiene el bloqueo de `owner_bootstrap_state`.
2. Rechaza si el proceso está cerrado o ya existe otro propietario.
3. Valida y reclama atómicamente el correo normalizado.
4. Crea la cuenta inactiva sin contraseña ni factor.
5. Emite un token de 256 bits, guarda solo su huella y solicita el correo.
6. Si el envío falla, invalida ese enlace y conserva al propietario inactivo; el comando puede emitir uno nuevo mientras el proceso siga abierto.
7. El enlace permite preparar TOTP y presentar contraseña y código nuevo; una única transacción activa cuenta, contraseña y factor, genera los diez códigos, consume el enlace y cierra para siempre el bootstrap.
8. La persona técnica nunca recibe ni puede consultar contraseña, TOTP o códigos.

La activación no crea una sesión: el propietario inicia sesión posteriormente con sus factores.

**Cobertura:** RF-01-CA-01, CA-03, CA-07 a CA-16; RF-05; RF-07-CA-01, CA-02, CA-16 y CA-24; RF-11-CA-01; RF-12-CA-07 a CA-09.

## 7. Invitación y activación del personal

1. Una sesión de propietario supera autorización y límites aplicables.
2. Se bloquea el estado de personal, se valida el correo y se crea su reclamación y cuenta pendiente.
3. Se crea un enlace de 24 horas en estado de emisión.
4. Si el proveedor lo acepta, el enlace queda vigente; si falla, queda inválido y la cuenta permanece pendiente.
5. Reenviar invalida primero el enlace anterior y emite otro distinto por 24 horas; cancelar invalida enlace, cuenta pendiente y reclamación.
6. Al abrir un enlace válido, el personal configura personalmente contraseña y TOTP.
7. La confirmación final revalida el correo y, bajo bloqueo, activa una sola cuenta, consume el enlace y genera diez códigos visibles una vez.
8. Un fallo o abandono elimina cualquier configuración parcial y no activa ni inicia sesión.

**Cobertura:** RF-01-CA-02, CA-04, CA-14 a CA-16; RF-02-CA-01 a CA-09; RF-05; RF-07-CA-01, CA-02, CA-16 y CA-24; RF-11-CA-01; RF-12-CA-03 y CA-07 a CA-09.

## 8. Contraseñas y lista comprometida

### 8.1 Almacenamiento Argon2id

- `argon2-cffi` producirá cadenas PHC Argon2id con salt aleatorio por contraseña.
- El punto inicial será memoria de 19 MiB, dos iteraciones y paralelismo uno; se medirá en el entorno real y solo podrá fortalecerse sin cambiar la spec.
- La verificación tendrá concurrencia acotada para no agotar la memoria del único despliegue.
- Una autenticación correcta rehará la huella si los parámetros vigentes son más fuertes.
- Para correos inexistentes se verificará una huella señuelo equivalente, evitando diferencias obvias de tiempo.
- La contraseña se mantiene únicamente durante la llamada necesaria y nunca se registra, cifra para recuperación ni envía.
- No existe caducidad periódica ni regla adicional de mayúsculas, números o símbolos; el frontend permite pegar, autocompletar y usar generadores de administradores de contraseñas.

### 8.2 Lista local versionada

- La fuente será el corpus oficial descargable de [Pwned Passwords de Have I Been Pwned](https://haveibeenpwned.com/API/V3#PwnedPasswords), usado sin consultas de red en tiempo de ejecución. El artefacto contendrá las huellas SHA-1 en mayúsculas de las 100,000 entradas con mayor conteo de exposición; SHA-1 solo identifica miembros de esa lista y nunca protege credenciales almacenadas.
- Los metadatos registrarán fuente, fecha de la instantánea, fecha de obtención, número de entradas y checksum; no contendrán contraseñas legibles ni relaciones con correos o identidades.
- La versión deberá revisarse antes del primer despliegue y cada 90 días; una versión más reciente reemplazará atómicamente a la anterior.
- Si el archivo falta, está corrupto o venció su revisión, crear, cambiar o restablecer contraseñas fallará de forma segura; el inicio de sesión con huellas ya creadas seguirá disponible.
- La obtención de la instantánea y la comprobación de sus términos vigentes son una puerta previa a incorporar el artefacto; no se descargará nada al aprobar este plan.

La comparación usa exactamente el valor recibido, sin alterar mayúsculas, espacios internos o Unicode; antes se aplican únicamente los límites y la regla de solo espacios definidos por la spec.

**Cobertura:** RF-05-CA-01 a CA-08; soporte de RF-01-CA-08, RF-02-CA-02, RF-03-CA-01 a CA-03, RF-06-CA-03, CA-06, CA-11 a CA-13 y RF-07-CA-06 a CA-08, CA-18 y CA-19.

## 9. TOTP y códigos de recuperación

### 9.1 TOTP

- Se implementa RFC 6238 mediante `PyOTP`, con seis dígitos, periodo de 30 segundos y parámetros compatibles con aplicaciones genéricas.
- Los códigos TOTP se generan exclusivamente en la aplicación de autenticación; nunca se envían por correo, SMS o WhatsApp ni se exige una marca concreta.
- Se aceptan los contadores anterior, actual y siguiente calculados por el reloj del servidor.
- El secreto se genera criptográficamente, se cifra con AES-256-GCM y se asocia con cuenta, propósito y versión de clave como datos autenticados.
- En una operación de un solo paso, el contador aceptado se registra como usado dentro del mismo commit exitoso. En un reemplazo de varios pasos, el flujo conserva solo el identificador del contador comprobado y trata de consumirlo condicionalmente al finalizar; si otra operación lo consumió primero, el reemplazo falla sin alterar el factor anterior. La restricción única impide dos éxitos, incluido un contador futuro cuando se vuelva actual.
- El URI de configuración y su QR se muestran solo durante el flujo pendiente. Al confirmar se destruye la copia pendiente visible.

### 9.2 Códigos de recuperación

- Se generan exactamente diez códigos de 16 caracteres con `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`, usando un generador criptográfico.
- Se muestran como cuatro grupos de cuatro. Los guiones son solo presentación; al validar se retiran espacios exteriores, se ignoran guiones y mayúsculas/minúsculas antes de obtener una huella HMAC. Cualquier otro carácter o espacio interno se rechaza.
- Se guarda una huella por código, nunca el texto. Los diez textos se devuelven una sola vez después del commit exitoso.
- Un reemplazo de varios pasos conserva únicamente la referencia interna del código comprobado, sin marcarlo como usado. Al finalizar intenta consumirlo condicionalmente; si otra operación lo utilizó primero, el reemplazo falla sin alterar el factor anterior. Un abandono deja intactos los códigos anteriores.
- Regenerar exige contraseña y TOTP, invalida atómicamente todos los anteriores, crea diez nuevos, cierra sesiones y genera auditoría y aviso.

### 9.3 Claves criptográficas

Una clave raíz versionada vivirá en el almacén de secretos del despliegue. Mediante derivación con etiquetas separadas producirá claves distintas para cifrado TOTP, huellas de enlaces, sesiones, recuperación, correo e IP. PostgreSQL solo conserva el identificador de versión. La rotación descifra y vuelve a cifrar en una operación controlada; las claves anteriores permanecen disponibles hasta verificar la migración. Una copia recuperable de las claves deberá custodiarse fuera de PostgreSQL antes de producción.

**Cobertura:** RF-03-CA-01, CA-02, CA-08 y CA-12; RF-04-CA-06 y CA-08; RF-07-CA-01 a CA-24; RF-12-CA-01, CA-05 y CA-06.

## 10. Sesiones, cookies, CSRF e invalidación

### 10.1 Sesión opaca en PostgreSQL

- Se generan al menos 256 bits aleatorios; el navegador recibe el token y PostgreSQL solo su HMAC.
- La cookie se llama con prefijo `__Host-`, usa `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/` y no define `Domain`.
- El rol nunca viaja como autoridad en la cookie; se obtiene de la cuenta en cada solicitud.
- Crear crea una sesión nueva e invalida la anterior dentro de una sola transacción.
- El servidor rechaza a los 30 minutos exactos desde la última acción humana o a las 8 horas exactas desde la creación.
- Mutaciones y cargas iniciadas por navegación humana actualizan la actividad; sondeos, estado de entrega y renovaciones automáticas no lo hacen.
- Cerrar sesión, desactivar la cuenta o completar cualquiera de los cambios enumerados en RF-04 invalida filas y cookies inmediatamente.

### 10.2 CSRF y cabeceras

- Al autenticar, el servidor genera un token CSRF ligado a la sesión y guarda solo su huella.
- React conserva el token en memoria y lo envía en una cabecera en toda solicitud autenticada que cambie estado.
- Una carga segura del contexto de sesión puede rotarlo sin extender la inactividad; no se usa `localStorage` ni `sessionStorage` para secretos.
- Además se valida `Origin` —o `Referer` cuando corresponda— contra el único origen aprobado.
- Se aplican `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, CSP restrictiva y protección contra inclusión en marcos.
- Una sesión ausente o inválida responde 401; una sesión válida sin permiso o con CSRF inválido responde 403, siempre sin datos privados.

**Cobertura:** RF-03-CA-07; RF-04-CA-01 a CA-08; RF-09-CA-01; RF-10-CA-01 a CA-05; RNF-01 y RNF-03.

## 11. Enlaces temporales de un solo uso

Todos los enlaces usan el mismo mecanismo y políticas distintas por propósito:

| Propósito | Vigencia | Estado seguro si falla la entrega | Cobertura |
|---|---:|---|---|
| Activación inicial | 30 minutos | Propietario inactivo; puede reemitirse desde el comando. | RF-01-CA-07 a CA-12; RF-12-CA-07 a CA-09 |
| Invitación | 24 horas | Personal pendiente; propietario puede reenviar o cancelar. | RF-02-CA-01 a CA-09 |
| Recuperación de contraseña | 30 minutos | Contraseña vigente sin cambios. | RF-06-CA-01 a CA-05; RF-12-CA-07 a CA-09 |
| Restablecimiento forzado | 30 minutos | Contraseña anterior continúa inutilizable. | RF-06-CA-06, CA-07, CA-10 y CA-11; RF-12-CA-10 |
| Reemplazo del segundo factor | 30 minutos | Factor, códigos y sesiones anteriores sin cambios. | RF-07-CA-06 a CA-12, CA-18, CA-19 y CA-23 |
| Cambio de correo | 30 minutos | Correo anterior vigente y reserva nueva liberada. | RF-08-CA-01 a CA-08; RF-12-CA-07 a CA-09 |

El token tiene 256 bits, no contiene datos personales y se almacena como HMAC. El correo abre una ruta del mismo origen con el token en el fragmento del navegador; React lo copia a memoria, limpia inmediatamente la URL y lo envía en el cuerpo de un `POST`. Así no llega en la solicitud inicial, logs del servidor ni cabecera `Referer`.

Inspeccionar un enlace no lo consume. Confirmarlo ejecuta un `UPDATE` condicional o bloqueo de fila que comprueba propósito, estado y `now < expires_at`; a la expiración exacta se rechaza. Un enlace nuevo invalida el anterior antes de quedar vigente. Cualquier confirmación sensible revalida cuenta, correo y credenciales inmediatamente antes del commit.

**Cobertura:** RF-01-CA-07 a CA-12 y CA-15; RF-02-CA-01 a CA-06, CA-08 y CA-09; RF-04-CA-08; RF-06-CA-01 a CA-13; RF-07-CA-06 a CA-12, CA-18, CA-19, CA-23 y CA-24; RF-08-CA-02, CA-03, CA-05, CA-07 y CA-08; RF-09-CA-01; RF-12-CA-07 a CA-10.

## 12. Cambio de correo y reservas

La forma visible del correo se cifra para poder enviar mensajes; su versión normalizada en minúsculas se transforma con HMAC para búsqueda y unicidad.

1. Se comprueban contraseña y TOTP y se aplican límites.
2. Bajo bloqueo de la cuenta, se invalida la reserva anterior y se intenta reclamar el nuevo correo.
3. Se emite el enlace sin sustituir el correo vigente.
4. Un fallo de envío invalida el enlace y libera la reclamación nueva.
5. Al confirmar, se vuelve a comprobar la reclamación y se cambia el correo atómicamente.
6. Se invalidan sesiones, enlaces y configuraciones incompletas conforme a RF-04.
7. Se crean exactamente dos intenciones idempotentes: una al correo anterior y otra al nuevo; no se crea el aviso general adicional.

Una restricción única en `admin_email_claims` resuelve carreras entre propietario, invitación y cambios. La respuesta de correo ocupado es genérica y no identifica la cuenta que lo utiliza.

**Cobertura:** RF-01-CA-02, CA-14 a CA-16; RF-03-CA-03, CA-04, CA-08 y CA-12; RF-04-CA-06 y CA-08; RF-08-CA-01 a CA-08; RF-12-CA-01, CA-05 a CA-09.

## 13. Recuperación y reemplazo de factores

### 13.1 Recuperación de contraseña

- La solicitud pública siempre responde igual y aplica el límite compartido por IP.
- Si existe una cuenta activa, sustituye cualquier enlace previo y solicita otro por 30 minutos.
- El enlace permite elegir una contraseña nueva válida; al confirmar invalida sesiones y enlaces, pero conserva TOTP y códigos.
- El bloqueo temporal original no cambia.
- Después de recuperar, queda activa la restricción que impide iniciar reemplazo de TOTP con esa contraseña hasta completar un inicio de sesión con el factor anterior o un código de recuperación.

### 13.2 Restablecimiento forzado del personal

- Solo el propietario puede iniciarlo.
- La contraseña anterior se inutiliza y las sesiones se cierran antes de solicitar el correo.
- Si la entrega falla o el enlace vence, el personal sigue sin acceso; el propietario puede emitir uno nuevo.
- El propietario nunca elige ni conoce la contraseña nueva.

### 13.3 Reemplazo del segundo factor

- Desde sesión: exige contraseña y TOTP o recuperación; conserva una referencia interna a la credencial comprobada y solo intenta consumirla al completar el flujo.
- Sin factor: exige correo y contraseña vigentes, cuenta activa no bloqueada y ausencia de la restricción posterior a recuperación; la respuesta siempre es genérica.
- El factor anterior, códigos y sesiones siguen activos mientras se prueba la configuración nueva.
- La confirmación del TOTP nuevo sustituye todo atómicamente, consume condicionalmente la credencial identificada cuando corresponde, genera diez códigos, invalida enlaces y sesiones, audita y avisa.
- Un abandono, vencimiento o fallo descarta lo nuevo y deja sin cambios la credencial anterior; no concede sesión.
- Sin contraseña, factor anterior y códigos no existe recuperación automática ni ruta administrativa de omisión.

### 13.4 Regeneración de códigos

Es una única operación autenticada: comprueba contraseña y TOTP, crea diez códigos, invalida los anteriores y la sesión, marca el periodo usado, audita y avisa dentro del mismo resultado transaccional. Un fallo conserva todos los códigos anteriores.

**Cobertura:** RF-03-CA-03, CA-04, CA-08 a CA-12; RF-04-CA-06 y CA-08; RF-05-CA-02, CA-05 y CA-06; RF-06-CA-01 a CA-13; RF-07-CA-03 a CA-23; RF-09-CA-01 y CA-06; RF-11-CA-01; RF-12-CA-01, CA-04 a CA-10.

### 13.5 Desactivación y reemplazo del personal

El propietario bloquea la cuenta objetivo y, en una sola transacción, la marca desactivada, cierra sus sesiones, invalida enlaces y configuraciones pendientes, destruye el factor TOTP y los códigos de recuperación y libera la reclamación del correo. El correo cifrado se conserva únicamente hasta el vencimiento identificable de §16. Se registran la desactivación y el aviso correspondiente al propietario. La cuenta no puede reactivarse: una autorización posterior comienza como invitación y cuenta nuevas.

**Cobertura:** RF-01-CA-05; RF-09-CA-01 a CA-06; RF-11-CA-01; RF-12-CA-03 a CA-05.

## 14. Autorización y mínimo privilegio

La autorización es una política del caso de uso. React puede ocultar opciones, pero FastAPI siempre solicita una decisión de backend con la identidad cargada de la sesión.

| Capacidad | Propietario | Personal | No autenticada | Cobertura |
|---|:---:|:---:|:---:|---|
| Operar citas, resultados, reenvío de código y bloqueos de spec 001 | Sí | Sí | No | RF-10-CA-01, CA-02 y CA-05 |
| Gestionar servicios y precios | Sí | No | No | RF-10-CA-01, CA-03 y CA-05 |
| Reintentar notificaciones fallidas de citas a contactos registrados, sin mostrar el código | Sí | Sí | No | RF-10-CA-01, CA-02 y CA-05; integración estricta con spec 001 |
| Cambiar su propia contraseña, correo, TOTP o códigos | Sí | Sí | No | RF-05-CA-02; RF-07-CA-04 y CA-05; RF-08-CA-01 y CA-06 |
| Invitar, cancelar invitación, forzar reset o desactivar personal | Sí | No | No | RF-02; RF-06-CA-06 y CA-07; RF-09-CA-01, CA-04 y CA-05 |
| Consultar historial | Sí | No | No | RF-10-CA-01 y CA-04; RF-11-CA-03 y CA-04 |
| Cambiar rol, desactivar propietario o reactivar personal | No por funciones ordinarias | No | No | RF-01-CA-03; RF-09-CA-04 y CA-05 |
| Funciones públicas de la spec 001 | Sí, fuera de sesión administrativa | Sí, fuera de sesión administrativa | Sí | Separación de RF-01-CA-06 y RF-10 |

Un rechazo por rol no inicia ninguna mutación y genera el evento exigido. Un 403 no revela la existencia del recurso solicitado.

## 15. Límites, bloqueos y concurrencia

### 15.1 Fallos de credenciales y bloqueo

- La cuenta conocida tiene una única secuencia de fallos para login y operaciones sensibles.
- Cada solicitud incorrecta aporta como máximo un evento, aunque fallen varias credenciales.
- El quinto fallo dentro de 15 minutos fija `lock_until` en ese instante más 15 minutos.
- Durante el bloqueo se rechaza antes de comprobar credenciales, no se añade fallo ni se mueve `lock_until`.
- Solo un inicio de sesión completo correcto borra fallos; una operación sensible correcta no lo hace.
- Un código correcto se consume únicamente si toda la solicitud termina correctamente; en un flujo de varios pasos solo se conserva su referencia interna hasta el commit final.
- Una sesión ya abierta conserva operaciones ordinarias autorizadas, pero no las sensibles enumeradas.
- Recuperar la contraseña sigue disponible y no modifica el bloqueo.

**Cobertura:** RF-03-CA-02 a CA-12; RF-06-CA-08 y CA-09; RF-07-CA-18, CA-20 y CA-22.

### 15.2 Límites móviles

| Límite compartido | Capacidad | Sujeto | Cobertura |
|---|---:|---|---|
| Login, recuperación y reemplazo perdido | 20 en 15 minutos | Huella de IP | RNF-01 |
| Operaciones administrativas autenticadas | 120 en 1 minuto | Cuenta | RNF-01 |
| Acciones de seguridad que generan mensajes | 10 en 15 minutos | Cuenta administrativa relacionada | RNF-01 |
| Operaciones administrativas de citas que generan notificación, incluidos reintentos manuales | 30 en 15 minutos | Cuenta | RNF-01 e integración spec 001 |

Cada solicitud tiene identificador interno y cuenta una vez aunque use dos canales. Los avisos automáticos de seguridad y los recordatorios automáticos de citas no consumen cupo; sus reintentos manuales sí lo consumen. Primero se evalúan todos los límites y se aplica el más restrictivo; un rechazo no crea eventos de volumen adicionales ni ejecuta efectos.

La IP se obtiene únicamente del encabezado del proxy confiable configurado; los encabezados aportados directamente por Internet no se consideran autoridad. Se almacena una HMAC, nunca la dirección legible.

### 15.3 Concurrencia

PostgreSQL serializa por cuenta, reclamación de correo, token, código, sesión o guardia de límite. Se usan actualizaciones condicionales y restricciones únicas como última defensa. No se mantiene una transacción abierta mientras se espera indefinidamente a un proveedor; un estado intermedio idempotente permite finalizar como aceptado o fallido.

**Cobertura:** RF-01-CA-11, CA-14 a CA-16; RF-03-CA-03, CA-09 y CA-12; RF-04-CA-01, CA-02 y CA-08; RF-07-CA-03, CA-08, CA-10, CA-15, CA-20 a CA-23; RF-08-CA-07 y CA-08; RNF-01 y RNF-02.

## 16. Historial administrativo y conservación

El historial registra únicamente:

- `actor_account_id` cuando haya una cuenta identificada;
- acción y resultado mediante valores controlados;
- instante absoluto mostrado en `America/Mexico_City`;
- referencia interna opaca del elemento cuando RF-11-CA-08 la exige.

No almacena IP, correo copiado, nombre de clienta, teléfono, contraseña, TOTP, recuperación, enlace ni código privado. Las consultas ordinarias no crean eventos.

Los tipos controlados incluyen login correcto o fallido, bloqueo, cierre de sesión, activación, invitación, desactivación, cambio o recuperación de contraseña, cambio de correo, reemplazo de TOTP, regeneración de códigos y las mutaciones o denegaciones de permisos enumeradas en RF-11-CA-08. El propietario filtra por cuenta, tipo y periodo.

La capa ordinaria solo permite insertar y consultar; no ofrece edición o eliminación individual. PostgreSQL rechaza actualizaciones del evento. La eliminación existe exclusivamente en el caso de uso interno de retención.

Cada evento vence al cumplirse la misma fecha y hora local después de sumar 12 meses naturales; si el día no existe en el mes resultante, se usa su último día. Toda consulta excluye inmediatamente los vencidos, aunque la limpieza física esté pendiente. Un proceso interno espera la siguiente expiración, elimina en lotes e idempotentemente y recupera pendientes antes de admitir tráfico al arrancar. Para una cuenta de personal desactivada se actualiza `identifiable_until` con su último evento; al vencer se borra correo cifrado y cualquier asociación identificable restante, manteniendo solo datos no identificables permitidos.

**Cobertura:** RF-09-CA-02, CA-03 y CA-06; RF-10-CA-05; RF-11-CA-01 a CA-09; RNF-03 y RNF-04.

## 17. Avisos de seguridad y fallos de entrega

Se reutiliza el puerto de correo y Resend sin rastreo aprobados en el plan 001, con simulador en desarrollo. Cada intención posee una clave idempotente derivada de evento, destinatario y plantilla.

| Evento | Destinatario exacto | Observación |
|---|---|---|
| Contraseña, TOTP o códigos de recuperación cambiados | Titular en su correo vigente | Sin factores ni enlaces. |
| Correo cambiado | Una vez al anterior y una vez al nuevo | Sustituye al aviso general. |
| Cuenta bloqueada | Titular | Si es personal, también se aplica la fila siguiente. |
| Personal invitado, activado, bloqueado o desactivado | Propietario | El enlace de invitación al personal es un mensaje transaccional separado. |
| Acción que exige activación, recuperación, cambio de correo o reemplazo | Correo exigido por el flujo | Entrega separada del aviso de seguridad. |

### 17.1 Acciones ya confirmadas

Cambios de contraseña o TOTP, bloqueos y eventos del personal se confirman primero en PostgreSQL. Después se intenta el aviso. Un fallo queda auditado y nunca revierte la protección. El cambio de correo genera únicamente sus dos avisos específicos.

### 17.2 Acciones que dependen de un enlace

El enlace comienza en estado de emisión. El adaptador usa una clave idempotente:

- aceptación del proveedor: el enlace pasa a vigente;
- rechazo confirmado: se invalida y se restaura el estado seguro definido;
- resultado incierto: se reconcilia con la misma clave antes de decidir, sin crear otro token;
- fallo tardío comunicado por el proveedor: se invalida si aún estaba vigente y se registra el fallo.

Una solicitud pública conserva respuesta genérica. Una acción identificada informa en español que el correo no pudo enviarse, sin causa interna. Una nueva solicitud siempre crea otro token, invalida los anteriores del mismo propósito y recibe plazo completo.

El destinatario cifrado se elimina cuando deja de ser necesario para finalizar la entrega. Los avisos de seguridad nunca contienen enlaces ni secretos. Los mensajes transaccionales separados cuyo único propósito es entregar un enlace exigido por la spec incluyen solo ese enlace opaco y la información mínima necesaria.

**Cobertura:** RF-02-CA-01, CA-06 y CA-09; RF-05-CA-05; RF-06-CA-02, CA-05, CA-06 y CA-10; RF-07-CA-07, CA-11, CA-17, CA-18 y CA-21; RF-08-CA-02 a CA-05; RF-09-CA-01; RF-12-CA-01 a CA-10.

## 18. Contratos web

### 18.1 Convenciones

- JSON usa identificadores técnicos en inglés; mensajes visibles están en español.
- Correos, contraseñas, TOTP, recuperación y tokens entran en el cuerpo, nunca en parámetros de consulta.
- Éxitos usan 200, 201, 202 o 204; validación 400/422; autenticación 401; autorización o CSRF 403; conflicto de estado 409; volumen 429.
- Enlaces inválidos, usados, vencidos o de propósito incorrecto comparten estado y mensaje genéricos.
- Recuperación y reemplazo público responden 202 con el mismo cuerpo exista o no la cuenta.
- Ningún error contiene traza, SQL, identificador interno, proveedor, secreto o confirmación de cuenta.

### 18.2 Operaciones públicas de seguridad

| Operación | Entrada | Salida | Errores sanitizados | Cobertura |
|---|---|---|---|---|
| Iniciar sesión | Correo, contraseña y TOTP o recuperación | Contexto mínimo, CSRF y cookie | Credenciales genéricas; bloqueo; 429 | RF-03; RF-04-CA-01 y CA-02 |
| Solicitar recuperación | Correo | Respuesta 202 genérica | Solo 429 observable | RF-06-CA-01, CA-02 y CA-08 |
| Preparar flujo de enlace | Token en cuerpo | Formulario autorizado y, solo para configurar TOTP, QR/clave pendiente | Enlace genérico | RF-01-CA-08 a CA-10; RF-02-CA-02 a CA-05; RF-07-CA-09, CA-23 y CA-24 |
| Completar recuperación | Token y contraseña nueva | Confirmación sin sesión | Enlace genérico; contraseña inválida | RF-05; RF-06-CA-03 a CA-05 y CA-09, CA-12 |
| Solicitar reemplazo perdido | Correo y contraseña | Respuesta 202 genérica | Solo 429 observable | RF-07-CA-06 a CA-08, CA-12, CA-18 y CA-19 |
| Completar reemplazo | Token, configuración nueva y TOTP de prueba | Diez códigos una vez, sin sesión | Enlace/configuración genéricos | RF-07-CA-09 a CA-11 y CA-23, CA-24 |
| Completar activación | Token, contraseña y TOTP de prueba | Diez códigos una vez, sin sesión | Enlace/configuración genéricos | RF-01-CA-08 a CA-12; RF-02-CA-02 a CA-05 |
| Confirmar correo | Token | Confirmación sin sesión | Enlace genérico | RF-08-CA-03 a CA-05 |

### 18.3 Operaciones autenticadas propias

| Operación | Entrada | Salida | Errores sanitizados | Cobertura |
|---|---|---|---|---|
| Consultar contexto | Cookie | Cuenta, rol y CSRF; no extiende actividad automática | 401 | RF-04-CA-03, CA-04 y CA-07 |
| Cerrar sesión | Cookie y CSRF | 204 y cookie retirada | 401/403 | RF-04-CA-05 |
| Cambiar contraseña | Actual, TOTP y nueva | Confirmación; sesiones cerradas | Credencial genérica; bloqueo; 429 | RF-03; RF-04-CA-06, CA-08; RF-05 |
| Solicitar cambio de correo | Nuevo correo, contraseña y TOTP | Enlace solicitado | Validación genérica; bloqueo; 409; 429 | RF-08-CA-01, CA-02, CA-07 y CA-08 |
| Iniciar reemplazo TOTP | Contraseña y TOTP o recuperación | Configuración pendiente visible | Credencial genérica; bloqueo; 429 | RF-07-CA-05 |
| Regenerar recuperación | Contraseña y TOTP | Diez códigos una vez; sesión cerrada | Credencial genérica; bloqueo; 429 | RF-07-CA-04, CA-16, CA-21 y CA-22 |

### 18.4 Operaciones exclusivas del propietario

| Operación | Entrada | Salida | Errores sanitizados | Cobertura |
|---|---|---|---|---|
| Invitar personal | Correo | Pendiente y resultado de correo | Correo no disponible; 403; 409; 429 | RF-01-CA-04 y CA-14 a CA-16; RF-02-CA-01 y CA-09 |
| Reenviar/cancelar invitación | Identificador interno | Pendiente actualizado o cancelado | Estado inválido; 403; 409; 429 | RF-02-CA-04 a CA-06 y CA-08, CA-09 |
| Forzar restablecimiento | Cuenta de personal | Acceso anterior invalidado y resultado de correo | Estado inválido; 403; 429 | RF-06-CA-06, CA-07, CA-10 y CA-11; RF-12-CA-10 |
| Desactivar personal | Cuenta de personal | Cuenta desactivada | Estado inválido; 403; 409 | RF-09-CA-01 a CA-06 |
| Consultar historial | Cuenta, tipo y periodo opcionales | Eventos no vencidos | Validación; 403 | RF-11-CA-03, CA-04, CA-06 y CA-07 |

Las operaciones administrativas de la spec 001 usan la misma cookie, CSRF y política de RF-10 sin alterar sus contratos de negocio.

## 19. Decisiones técnicas y alternativas descartadas

### DT-01. Monolito modular y stack compartido

**Decisión:** reutilizar FastAPI/Python 3.14 con `pip`, React/TypeScript/Vite con Node 24 LTS y `npm`, SQLAlchemy/Alembic, PostgreSQL, pytest y Playwright en el despliegue único.  
**Justificación:** mantiene transacciones locales, mismo origen y el objetivo operativo de $100 MXN con alerta cercana a $85.  
**Alternativa descartada:** servicio de identidad separado o frontend separado, por costo y coordinación innecesarios.  
**Cobertura:** RF-01 a RF-12.

### DT-02. Sesiones opacas del servidor

**Decisión:** token aleatorio en cookie y estado en PostgreSQL.  
**Justificación:** permite una sesión, revocación inmediata, inactividad y máximo absoluto.  
**Alternativa descartada:** JWT autocontenido, porque complica revocar de inmediato y termina requiriendo estado adicional.  
**Cobertura:** RF-03-CA-07; RF-04-CA-01 a CA-08; RF-09-CA-01.

### DT-03. Argon2id

**Decisión:** `argon2-cffi` y rehash progresivo con parámetros registrados.  
**Justificación:** resistencia moderna a ataques fuera de línea sin servicio externo.  
**Alternativa descartada:** cifrado reversible, SHA rápido, bcrypt o PBKDF2 como primera opción.  
**Cobertura:** RF-03; RF-05; RF-06; RF-07-CA-06 a CA-08 y CA-18.

### DT-04. Lista local versionada

**Decisión:** 100,000 huellas frecuentes, metadatos y revisión cada 90 días.  
**Justificación:** cumple la lista vigente sin dependencia de red durante una operación sensible.  
**Alternativa descartada:** consulta remota en cada cambio o una lista legible incluida en el repositorio.  
**Cobertura:** RF-05-CA-06.

### DT-05. TOTP estándar y QR local

**Decisión:** `PyOTP` para RFC 6238 y `qrcode.react` para representar el QR localmente, sin servicio remoto.  
**Justificación:** evita criptografía y codificación QR propias y conserva compatibilidad entre marcas.  
**Alternativa descartada:** OTP por correo/WhatsApp, dependencia de una aplicación específica o generador web externo.  
**Cobertura:** RF-07-CA-01, CA-14, CA-17 y CA-24.

### DT-06. Cifrado autenticado y huellas con clave

**Decisión:** `cryptography` para AES-256-GCM y derivación de subclaves; HMAC para búsquedas y validaciones no reversibles.  
**Justificación:** TOTP y correos necesitan recuperarse, mientras enlaces, sesiones y recuperación no.  
**Alternativa descartada:** texto plano, una clave dentro de PostgreSQL o un KMS externo en el MVP.  
**Cobertura:** RF-01-CA-13; RF-02-CA-07; RF-03-CA-08; RF-05-CA-04; RF-07-CA-02, CA-13, CA-16, CA-20 y CA-24; RF-12-CA-06.

### DT-07. Correo reclamado mediante registro único

**Decisión:** correo cifrado más HMAC normalizada en `admin_email_claims`.  
**Justificación:** expresa la unicidad entre cuentas y reservas en una sola restricción concurrente.  
**Alternativa descartada:** consultas previas independientes entre tablas.  
**Cobertura:** RF-01-CA-02 y CA-14 a CA-16; RF-08-CA-02, CA-03, CA-07 y CA-08.

### DT-08. Enlaces con fragmento y consumo PostgreSQL

**Decisión:** token en fragmento, intercambio por cuerpo y huella en PostgreSQL.  
**Justificación:** reduce exposición en logs y permite vencimiento y consumo exactos.  
**Alternativa descartada:** token en query string, token firmado autocontenido o enlace reutilizable.  
**Cobertura:** RF-01, RF-02, RF-06, RF-07, RF-08, RF-09-CA-01 y RF-12-CA-07 a CA-10.

### DT-09. Límites y bloqueos en PostgreSQL

**Decisión:** reutilizar eventos mínimos y guardias transaccionales del plan 001.  
**Justificación:** exactitud concurrente sin Redis.  
**Alternativa descartada:** contadores en memoria o introducir Redis antes de necesitar escalar.  
**Cobertura:** RF-03-CA-03 a CA-12; RNF-01 y RNF-02.

### DT-10. Entregas idempotentes sin cola externa

**Decisión:** intenciones y estados en PostgreSQL, adaptador Resend y trabajo dentro del mismo proceso desplegado.  
**Justificación:** conserva evidencia y recuperación sin Redis multicola ni otro servicio.  
**Alternativa descartada:** Celery/RabbitMQ, envío sin registro o revertir acciones confirmadas.  
**Cobertura:** RF-02-CA-09; RF-12-CA-01 a CA-10.

### DT-11. Bootstrap por comando protegido

**Decisión:** comando interactivo en el entorno autorizado, cerrado tras activar al propietario.  
**Justificación:** no deja registro público ni permite que la persona técnica conozca factores.  
**Alternativa descartada:** página secreta, credencial predeterminada o SQL manual.  
**Cobertura:** RF-01-CA-01 y CA-07 a CA-13.

### DT-12. Retención dirigida por vencimiento

**Decisión:** filtro inmediato, proceso del siguiente vencimiento y recuperación al arranque.  
**Justificación:** impide consultar eventos vencidos y retira datos sin una extensión PostgreSQL o servicio cron adicional.  
**Alternativa descartada:** borrado manual, conservación indefinida o cron externo obligatorio.  
**Cobertura:** RF-09-CA-02 y CA-03; RF-11-CA-06 y CA-07.

### DT-13. Restauración con invalidación de seguridad

**Decisión:** después de restaurar PostgreSQL y antes de admitir tráfico se invalidan todas las sesiones y enlaces restaurados, se descartan configuraciones incompletas, se liberan reservas de correo no confirmadas y se ejecutan la retención de auditoría de esta spec y el retiro de citas de la spec 001. Un restablecimiento forzado restaurado conserva la contraseña anterior inutilizable y requiere que el propietario emita un enlace nuevo.  
**Justificación:** un respaldo no debe revivir una sesión o token que ya se había consumido o invalidado después de crearlo.  
**Alternativa descartada:** publicar inmediatamente la copia restaurada o confiar solo en los vencimientos originales.  
**Cobertura:** RF-04-CA-07 y CA-08; RF-06-CA-10 y CA-11; RF-07-CA-08 y CA-23; RF-08-CA-05 y CA-07; RF-09-CA-01; RF-11-CA-07; RNF-01 a RNF-03.

### 19.1 Dependencias nuevas justificadas

| Dependencia candidata | Uso exclusivo | Motivo para no implementarlo manualmente |
|---|---|---|
| `argon2-cffi` | Huellas Argon2id. | La implementación criptográfica propia sería insegura. |
| `PyOTP` | TOTP RFC 6238. | Evita errores de estándar, ventana y formato. |
| `cryptography` | AES-GCM y derivación de claves. | Primitivas revisadas y autenticadas. |
| `qrcode.react` | Mostrar localmente el URI TOTP durante configuración. | El formato QR no es lógica de negocio y no debe enviarse a un tercero. |

No se añaden Redis, JWT, OAuth, Celery, un KMS externo ni una API de contraseñas comprometidas. Las versiones exactas y licencias se verificarán y fijarán únicamente cuando una tarea posterior reciba autorización explícita para instalar dependencias.

## 20. Estrategia de pruebas

### 20.1 Unitarias de dominio

- estados y límites de cuentas, correo exacto, contraseñas y lista bloqueada;
- ventanas exactas de enlaces, bloqueo, inactividad, sesión y retención;
- TOTP anterior/actual/siguiente, normalización y formato de recuperación;
- políticas completas por rol y contenido mínimo de auditoría;
- destinatarios y deduplicación de avisos.

**Cobertura:** RF-01-CA-02 a CA-06; RF-02-CA-03 a CA-08; RF-03; RF-04-CA-03 a CA-08; RF-05; RF-06; RF-07; RF-08; RF-09; RF-10; RF-11; RF-12.

### 20.2 Integración con PostgreSQL

- migraciones desde una base vacía y restricciones estructurales;
- propietario/personal únicos, correo reclamado y una sesión;
- consumo e invalidación de enlaces, códigos y periodos;
- cambio de correo, factor, contraseña y sesiones como transacciones completas;
- historial inmutable, expiración y limpieza de personal;
- límites móviles y bloqueo compartido con reloj controlado.
- restauración aislada que invalida sesiones, enlaces y configuraciones pendientes antes de habilitar tráfico.

**Cobertura:** RF-01-CA-03 a CA-05 y CA-09 a CA-16; RF-02-CA-03, CA-04, CA-06 y CA-08; RF-03-CA-03 a CA-12; RF-04; RF-06-CA-04 a CA-13; RF-07-CA-03 a CA-23; RF-08-CA-02 a CA-08; RF-09; RF-11-CA-05 a CA-08; RNF-02.

### 20.3 Contrato

- cada entrada, salida y código HTTP de la sección 18;
- respuestas equivalentes para cuentas o enlaces inexistentes, vencidos y usados;
- cookies y CSRF, mensajes españoles y claves técnicas inglesas;
- acciones administrativas de la spec 001 con sesión y roles reales;
- reintentos de notificaciones fallidas de citas permitidos a propietario y personal, únicamente a contactos registrados, sin revelar el código y bajo los límites de ambas specs;
- fallos de correo y estados seguros visibles.

**Cobertura:** RF-01 a RF-12; RNF-01, RNF-03 y RNF-04.

### 20.4 Seguridad

- secretos ausentes de URL final, almacenamiento web, logs, errores, historial y correo prohibido;
- parámetros Argon2, salts distintos, rehash y huella señuelo;
- CSP, `no-store`, `no-referrer`, cookie `__Host-`, Origin y CSRF;
- token de 256 bits, QR no recuperable, cifrado alterado que falla cerrado;
- matriz negativa de autorización y ausencia de acceso privado sin sesión;
- imposibilidad de cambiar el destinatario o revelar el código durante un reintento de notificación fallida de cita;
- lista bloqueada ausente, corrupta o fuera de vigencia.

**Cobertura:** RF-01-CA-06 y CA-13; RF-02-CA-05 y CA-07; RF-03-CA-02, CA-08 y CA-12; RF-04-CA-07; RF-05-CA-04, CA-06 y CA-08; RF-06-CA-01 y CA-07; RF-07-CA-12, CA-13, CA-17 a CA-20 y CA-24; RF-09-CA-04; RF-10; RF-11-CA-02 y CA-04; RF-12-CA-06; RNF-01 y RNF-03.

### 20.5 Concurrencia

- dos activaciones del propietario y dos invitaciones;
- dos reclamaciones del mismo correo y dos cambios de una cuenta;
- dos consumos del mismo enlace, recuperación, TOTP o código;
- dos inicios de sesión de la misma cuenta;
- quinto fallo concurrente y bordes de los cuatro límites;
- desactivación simultánea con una operación administrativa.

**Cobertura:** RF-01-CA-04, CA-09, CA-11 y CA-14 a CA-16; RF-02-CA-04, CA-06 y CA-08; RF-03-CA-03, CA-04, CA-09 y CA-12; RF-04-CA-01, CA-02 y CA-08; RF-06-CA-04 y CA-10; RF-07-CA-03, CA-08, CA-10, CA-15 y CA-20 a CA-23; RF-08-CA-07 y CA-08; RF-09-CA-01; RNF-01 y RNF-02.

### 20.6 Proveedor y fallos

- simulador determinista de aceptación, rechazo, fallo tardío y resultado incierto;
- cada tipo de enlace fallido conserva el estado exacto;
- avisos posteriores no revierten acciones y no se duplican;
- cambio de correo envía exactamente a los dos destinatarios;
- claves idempotentes y reemisión con token distinto.

**Cobertura:** RF-02-CA-01, CA-06 y CA-09; RF-06-CA-02, CA-05, CA-06, CA-10 y CA-11; RF-07-CA-07, CA-11 y CA-21; RF-08-CA-02 a CA-05; RF-09-CA-01; RF-12-CA-01 a CA-10.

### 20.7 Playwright

- propietario completa activación, guarda códigos e inicia/cierra sesión;
- invita al personal, quien activa su cuenta, opera solo la agenda permitida y reintenta una notificación fallida de cita sin ver el código;
- bloqueo, recuperación, cambio de contraseña/correo y sustitución de TOTP;
- códigos mostrados una vez, sesión reemplazada y expiraciones exactas con reloj controlado;
- propietario consulta filtros del historial; personal y no autenticada reciben denegación;
- navegación y sondeos demuestran qué actividad reinicia o no el límite de inactividad.

**Cobertura:** RF-01 a RF-12, sin usar Playwright como única prueba de una regla crítica.

### 20.8 Comandos previstos

Se reutilizan los comandos aprobados en el plan 001:

| Verificación | Comando |
|---|---|
| Migraciones | `python -m alembic -c backend/alembic.ini upgrade head` |
| Unitarias | `python -m pytest backend/tests/unit` |
| PostgreSQL | `python -m pytest backend/tests/integration` |
| Contratos | `python -m pytest backend/tests/contract` |
| Backend completo | `python -m pytest backend/tests` |
| Tipos | `npm --prefix frontend run typecheck` |
| Compilación | `npm --prefix frontend run build` |
| Playwright | `npm --prefix frontend run test:e2e` |

Ningún comando se ejecuta ni se considera disponible por la mera aprobación de este plan.

### 20.9 Verificación de la constitución

| Principio | Evidencia prevista |
|---|---|
| Simplicidad y Spec-Anchored | Monolito compartido, alternativas descartadas y matriz completa sin requisitos funcionales nuevos. |
| Separación | Dominio y casos de uso sin dependencias de FastAPI, React, SQLAlchemy, PostgreSQL o Resend. |
| Tests, integridad y verificación | Pruebas por capa, PostgreSQL real y concurrencia; ninguna tarea termina con una verificación fallida. |
| Seguridad, sitio público y secretos | Autenticación y autorización en cada operación, secreto externo, respuestas sanitizadas y escaneo. |
| Persistencia | Todo estado duradero se guarda en PostgreSQL. |
| Comprensión y cambios pequeños | Revisión humana, aprobación explícita y secuencia antes de generar tareas. |
| Idioma | Identificadores y logs en inglés; mensajes y contenido de BeautyHub en español. |

## 21. Matriz de cobertura de los 128 criterios EARS

Leyenda de pruebas: **U** unitarias; **PG** integración PostgreSQL; **CT** contrato; **SEC** seguridad; **CON** concurrencia; **E2E** Playwright; **MAIL** proveedor simulado.

| Criterio | Diseño principal | Pruebas |
|---|---|---|
| RF-01-CA-01 | §6, §19 DT-11 | PG, CT, E2E |
| RF-01-CA-02 | §4, §12 | U, PG, CT |
| RF-01-CA-03 | §4.1, §6, §14 | U, PG, CT |
| RF-01-CA-04 | §4.1, §7, §14 | U, PG, CON |
| RF-01-CA-05 | §7, §14 | U, PG, E2E |
| RF-01-CA-06 | §2, §14 | CT, SEC, E2E |
| RF-01-CA-07 | §6, §11 | PG, CT, MAIL |
| RF-01-CA-08 | §6, §8, §9 | U, CT, E2E |
| RF-01-CA-09 | §4.1, §6, §11 | PG, CON, CT |
| RF-01-CA-10 | §6, §9, §11 | PG, CT, E2E |
| RF-01-CA-11 | §4.1, §6, §15.3 | PG, CON |
| RF-01-CA-12 | §6, §11, §16 | PG, CT, E2E |
| RF-01-CA-13 | §6, §9.3 | SEC, CT |
| RF-01-CA-14 | §4, §12, §15.3 | PG, CON, CT |
| RF-01-CA-15 | §6, §7, §12 | PG, CON, CT |
| RF-01-CA-16 | §4.1, §12, §15.3 | PG, CON, SEC |
| RF-02-CA-01 | §7, §11, §17 | PG, CT, MAIL, E2E |
| RF-02-CA-02 | §7, §8, §9 | U, CT, E2E |
| RF-02-CA-03 | §4, §7 | PG, CT |
| RF-02-CA-04 | §7, §11 | PG, CON, CT |
| RF-02-CA-05 | §7, §18 | CT, SEC |
| RF-02-CA-06 | §7, §11, §17 | PG, CT, MAIL |
| RF-02-CA-07 | §7, §9.3 | SEC, CT |
| RF-02-CA-08 | §7, §11 | PG, CT, E2E |
| RF-02-CA-09 | §7, §17, §19 DT-10 | PG, CT, MAIL |
| RF-03-CA-01 | §8, §9, §18.2 | U, CT, E2E |
| RF-03-CA-02 | §5, §15.1, §18 | CT, SEC, E2E |
| RF-03-CA-03 | §15.1 | U, PG, CON, E2E |
| RF-03-CA-04 | §15.1 | U, PG, CT |
| RF-03-CA-05 | §15.1 | U, PG, CT |
| RF-03-CA-06 | §10, §15.1 | U, CT, E2E |
| RF-03-CA-07 | §10, §18.2 | PG, CT, E2E |
| RF-03-CA-08 | §15.1, §16 | CT, SEC |
| RF-03-CA-09 | §15.1 | U, PG, CON |
| RF-03-CA-10 | §14, §15.1 | CT, SEC, E2E |
| RF-03-CA-11 | §13.1, §15.1 | U, PG, CT |
| RF-03-CA-12 | §9, §13, §15.1 | PG, CON, SEC |
| RF-04-CA-01 | §4, §10 | PG, CON, E2E |
| RF-04-CA-02 | §10, §15.3 | PG, CON, E2E |
| RF-04-CA-03 | §10.1, §18.3 | U, CT, E2E |
| RF-04-CA-04 | §10.1 | U, PG, E2E |
| RF-04-CA-05 | §10.1, §18.3 | PG, CT, E2E |
| RF-04-CA-06 | §10.1, §13 | PG, CT, E2E |
| RF-04-CA-07 | §10, §14 | CT, SEC, E2E |
| RF-04-CA-08 | §4.1, §10, §13 | PG, CON, CT |
| RF-05-CA-01 | §8 | U, CT, E2E |
| RF-05-CA-02 | §8, §13.4 | U, CT, E2E |
| RF-05-CA-03 | §8 | U, CT |
| RF-05-CA-04 | §8, §9.3 | CT, SEC |
| RF-05-CA-05 | §8, §13 | PG, CT, MAIL |
| RF-05-CA-06 | §8.2, §19 DT-04 | U, CT, SEC |
| RF-05-CA-07 | §8 | U, CT, E2E |
| RF-05-CA-08 | §18.3 | CT, E2E |
| RF-06-CA-01 | §13.1, §18.2 | CT, SEC, E2E |
| RF-06-CA-02 | §11, §13.1, §17 | PG, CT, MAIL |
| RF-06-CA-03 | §8, §13.1 | U, CT, E2E |
| RF-06-CA-04 | §11, §13.1 | PG, CON, CT |
| RF-06-CA-05 | §10, §13.1, §17 | PG, CT, MAIL |
| RF-06-CA-06 | §13.2, §18.4 | PG, CT, MAIL, E2E |
| RF-06-CA-07 | §13.2, §14 | CT, SEC |
| RF-06-CA-08 | §13.1, §15.1 | U, CT, E2E |
| RF-06-CA-09 | §13.1, §15.1 | U, PG, E2E |
| RF-06-CA-10 | §11, §13.2 | PG, CON, MAIL |
| RF-06-CA-11 | §11, §13.2 | PG, CT, MAIL |
| RF-06-CA-12 | §13.1, §13.3 | U, PG, SEC |
| RF-06-CA-13 | §13.1, §13.3 | U, PG, E2E |
| RF-07-CA-01 | §9.1, §19 DT-05 | U, CT, E2E |
| RF-07-CA-02 | §9.2 | U, PG, E2E |
| RF-07-CA-03 | §9.2, §15.3 | PG, CON, CT |
| RF-07-CA-04 | §9.2, §13.4 | U, CT, E2E |
| RF-07-CA-05 | §9, §13.3, §18.3 | U, PG, E2E |
| RF-07-CA-06 | §13.3, §18.2 | CT, SEC, E2E |
| RF-07-CA-07 | §11, §13.3, §17 | PG, CT, MAIL |
| RF-07-CA-08 | §4.1, §11, §13.3 | PG, CON, CT |
| RF-07-CA-09 | §9.1, §13.3 | PG, CT, E2E |
| RF-07-CA-10 | §4.1, §9, §13.3 | PG, CON, E2E |
| RF-07-CA-11 | §13.3, §16, §17 | PG, CT, MAIL |
| RF-07-CA-12 | §5, §13.3, §14 | CT, SEC, E2E |
| RF-07-CA-13 | §9.3, §14 | CT, SEC |
| RF-07-CA-14 | §9.1 | U, PG, E2E |
| RF-07-CA-15 | §9.1, §15.3 | PG, CON, SEC |
| RF-07-CA-16 | §9.2 | U, CT, E2E |
| RF-07-CA-17 | §9.1, §17 | CT, SEC |
| RF-07-CA-18 | §5, §13.3, §18.2 | CT, SEC, E2E |
| RF-07-CA-19 | §5, §13.1, §13.3 | CT, SEC, E2E |
| RF-07-CA-20 | §9.2, §15.1 | U, PG, CON |
| RF-07-CA-21 | §9.2, §13.4, §17 | PG, CT, MAIL, E2E |
| RF-07-CA-22 | §9.2, §13.4, §15.1 | U, PG, CT |
| RF-07-CA-23 | §9, §11, §13.3 | PG, CT, E2E |
| RF-07-CA-24 | §9.1, §10.2, §13.3 | CT, SEC, E2E |
| RF-08-CA-01 | §12, §18.3 | U, CT, E2E |
| RF-08-CA-02 | §4, §11, §12 | PG, CT, MAIL |
| RF-08-CA-03 | §12, §15.3 | PG, CON, CT |
| RF-08-CA-04 | §12, §17 | PG, CT, MAIL |
| RF-08-CA-05 | §11, §12, §17 | PG, CT, MAIL |
| RF-08-CA-06 | §12, §14 | CT, SEC |
| RF-08-CA-07 | §4.1, §12 | PG, CON, CT |
| RF-08-CA-08 | §12, §15.3 | PG, CON, CT |
| RF-09-CA-01 | §10, §11, §13.2, §13.5, §18.4 | PG, CON, CT, E2E |
| RF-09-CA-02 | §16 | PG, CT, E2E |
| RF-09-CA-03 | §16, §19 DT-12 | U, PG, E2E |
| RF-09-CA-04 | §14 | CT, SEC, E2E |
| RF-09-CA-05 | §7, §14 | U, CT, E2E |
| RF-09-CA-06 | §9, §13.5, §16 | PG, CT, SEC |
| RF-10-CA-01 | §2, §14 | CT, SEC, E2E |
| RF-10-CA-02 | §2, §14 | CT, SEC, E2E |
| RF-10-CA-03 | §2, §14 | CT, SEC, E2E |
| RF-10-CA-04 | §14, §18.4 | CT, SEC, E2E |
| RF-10-CA-05 | §14, §16 | PG, CT, SEC |
| RF-11-CA-01 | §16 | U, PG, CT |
| RF-11-CA-02 | §16 | CT, SEC |
| RF-11-CA-03 | §14, §16, §18.4 | CT, SEC, E2E |
| RF-11-CA-04 | §14, §16 | CT, SEC, E2E |
| RF-11-CA-05 | §16 | PG, CT, SEC |
| RF-11-CA-06 | §16, §19 DT-12 | U, PG, E2E |
| RF-11-CA-07 | §16, §19 DT-12 | U, PG, E2E |
| RF-11-CA-08 | §2, §16 | PG, CT, E2E |
| RF-11-CA-09 | §2, §16 | PG, CT, E2E |
| RF-12-CA-01 | §12, §17 | U, PG, MAIL, E2E |
| RF-12-CA-02 | §15.1, §17 | U, PG, MAIL |
| RF-12-CA-03 | §7, §13.2, §13.5, §17 | U, PG, MAIL |
| RF-12-CA-04 | §13, §17 | PG, CT, MAIL |
| RF-12-CA-05 | §17 | PG, CT, MAIL |
| RF-12-CA-06 | §16, §17 | CT, SEC, MAIL |
| RF-12-CA-07 | §11, §17 | PG, CT, MAIL |
| RF-12-CA-08 | §17, §18 | CT, SEC, MAIL |
| RF-12-CA-09 | §11, §17 | PG, CT, MAIL, CON |
| RF-12-CA-10 | §11, §13.2, §17 | PG, CT, MAIL |

La matriz contiene una fila por criterio; una prueba puede cubrir varios criterios, pero ningún criterio se considera cumplido únicamente por compartir RF.

## 22. Secuencia propuesta de implementación

Cada etapa deberá dividirse después en tareas de 20–30 minutos, pero este plan no las genera:

1. **Puertas:** aprobar el plan, verificar fuente/licencia de la lista y autorizar dependencias. **Cobertura:** RF-05-CA-06 y todos los RF como control de alcance.
2. **Fundamentos de seguridad:** reloj, aleatoriedad, derivación, cifrado, Argon2id y lista. **Cobertura:** RF-03, RF-05 y RF-07.
3. **Persistencia:** cuentas, reclamaciones, enlaces, factores, sesiones, límites, auditoría y migraciones. **Cobertura:** RF-01 a RF-12.
4. **Bootstrap e invitación:** propietario y personal hasta activación completa. **Cobertura:** RF-01 y RF-02.
5. **Login, bloqueo y sesiones:** cookie, CSRF, actividad e invalidación. **Cobertura:** RF-03 y RF-04.
6. **Seguridad propia:** contraseña, correo, TOTP y recuperación. **Cobertura:** RF-05 a RF-08.
7. **Personal y autorización:** desactivación, reemplazo y conexión con spec 001. **Cobertura:** RF-09 y RF-10.
8. **Historial y retención:** eventos, filtros y retiro. **Cobertura:** RF-11.
9. **Correo de seguridad:** todos los destinatarios, enlaces y fallos. **Cobertura:** RF-02, RF-05 a RF-09 y RF-12.
10. **Interfaz y E2E:** recorridos completos en español y matriz negativa. **Cobertura:** RF-01 a RF-12.
11. **Verificación final:** 128 criterios, constitución, seguridad, costo y revisión humana. **Cobertura:** RF-01 a RF-12 y RNF-01 a RNF-04.

## 23. Finalización, riesgos y puertas pendientes

### 23.1 Verificaciones de finalización

- los 128 criterios tienen prueba identificable y todas las suites pasan;
- migraciones aplican desde cero y desde el esquema de la spec 001;
- ninguna carrera crea dos propietarios, dos integrantes vigentes, dos correos reclamados, dos sesiones o dos consumos exitosos;
- una restauración aislada no revive sesiones, enlaces ni configuraciones pendientes y completa ambos procesos de retención antes del tráfico;
- propietario, personal y persona no autenticada cumplen exactamente la matriz de autorización;
- expiraciones, bloqueos y límites pasan en sus instantes exactos con reloj controlado;
- contraseñas, TOTP, recuperación, sesiones y enlaces no aparecen en datos, URL final, logs, historial ni errores no autorizados;
- las acciones confirmadas sobreviven a fallos de aviso y los enlaces fallidos dejan el estado seguro exigido;
- los eventos y datos identificables del personal se retiran a 12 meses;
- React muestra español y los nombres técnicos y logs permanecen en inglés;
- el costo previsto permanece dentro del objetivo aprobado y no se activa infraestructura adicional;
- el responsable puede explicar y aprueba explícitamente el resultado antes de implementar.

### 23.2 Riesgos y puertas

1. **Aprobación:** el plan fue aprobado explícitamente el 9 de septiembre de 2026 y autoriza generar las tareas; no autoriza por sí solo instalar dependencias ni implementar código.
2. **Lista comprometida:** antes de incorporarla se debe obtener la instantánea oficial, registrar fecha, checksum y términos aplicables; el archivo no existe todavía.
3. **Dependencias:** las cuatro candidatas requieren comprobación de compatibilidad, licencia, versión y aprobación explícita antes de instalarse.
4. **Claves:** antes de producción debe existir una copia segura y probada de la clave raíz; perderla inutilizaría TOTP y los valores cifrados.
5. **Proveedor:** Resend debe demostrar idempotencia, webhooks y conservación compatible; mientras tanto se usa el simulador.
6. **Capacidad:** los parámetros Argon2id y su concurrencia se medirán en el recurso real sin debilitar el mínimo descrito ni superar el presupuesto.
7. **Recuperación total:** perder simultáneamente contraseña, TOTP y todos los códigos no tiene omisión automática; cualquier mecanismo futuro exige una spec nueva.
8. **Publicación:** continúa vigente la revisión jurídica pendiente de la spec 001.
9. **Restauración:** el procedimiento conjunto de las specs 001 y 002 debe ensayarse antes de producción junto con el respaldo de claves.

## 24. Aprobación registrada

El responsable aprobó explícitamente este plan el 9 de septiembre de 2026. Puede generarse `tasks.md`, pero comenzar la implementación y efectuar cada instalación de dependencias conserva sus puertas de aprobación explícita.
