# Especificación 002 — Autenticación y autorización administrativa

**Estado:** Activa; aprobada explícitamente por el responsable del proyecto el 9 de septiembre de 2026; enmienda no funcional RNF-05 aprobada explícitamente el 10 de septiembre de 2026.

## Contexto y objetivo

BeautyHub necesita proteger las operaciones administrativas y los datos privados definidos en la especificación 001. El acceso administrativo debe identificar a cada persona, aplicar permisos mínimos, proteger las sesiones y conservar evidencia verificable de las acciones realizadas.

El objetivo es proporcionar dos cuentas administrativas separadas: una para la persona propietaria y otra para una persona del negocio. Cada cuenta utiliza credenciales propias y verificación en dos pasos; nunca se comparten contraseñas.

Esta especificación define el comportamiento de autenticación, sesiones, recuperación, autorización, gestión de la cuenta de personal, avisos de seguridad e historial administrativo. No modifica el acceso público de las clientas a sus citas.

## Usuarios

### Propietario

- Es la máxima autoridad administrativa del sistema.
- Puede realizar todas las operaciones administrativas definidas en la especificación 001.
- Gestiona la cuenta del personal y consulta el historial administrativo.

### Personal

- Es una persona autorizada por el propietario para operar la agenda.
- Gestiona citas, resultados y bloqueos de disponibilidad.
- No gestiona servicios, precios, cuentas administrativas ni configuraciones de seguridad.

### Persona no autenticada

- No puede acceder a operaciones administrativas ni a datos privados.
- Puede utilizar únicamente las funciones públicas permitidas por la especificación 001.

## Historias de usuario

### HU-01 — Iniciar y cerrar sesión

Como administrador, quiero identificarme con mis propias credenciales y verificación en dos pasos para acceder de forma segura a las funciones autorizadas.

### HU-02 — Recuperar el acceso

Como administrador, quiero recuperar una contraseña olvidada mediante mi correo registrado sin permitir que otra persona se apropie de mi cuenta.

### HU-03 — Gestionar la cuenta del personal

Como propietario, quiero invitar, desactivar o reemplazar a la persona del negocio para controlar quién puede operar la agenda.

### HU-04 — Aplicar permisos mínimos

Como propietario, quiero que la cuenta del personal acceda únicamente a las operaciones necesarias para su trabajo.

### HU-05 — Revisar acciones administrativas

Como propietario, quiero consultar quién realizó cada acción relevante y cuándo ocurrió para investigar errores o usos indebidos.

### HU-06 — Recibir avisos de seguridad

Como administrador, quiero recibir avisos cuando ocurra un cambio o bloqueo relevante en mi cuenta para detectar actividad no autorizada.

## Reglas generales

- Debe existir exactamente una cuenta de propietario.
- Puede existir como máximo una cuenta de personal pendiente de activación o activa al mismo tiempo.
- La cuenta de propietario, cualquier cuenta de personal pendiente o activa y todo correo reservado por un cambio pendiente utilizan correos distintos; cada cuenta utiliza una contraseña propia.
- Ambas cuentas deben utilizar verificación en dos pasos.
- No existe registro público de cuentas administrativas.
- Las cuentas y los permisos administrativos son independientes del acceso público de las clientas.
- Una clienta continúa accediendo únicamente a la cita asociada con su código privado, conforme a la especificación 001.
- Una cuenta desactivada no puede autenticarse ni conservar sesiones activas.
- La cuenta de propietario no puede eliminarse, desactivarse ni cambiarse al rol de personal desde las funciones ordinarias del sistema.
- Todos los tiempos de esta especificación se evalúan en `America/Mexico_City`.
- Todo enlace temporal es válido desde el instante en que se emite y únicamente mientras no haya transcurrido por completo su plazo; al cumplirse exactamente los 30 minutos o las 24 horas aplicables, el enlace queda vencido y debe rechazarse.

## Requisitos funcionales

### RF-01 — Cuentas y roles administrativos

**Criterios de aceptación EARS:**

- **RF-01-CA-01:** Antes de abrir el sistema al público, la persona técnica designada deberá registrar el correo del propietario mediante el proceso inicial protegido; este proceso nunca deberá estar disponible como registro público.
- **RF-01-CA-02:** Cuando se cree o cambie el correo de una cuenta, el sistema deberá retirar los espacios externos y exigir, después de ese ajuste, entre 1 y 254 caracteres y exactamente un signo `@`. La parte anterior a `@` deberá contener únicamente letras ASCII, números o `.`, `_`, `%`, `+` y `-`; no podrá comenzar o terminar con punto ni contener dos puntos consecutivos. El dominio deberá contener al menos un punto y componerse de segmentos no vacíos con letras ASCII, números o guiones; cada segmento deberá comenzar y terminar con letra o número, y el segmento final deberá contener al menos dos letras. La validación y la comparación con el correo del propietario y con los de cuentas de personal pendientes o activas no deberán distinguir mayúsculas de minúsculas.
- **RF-01-CA-03:** Mientras exista una cuenta de propietario, el sistema deberá impedir crear otra, eliminarla, desactivarla o cambiar su rol mediante las funciones administrativas ordinarias.
- **RF-01-CA-04:** Mientras exista una cuenta de personal pendiente de activación o activa, el sistema deberá impedir invitar o activar otra cuenta de personal.
- **RF-01-CA-05:** Cuando una cuenta de personal sea desactivada, el sistema deberá permitir que el propietario invite a una persona de reemplazo.
- **RF-01-CA-06:** Cuando se evalúe cualquier operación administrativa, el sistema deberá utilizar la identidad y el rol de la sesión autenticada, sin aceptar que la persona solicitante elija o altere su rol.
- **RF-01-CA-07:** Cuando se inicie la configuración del propietario, el sistema deberá enviar al correo previamente registrado un enlace opaco, de un solo uso y válido durante 30 minutos.
- **RF-01-CA-08:** Cuando el propietario utilice un enlace inicial válido, el sistema deberá exigirle establecer personalmente una contraseña que cumpla RF-05 y completar la verificación en dos pasos antes de activar la cuenta.
- **RF-01-CA-09:** Mientras la cuenta de propietario no esté activa, el sistema deberá permitir como máximo un enlace inicial vigente; cuando se emita otro, deberá invalidar el anterior.
- **RF-01-CA-10:** Si el enlace inicial expira o la activación falla, el sistema no deberá crear una cuenta activa ni conservar una configuración parcial de contraseña o verificación en dos pasos.
- **RF-01-CA-11:** Si dos operaciones concurrentes intentan activar la cuenta de propietario, el sistema deberá permitir como máximo una activación completa.
- **RF-01-CA-12:** Cuando se active la cuenta de propietario, el sistema deberá invalidar el enlace inicial, cerrar permanentemente el proceso de creación inicial y registrar la activación como evento de seguridad.
- **RF-01-CA-13:** La persona técnica designada no deberá poder consultar ni establecer la contraseña, los secretos de verificación o los códigos de recuperación del propietario.
- **RF-01-CA-14:** Cuando se registre el correo inicial del propietario, se invite a la cuenta de personal o se solicite un cambio de correo, el sistema deberá comprobar de forma atómica que el correo normalizado no pertenezca a otra cuenta pendiente o activa ni esté reservado por otro cambio pendiente; si está ocupado, deberá rechazar la operación sin emitir un enlace ni modificar cuentas.
- **RF-01-CA-15:** Cuando se confirme una activación, invitación o cambio de correo mediante un enlace, el sistema deberá volver a comprobar inmediatamente antes del cambio que el correo normalizado no haya sido ocupado por otra cuenta u operación pendiente; si ya no está disponible, deberá invalidar el enlace y rechazar la confirmación sin cambios parciales.
- **RF-01-CA-16:** Si dos operaciones concurrentes intentan registrar o reservar el mismo correo normalizado, el sistema deberá permitir como máximo una y rechazar las demás sin revelar qué cuenta utiliza el correo.

### RF-02 — Invitar y activar la cuenta del personal

**Criterios de aceptación EARS:**

- **RF-02-CA-01:** Cuando el propietario invite a una persona del negocio con un correo disponible conforme a RF-01-CA-14, el sistema deberá reservar ese correo y enviarle un enlace opaco, de un solo uso y válido durante 24 horas.
- **RF-02-CA-02:** Cuando la persona invitada utilice un enlace válido, el sistema deberá exigirle crear su propia contraseña y activar la verificación en dos pasos antes de activar la cuenta.
- **RF-02-CA-03:** Mientras la invitación no se complete, la cuenta deberá permanecer pendiente y no podrá iniciar sesión ni realizar operaciones administrativas.
- **RF-02-CA-04:** Cuando una invitación sea utilizada, expire, sea cancelada o sea reemplazada por una nueva, el sistema deberá impedir cualquier uso posterior del enlace anterior.
- **RF-02-CA-05:** Si se proporciona una invitación inválida o expirada, el sistema deberá negar la activación mediante un mensaje genérico sin revelar detalles internos.
- **RF-02-CA-06:** Cuando el propietario ordene reenviar una invitación pendiente, el sistema deberá invalidar la anterior y emitir una nueva con un plazo completo de 24 horas.
- **RF-02-CA-07:** El propietario no deberá poder establecer, consultar ni recibir la contraseña de la persona invitada.
- **RF-02-CA-08:** Cuando el propietario cancele una invitación pendiente, el sistema deberá invalidar su enlace y permitir una nueva invitación.
- **RF-02-CA-09:** Si falla el envío inicial o el reenvío de una invitación, el sistema deberá invalidar inmediatamente el enlace cuyo envío falló, conservar la invitación en estado pendiente, impedir la activación sin un enlace válido, informar el fallo al propietario y registrarlo sin almacenar el enlace completo; el propietario deberá poder volver a reenviarla o cancelarla.

### RF-03 — Iniciar sesión y bloquear intentos fallidos

**Criterios de aceptación EARS:**

- **RF-03-CA-01:** Cuando una cuenta activa inicie sesión, el sistema deberá exigir su correo, contraseña y un código temporal válido de verificación en dos pasos o un código de recuperación válido.
- **RF-03-CA-02:** Si el correo, la contraseña, el código temporal, el código de recuperación o el estado de la cuenta no permiten autenticarla, el sistema deberá negar el acceso mediante un mensaje genérico que no identifique qué elemento falló ni confirme la existencia de la cuenta.
- **RF-03-CA-03:** Cuando una cuenta existente acumule 5 solicitudes rechazadas por credenciales incorrectas dentro de cualquier ventana móvil de 15 minutos, el sistema deberá impedir durante 15 minutos, contados desde el quinto fallo, nuevos inicios de sesión y operaciones sensibles que exijan comprobar la contraseña actual, un código temporal o un código de recuperación. Para este conteo deberá considerarse cada inicio de sesión rechazado y cada intento de cambiar la contraseña, cambiar el correo, reemplazar el segundo factor o regenerar códigos de recuperación que sea rechazado porque una o más de las credenciales proporcionadas sean incorrectas. Cada solicitud rechazada deberá contar como un solo fallo, aunque contenga más de una credencial incorrecta.
- **RF-03-CA-04:** Mientras una cuenta esté bloqueada temporalmente, el sistema deberá rechazar sus nuevos inicios de sesión y cualquier comprobación de contraseña actual, código temporal o código de recuperación sin prolongar el bloqueo ni contarlos como fallos adicionales.
- **RF-03-CA-05:** Cuando termine el bloqueo temporal, el sistema deberá permitir un nuevo intento y comenzar una nueva cuenta de fallos.
- **RF-03-CA-06:** Cuando se active el bloqueo temporal por intentos fallidos, el sistema no deberá cerrar una sesión válida que ya estuviera activa.
- **RF-03-CA-07:** Cuando una autenticación sea válida, el sistema deberá crear la sesión con el rol real de la cuenta y registrar el acceso exitoso.
- **RF-03-CA-08:** Cuando una autenticación o comprobación de credenciales falle, el sistema deberá registrar el intento sin almacenar la contraseña, el código temporal, el código de recuperación ni otros secretos proporcionados.
- **RF-03-CA-09:** Cuando se complete correctamente un inicio de sesión, el sistema deberá borrar los fallos anteriores utilizados para calcular el bloqueo temporal de esa cuenta. Una comprobación correcta de credenciales dentro de una sesión ya abierta no deberá borrar esos fallos; cada fallo dejará de contar únicamente cuando salga de la ventana móvil de 15 minutos.
- **RF-03-CA-10:** Mientras una cuenta bloqueada conserve una sesión que ya estaba abierta, el sistema deberá permitir sus operaciones ordinarias autorizadas que no exijan comprobar credenciales, sin permitir cambios de contraseña, correo o segundo factor.
- **RF-03-CA-11:** Mientras una cuenta esté bloqueada temporalmente, el sistema deberá mantener disponible el restablecimiento de contraseña mediante un enlace válido conforme a RF-06; completarlo no deberá eliminar, acortar ni prolongar el bloqueo.
- **RF-03-CA-12:** Si un inicio de sesión u operación sensible se rechaza porque cualquier credencial requerida es incorrecta, el sistema no deberá consumir un código de recuperación correcto ni marcar como utilizado un periodo de código temporal correcto proporcionado en la misma solicitud; las credenciales de un solo uso deberán consumirse de forma atómica únicamente cuando la autenticación u operación completa sea correcta.

### RF-04 — Administrar la sesión

**Criterios de aceptación EARS:**

- **RF-04-CA-01:** Cuando una cuenta complete una autenticación válida, el sistema deberá permitir una sola sesión activa para esa cuenta.
- **RF-04-CA-02:** Cuando una cuenta inicie una nueva sesión, el sistema deberá cerrar inmediatamente cualquier sesión anterior de la misma cuenta.
- **RF-04-CA-03:** Cuando una sesión acumule 30 minutos sin una acción autenticada iniciada por la persona —como abrir una sección, consultar, buscar, guardar o cancelar—, el sistema deberá cerrarla y exigir una nueva autenticación; las actualizaciones y solicitudes automáticas en segundo plano no deberán reiniciar el contador.
- **RF-04-CA-04:** Cuando una sesión cumpla 8 horas desde su creación, el sistema deberá cerrarla aunque haya existido actividad continua.
- **RF-04-CA-05:** Cuando una persona cierre sesión, el sistema deberá invalidarla inmediatamente e impedir que vuelva a utilizarse.
- **RF-04-CA-06:** Cuando se cambie correctamente la contraseña, el correo o la configuración de verificación en dos pasos, el sistema deberá cerrar todas las sesiones de esa cuenta.
- **RF-04-CA-07:** Si una sesión es inválida, expiró o corresponde a una cuenta desactivada, el sistema deberá negar cualquier operación administrativa sin exponer datos privados.
- **RF-04-CA-08:** Cuando se complete correctamente un cambio o restablecimiento de contraseña, un cambio de correo, un reemplazo del segundo factor o una regeneración de códigos de recuperación, el sistema deberá invalidar atómicamente todos los enlaces de seguridad pendientes emitidos anteriormente para esa cuenta, descartar cualquier configuración de seguridad incompleta y liberar toda reserva de correo que no se haya convertido en el correo vigente.

### RF-05 — Crear y cambiar contraseñas

**Criterios de aceptación EARS:**

- **RF-05-CA-01:** Cuando una persona cree o cambie su contraseña, el sistema deberá exigir entre 12 y 128 caracteres, permitir frases con espacios y rechazar valores formados únicamente por espacios.
- **RF-05-CA-02:** Cuando una persona autenticada cambie su contraseña, el sistema deberá exigir la contraseña actual y un código válido de verificación en dos pasos.
- **RF-05-CA-03:** El sistema no deberá imponer cambios periódicos de contraseña por antigüedad.
- **RF-05-CA-04:** El sistema no deberá mostrar, enviar ni permitir recuperar una contraseña existente.
- **RF-05-CA-05:** Cuando una contraseña cambie correctamente, el sistema deberá aplicar la invalidación general de RF-04-CA-08 y enviar el aviso de seguridad correspondiente.
- **RF-05-CA-06:** Cuando una persona cree o cambie su contraseña, el sistema deberá rechazarla si aparece en la lista vigente de contraseñas comunes o comprometidas definida en el plan técnico, aunque cumpla la longitud permitida.
- **RF-05-CA-07:** El sistema no deberá exigir combinaciones obligatorias de mayúsculas, minúsculas, números o símbolos como condición adicional a RF-05-CA-01 y RF-05-CA-06.
- **RF-05-CA-08:** Cuando una persona introduzca una contraseña, el sistema deberá permitir pegarla y utilizar las funciones de autocompletado o generación de un administrador de contraseñas.

### RF-06 — Recuperar la contraseña

**Criterios de aceptación EARS:**

- **RF-06-CA-01:** Cuando cualquier persona solicite recuperar una contraseña, el sistema deberá responder con el mismo mensaje genérico exista o no una cuenta asociada con el correo indicado.
- **RF-06-CA-02:** Cuando exista una cuenta activa asociada, el sistema deberá enviar a su correo un enlace opaco, de un solo uso y válido durante 30 minutos.
- **RF-06-CA-03:** Cuando se utilice un enlace válido, el sistema deberá exigir una contraseña nueva que cumpla RF-05 y mantener obligatoria la verificación en dos pasos para el siguiente inicio de sesión.
- **RF-06-CA-04:** Cuando un enlace sea utilizado, expire o sea reemplazado por una nueva solicitud, el sistema deberá impedir cualquier uso posterior.
- **RF-06-CA-05:** Cuando la contraseña se restablezca correctamente, el sistema deberá cerrar todas las sesiones de la cuenta, aplicar la invalidación general de RF-04-CA-08 y enviar el aviso de seguridad correspondiente.
- **RF-06-CA-06:** Cuando el propietario fuerce el restablecimiento de la cuenta de personal, el sistema deberá cerrar sus sesiones, impedir inmediatamente nuevos accesos con la contraseña anterior y enviar a la persona un enlace opaco, de un solo uso y válido durante 30 minutos para crear una nueva contraseña.
- **RF-06-CA-07:** El propietario no deberá poder elegir, consultar ni recibir la nueva contraseña de la cuenta de personal.
- **RF-06-CA-08:** Mientras una cuenta esté bloqueada temporalmente por intentos fallidos, el sistema deberá permitir que se solicite y complete el restablecimiento de su contraseña conforme a este requisito.
- **RF-06-CA-09:** Cuando la contraseña se restablezca durante un bloqueo temporal, el sistema no deberá eliminar, acortar ni prolongar el bloqueo; la cuenta deberá poder intentar iniciar sesión únicamente cuando termine el periodo original de 15 minutos.
- **RF-06-CA-10:** Mientras exista un restablecimiento forzado pendiente, el sistema deberá mantener como máximo un enlace vigente; una nueva orden del propietario deberá invalidar inmediatamente el anterior.
- **RF-06-CA-11:** Si el enlace de restablecimiento forzado expira o es sustituido, la contraseña anterior deberá permanecer inutilizable y la cuenta no podrá iniciar sesión hasta completar un enlace nuevo y válido.
- **RF-06-CA-12:** Cuando una contraseña se establezca mediante un enlace de recuperación o restablecimiento forzado, el sistema no deberá aceptarla para autorizar el reemplazo del segundo factor hasta que la cuenta complete una autenticación con su segundo factor existente o con un código de recuperación.
- **RF-06-CA-13:** Cuando la cuenta complete esa autenticación, el sistema deberá permitir que la contraseña vigente vuelva a autorizar futuros reemplazos del segundo factor conforme a RF-07.

### RF-07 — Verificación en dos pasos y recuperación

**Criterios de aceptación EARS:**

- **RF-07-CA-01:** Cuando se active una cuenta, el sistema deberá exigir la vinculación con una aplicación de autenticación compatible con un estándar abierto, capaz de generar sin conexión códigos temporales de exactamente 6 dígitos que cambien cada 30 segundos, antes de permitir el primer acceso administrativo.
- **RF-07-CA-02:** Cuando se complete la vinculación, el sistema deberá generar diez códigos aleatorios de recuperación, no elegidos por la persona, mostrarlos únicamente en ese momento y advertir que deben guardarse fuera del sistema en un lugar seguro; cada código deberá ser de un solo uso.
- **RF-07-CA-03:** Cuando se complete correctamente una autenticación u operación autorizada utilizando un código de recuperación, el sistema deberá invalidar únicamente ese código como parte del mismo resultado exitoso.
- **RF-07-CA-04:** Cuando una persona autenticada solicite regenerar sus códigos de recuperación, el sistema deberá exigir su contraseña actual y un código temporal válido de la aplicación de autenticación; un código de recuperación no deberá sustituir al código temporal para esta operación.
- **RF-07-CA-05:** Cuando una persona autenticada solicite reemplazar su configuración de verificación en dos pasos, el sistema deberá exigir su contraseña y un código temporal o de recuperación válido, y después exigir que configure y confirme el nuevo factor antes de sustituir la configuración anterior.
- **RF-07-CA-06:** Si una persona pierde el segundo factor y todos sus códigos de recuperación, el sistema deberá solicitarle el correo registrado y la contraseña actual para pedir el reemplazo.
- **RF-07-CA-07:** Cuando el correo corresponda a una cuenta activa no bloqueada, la contraseña actual sea correcta y no conserve la restricción definida en RF-06-CA-12, el sistema deberá enviar al correo registrado un enlace opaco, de un solo uso y válido durante 30 minutos.
- **RF-07-CA-08:** Mientras exista un enlace pendiente para reemplazar el segundo factor, el sistema deberá permitir como máximo uno vigente; una nueva solicitud deberá invalidar el anterior y descartar cualquier configuración nueva todavía no confirmada.
- **RF-07-CA-09:** Cuando la persona utilice un enlace válido, el sistema deberá permitirle configurar un factor nuevo y exigir un código temporal generado por esa configuración para comprobar que funciona, sin invalidar todavía el factor anterior, sus códigos de recuperación ni sus sesiones.
- **RF-07-CA-10:** Cuando se confirme correctamente el factor nuevo, tanto en un reemplazo iniciado desde una sesión como mediante un enlace, el sistema deberá activar atómicamente la configuración nueva, invalidar la anterior, invalidar todos los códigos de recuperación anteriores, aplicar la invalidación general de RF-04-CA-08, generar diez códigos de recuperación nuevos, mostrarlos una sola vez y cerrar todas las sesiones de la cuenta.
- **RF-07-CA-11:** Cuando se complete correctamente el reemplazo, el sistema deberá registrarlo como evento de seguridad y enviar un aviso al correo registrado sin incluir secretos ni códigos.
- **RF-07-CA-12:** Si la persona tampoco conoce su contraseña actual y no conserva un código de recuperación, el sistema no deberá permitir restablecer automáticamente el segundo factor mediante el correo como único medio.
- **RF-07-CA-13:** El propietario no deberá poder consultar los secretos ni los códigos de recuperación de la cuenta de personal.
- **RF-07-CA-14:** Cuando se valide un código temporal, el sistema deberá aceptar el correspondiente al periodo actual de 30 segundos y, para tolerar un desfase de reloj, los correspondientes al periodo inmediatamente anterior o posterior.
- **RF-07-CA-15:** Cuando una autenticación u operación se complete correctamente con un código temporal asociado con un periodo, el sistema deberá marcar ese periodo como utilizado como parte del mismo resultado exitoso e impedir que vuelva a utilizarse para otra autenticación u operación de esa cuenta.
- **RF-07-CA-16:** Cada código de recuperación deberá contener exactamente 16 caracteres aleatorios elegidos de las letras mayúsculas y los números, excluyendo `I`, `O`, `0` y `1`, y deberá mostrarse en cuatro grupos de cuatro caracteres separados por guiones visuales. Al validarlo, el sistema deberá retirar los espacios exteriores, ignorar los guiones y no distinguir entre letras mayúsculas y minúsculas; cualquier otro carácter o espacio interno deberá causar el rechazo del código.
- **RF-07-CA-17:** El sistema no deberá enviar códigos temporales de verificación en dos pasos por correo, SMS o WhatsApp ni exigir una marca específica de aplicación de autenticación.
- **RF-07-CA-18:** Si el correo no existe, la cuenta está pendiente, desactivada o bloqueada, la contraseña es incorrecta o conserva la restricción definida en RF-06-CA-12, el sistema deberá mostrar el mismo mensaje genérico, no enviar el enlace y no confirmar la existencia ni el estado de la cuenta; cuando corresponda a una cuenta existente, una contraseña incorrecta deberá contar conforme a RF-03.
- **RF-07-CA-19:** El sistema no deberá permitir encadenar una recuperación de contraseña por correo con un reemplazo del segundo factor por correo para recuperar automáticamente una cuenta sin presentar el segundo factor anterior o un código de recuperación.
- **RF-07-CA-20:** Cuando se proporcione un código de recuperación incorrecto, el sistema no deberá invalidar ni consumir ninguno de los códigos de recuperación válidos de la cuenta.
- **RF-07-CA-21:** Cuando la contraseña y el código temporal sean correctos, el sistema deberá invalidar todos los códigos de recuperación anteriores, aplicar la invalidación general de RF-04-CA-08, generar diez códigos nuevos conforme a RF-07-CA-02 y RF-07-CA-16, mostrarlos una sola vez, cerrar todas las sesiones de la cuenta, registrar el evento y enviar un aviso de seguridad sin incluir los códigos.
- **RF-07-CA-22:** Si la contraseña o el código temporal proporcionados para regenerar los códigos de recuperación son incorrectos, el sistema deberá rechazar la operación, conservar válidos todos los códigos de recuperación anteriores y contar la solicitud como un solo fallo conforme a RF-03.
- **RF-07-CA-23:** Si el reemplazo del segundo factor se interrumpe, su enlace expira o es invalidado, o el nuevo factor no se confirma correctamente, el sistema deberá descartar cualquier configuración nueva incompleta y conservar sin cambios el factor anterior, sus códigos de recuperación y las sesiones existentes; el flujo de reemplazo no deberá conceder por sí mismo una sesión administrativa.
- **RF-07-CA-24:** Mientras una configuración de verificación en dos pasos todavía no haya sido confirmada, el sistema deberá mostrar su código QR o clave secreta únicamente dentro de ese flujo de configuración. Después de confirmarla, el sistema no deberá volver a mostrar, enviar ni permitir consultar esa clave; cualquier dispositivo o configuración posterior deberá utilizar el proceso de reemplazo.

### RF-08 — Cambiar el correo de la propia cuenta

**Criterios de aceptación EARS:**

- **RF-08-CA-01:** Cuando una persona solicite cambiar el correo de su propia cuenta, el sistema deberá exigir su contraseña y un código temporal válido de verificación en dos pasos.
- **RF-08-CA-02:** Cuando el correo nuevo cumpla RF-01-CA-02 y esté disponible conforme a RF-01-CA-14, el sistema deberá reservarlo para ese cambio y enviarle un enlace de verificación opaco, de un solo uso y válido durante 30 minutos sin sustituir todavía el correo anterior.
- **RF-08-CA-03:** Cuando la persona utilice el enlace válido y el correo continúe disponible conforme a RF-01-CA-15, el sistema deberá sustituir el correo, cerrar sus sesiones y aplicar la invalidación general de RF-04-CA-08.
- **RF-08-CA-04:** Cuando el correo cambie correctamente, el sistema deberá enviar exactamente un aviso al correo anterior y exactamente uno al correo nuevo, sin generar otro aviso duplicado por la misma acción.
- **RF-08-CA-05:** Si el enlace expira o es invalidado antes de confirmar el cambio, el sistema deberá conservar el correo anterior, liberar la reserva del correo nuevo y no efectuar cambios parciales.
- **RF-08-CA-06:** Una cuenta no deberá poder cambiar el correo, rol o estado de otra cuenta mediante esta función.
- **RF-08-CA-07:** Mientras exista un cambio de correo pendiente para una cuenta, el sistema deberá mantener como máximo un enlace vigente; una solicitud nueva deberá invalidar inmediatamente el enlace anterior, liberar la reserva anterior y reservar el nuevo correo sin cambiar todavía el correo registrado.
- **RF-08-CA-08:** Si se procesan simultáneamente dos solicitudes de cambio de correo para la misma cuenta, el sistema deberá dejar como máximo un enlace vigente y conservar el correo actual hasta que uno válido sea confirmado.

### RF-09 — Desactivar y reemplazar la cuenta de personal

**Criterios de aceptación EARS:**

- **RF-09-CA-01:** Cuando el propietario desactive la cuenta de personal, el sistema deberá cerrar inmediatamente sus sesiones, invalidar todos sus enlaces pendientes —incluidos invitación, recuperación de contraseña, restablecimiento forzado, cambio de correo y reemplazo del segundo factor— e impedir nuevos accesos.
- **RF-09-CA-02:** Cuando una cuenta de personal esté desactivada, el sistema deberá conservar la asociación necesaria con su historial administrativo durante el plazo de conservación de dicho historial.
- **RF-09-CA-03:** Cuando se cumplan 12 meses desde el último evento asociado con una cuenta de personal desactivada, el sistema deberá eliminar su correo y cualquier otro dato identificable que ya no sea necesario, sin alterar los conteos no identificables permitidos.
- **RF-09-CA-04:** Una cuenta de personal no deberá poder activar, desactivar, invitar, reemplazar ni cambiar el rol de ninguna cuenta.
- **RF-09-CA-05:** El propietario no deberá poder reactivar una cuenta de personal desactivada; para autorizar nuevamente a esa persona deberá emitir una nueva invitación.
- **RF-09-CA-06:** Cuando se desactive la cuenta de personal, el sistema deberá invalidar su configuración de verificación en dos pasos y todos sus códigos de recuperación, conservando únicamente la asociación mínima requerida con el historial durante el plazo aplicable.

### RF-10 — Autorizar operaciones administrativas

**Criterios de aceptación EARS:**

- **RF-10-CA-01:** Mientras una sesión de propietario sea válida, el sistema deberá permitirle realizar todas las operaciones administrativas definidas en las especificaciones 001 y 002.
- **RF-10-CA-02:** Mientras una sesión de personal sea válida, el sistema deberá permitirle consultar, crear, modificar y cancelar citas; marcar resultados; reenviar códigos privados y reintentar notificaciones fallidas de citas únicamente a los contactos registrados y sin mostrar el código privado; y crear, editar o eliminar bloqueos de disponibilidad conforme a la especificación 001.
- **RF-10-CA-03:** Mientras una sesión corresponda al personal, el sistema deberá impedir crear, editar, activar o desactivar servicios y precios.
- **RF-10-CA-04:** Mientras una sesión corresponda al personal, el sistema deberá impedir gestionar cuentas, roles, configuración de autenticación ajena o historial administrativo.
- **RF-10-CA-05:** Cuando una sesión intente ejecutar una operación no permitida para su rol, el sistema deberá negarla sin cambios parciales y registrar el intento.

### RF-11 — Historial administrativo

**Criterios de aceptación EARS:**

- **RF-11-CA-01:** Cuando ocurra un inicio de sesión correcto o fallido, un bloqueo o cierre de sesión, una activación, invitación o desactivación de cuenta, un cambio o recuperación de contraseña, correo o segundo factor, el sistema deberá registrar la cuenta responsable cuando esté identificada, la acción, el resultado, la fecha y la hora.
- **RF-11-CA-02:** El historial no deberá copiar nombres, teléfonos, correos ni otros datos personales de clientas, ni almacenar contraseñas, códigos temporales, códigos de recuperación, enlaces secretos o códigos privados de citas.
- **RF-11-CA-03:** Mientras una sesión de propietario sea válida, el sistema deberá permitir consultar el historial y filtrar por cuenta, tipo de acción y periodo.
- **RF-11-CA-04:** Mientras una sesión corresponda al personal, el sistema deberá impedir consultar el historial.
- **RF-11-CA-05:** Ninguna función ordinaria deberá permitir editar o eliminar eventos individuales del historial.
- **RF-11-CA-06:** Hasta cumplirse 12 meses desde cada evento, el sistema deberá conservarlo disponible para el propietario.
- **RF-11-CA-07:** Cuando un evento cumpla 12 meses, el sistema deberá eliminarlo automáticamente junto con las asociaciones identificables que ya no sean necesarias.
- **RF-11-CA-08:** Cuando una cuenta administrativa cree, modifique o cancele una cita; registre su resultado; reenvíe su código privado; cree, modifique o elimine un bloqueo; cree, modifique, active o desactive un servicio; o intente una operación rechazada por falta de permisos, el sistema deberá registrar la cuenta responsable, la acción, el resultado, la fecha, la hora y la referencia interna del elemento afectado.
- **RF-11-CA-09:** Cuando una cuenta administrativa únicamente consulte, busque, filtre, abra una sección o cambie de pantalla, el sistema no deberá crear un evento en el historial por esa acción ordinaria.

### RF-12 — Avisos de seguridad

**Criterios de aceptación EARS:**

- **RF-12-CA-01:** Cuando cambien correctamente la contraseña o la configuración de verificación en dos pasos de una cuenta, el sistema deberá enviar un aviso al correo registrado. Cuando cambie el correo, deberá aplicar únicamente los dos avisos definidos en RF-08-CA-04 y no deberá enviar un aviso adicional por esta regla.
- **RF-12-CA-02:** Cuando una cuenta sea bloqueada temporalmente por intentos fallidos, el sistema deberá enviar un aviso a la persona titular de la cuenta.
- **RF-12-CA-03:** Cuando la cuenta de personal sea invitada, activada, bloqueada o desactivada, el sistema deberá enviar un aviso al propietario.
- **RF-12-CA-04:** Mientras una cuenta esté desactivada o temporalmente bloqueada, el sistema deberá impedir nuevos inicios de sesión aunque falle el envío del aviso.
- **RF-12-CA-05:** Si un aviso de seguridad no puede enviarse después de completar una acción, el sistema deberá conservar la acción, registrar el fallo y no revelar detalles internos.
- **RF-12-CA-06:** Los avisos de seguridad no deberán incluir contraseñas, códigos temporales, códigos de recuperación, enlaces secretos completos ni datos personales de clientas.
- **RF-12-CA-07:** Si falla el envío de un enlace de activación inicial, recuperación de contraseña, cambio de correo o reemplazo del segundo factor, el sistema deberá invalidar inmediatamente el enlace cuyo envío falló, no deberá considerar completada la acción y deberá conservar el estado seguro anterior: propietario inactivo, contraseña vigente, correo anterior o segundo factor anterior, según corresponda; si era un cambio de correo, también deberá liberar la reserva del correo nuevo.
- **RF-12-CA-08:** Cuando el fallo de envío provenga de una solicitud pública, el sistema deberá conservar la respuesta genérica; cuando la acción haya sido iniciada mediante un acceso identificado y autorizado, deberá informar a esa persona que el correo no pudo enviarse.
- **RF-12-CA-09:** Cuando falle cualquier envío de enlace, el sistema deberá registrar el fallo sin almacenar el enlace completo y permitir una nueva solicitud; el enlace nuevo deberá ser distinto del enlace fallido, invalidar cualquier otro enlace anterior del mismo propósito y comenzar con su plazo completo.
- **RF-12-CA-10:** Si falla el envío de un restablecimiento forzado de contraseña de la cuenta de personal, el sistema deberá invalidar inmediatamente el enlace cuyo envío falló, conservar la contraseña anterior inutilizable e informar al propietario para que pueda emitir un enlace nuevo.

## Requisitos no funcionales

### RNF-01 — Seguridad por defecto

- Toda entrada externa debe tratarse como no confiable y validarse.
- Las contraseñas, secretos de verificación, códigos de recuperación, sesiones y enlaces de un solo uso deben protegerse como secretos y nunca registrarse en texto legible; una clave de verificación solo puede mostrarse durante su configuración no confirmada y nunca después de activarse.
- Todo enlace temporal de activación, invitación, recuperación, cambio de correo o reemplazo de seguridad debe contener un identificador generado con al menos 128 bits de aleatoriedad criptográfica y no debe incorporar correos, nombres ni otros datos personales.
- Los errores de autenticación y recuperación no deben permitir enumerar cuentas ni revelar detalles internos.
- Toda autorización debe comprobarse en cada operación y no depender únicamente de ocultar opciones en la interfaz.
- Los accesos de inicio de sesión, recuperación de contraseña y solicitud de reemplazo del segundo factor deben compartir un máximo de 20 solicitudes por dirección IP dentro de cualquier ventana móvil de 15 minutos.
- Las operaciones administrativas autenticadas deben aceptar como máximo 120 solicitudes por cuenta dentro de cualquier ventana móvil de 1 minuto.
- Las acciones que provoquen mensajes de seguridad iniciados por una cuenta o relacionados con ella —invitación y reenvío de invitación, recuperación o restablecimiento forzado de contraseña, cambio de correo y reemplazo del segundo factor— deben aceptar como máximo 10 solicitudes por cuenta administrativa dentro de cualquier ventana móvil de 15 minutos.
- Las operaciones administrativas que provoquen notificaciones de citas —crear, modificar, cancelar, reenviar el código privado o reintentar manualmente una notificación fallida— deben aceptar como máximo 30 solicitudes por cuenta administrativa dentro de cualquier ventana móvil de 15 minutos.
- Cada acción deberá contar una sola vez para su límite aunque intente enviar mensajes por más de un canal.
- Los avisos automáticos de seguridad producidos por un evento ya confirmado y los recordatorios automáticos de citas definidos en la spec 001 no deberán contar para estos límites ni dejar de enviarse por haberlos alcanzado.
- Cuando una solicitud supere cualquiera de los límites aplicables, el sistema deberá rechazarla sin enviar mensajes, ejecutar operaciones ni revelar detalles internos; si coinciden varios límites, deberá aplicar el más restrictivo.
- Los límites de volumen deben funcionar de forma independiente del bloqueo temporal por intentos de autenticación fallidos.
- Ninguna credencial predeterminada, contraseña compartida ni mecanismo público de omisión está permitido.

### RNF-02 — Integridad y concurrencia

- Los límites de cuentas, cambios de estado, consumo de enlaces, consumo de códigos y creación de sesiones deben protegerse contra operaciones concurrentes.
- Una operación rechazada no debe dejar cambios parciales.
- Dos usos concurrentes del mismo enlace o código de recuperación deben permitir como máximo un resultado exitoso.

### RNF-03 — Privacidad y mínimo privilegio

- Cada cuenta debe acceder únicamente a las funciones de su rol.
- El historial debe contener solo la información mínima definida en RF-11.
- Las notificaciones deben limitarse a información de seguridad necesaria.
- Las cuentas desactivadas y los eventos vencidos no deben conservar datos identificables fuera de los plazos definidos.

### RNF-04 — Idioma y tiempo

- Todo contenido visible para usuarios de BeautyHub debe presentarse en español.
- Los plazos, bloqueos, expiraciones y registros de tiempo deben evaluarse de forma consistente en `America/Mexico_City`.

### RNF-05 — Adaptabilidad, accesibilidad y compatibilidad

- Toda interfaz de autenticación y administración incluida en esta spec debe ser comprensible y completamente utilizable mediante un diseño fluido desde 320 píxeles CSS de ancho en adelante.
- Ninguna página debe presentar desplazamiento horizontal general, contenido o funciones ocultos o perdidos ni controles superpuestos. Una tabla administrativa puede usar desplazamiento horizontal dentro de su propio contenedor solo cuando sea indispensable y debe conservar todas sus acciones utilizables.
- El texto debe ser legible sin obligar a ampliar la página; el sistema no debe impedir el zoom del navegador y los controles deben poder utilizarse cómodamente mediante una pantalla táctil.
- Cada campo debe tener una etiqueta explícita y cada error debe mostrarse cerca del campo correspondiente y estar asociado con él para tecnologías de asistencia.
- Todas las funciones deben poder operarse con teclado, el foco debe ser perceptible, la estructura y los nombres accesibles deben permitir navegación básica con lector de pantalla y ningún significado debe depender únicamente del color.
- La compatibilidad objetivo comprende Chrome en Android, Safari en iPhone y Chrome, Edge y Firefox de escritorio en su versión estable vigente y la versión principal inmediatamente anterior al momento de publicar.
- Los recorridos principales deben superar comprobaciones automatizadas de adaptabilidad y accesibilidad en tamaños representativos desde 320 píxeles CSS. Antes de publicar, la autenticación y administración deben superar además una comprobación manual en al menos un dispositivo Android y un iPhone reales.

## Casos límite

- Una quinta autenticación fallida dentro de 15 minutos activa el bloqueo; cuatro no lo activan.
- Cinco fallos combinados entre inicio de sesión y comprobaciones de contraseña actual, código temporal o código de recuperación activan el mismo bloqueo; no existen contadores separados que permitan continuar probando en otra función.
- Un mismo envío con contraseña y código incorrectos cuenta como un solo fallo, no como dos.
- Un inicio de sesión completo y correcto borra los fallos anteriores de la cuenta; completar correctamente una operación sensible dentro de una sesión ya abierta no los borra.
- Las primeras 20 solicitudes combinadas de inicio de sesión, recuperación de contraseña o reemplazo del segundo factor desde una dirección IP dentro de 15 minutos están permitidas; la solicitud 21 se rechaza.
- Las primeras 120 operaciones administrativas autenticadas de una cuenta dentro de 1 minuto están permitidas; la operación 121 se rechaza.
- Las primeras 10 acciones de seguridad de una cuenta que provoquen mensajes dentro de 15 minutos están permitidas; la acción 11 se rechaza.
- Las primeras 30 operaciones administrativas de citas de una cuenta que provoquen notificaciones dentro de 15 minutos —incluidos los reintentos manuales fallidos de citas— están permitidas; la operación 31 se rechaza antes de ejecutar la acción.
- Una operación que intenta WhatsApp y correo cuenta como una sola acción para el límite aplicable.
- Cuando la ventana móvil deje de contener el número máximo de solicitudes aplicable, el sistema vuelve a aceptar solicitudes.
- Un intento exactamente al terminar los 15 minutos de bloqueo está permitido.
- Los intentos realizados durante el bloqueo no extienden su duración.
- Restablecer correctamente la contraseña durante un bloqueo no lo elimina: la cuenta espera hasta que termine el periodo original de 15 minutos.
- Un bloqueo por intentos fallidos no cierra una sesión legítima ya abierta.
- Una sesión abierta durante el bloqueo puede gestionar la agenda según su rol, pero no cambiar contraseña, correo o segundo factor hasta que termine el bloqueo.
- Un nuevo inicio de sesión válido cierra la sesión anterior de la misma cuenta.
- Una contraseña de 12 caracteres se rechaza si figura en la lista vigente de valores comunes o comprometidos; una frase que cumple la longitud y no figura en ella no requiere símbolos, números o mayúsculas forzosos.
- Una sesión se cierra al alcanzar exactamente 30 minutos sin actividad o exactamente 8 horas desde su creación.
- Las actualizaciones o solicitudes automáticas en segundo plano no prolongan una sesión administrativa.
- Cambiar contraseña, correo o verificación en dos pasos cierra todas las sesiones de la cuenta.
- Completar cualquier cambio de contraseña, correo, segundo factor o códigos de recuperación invalida todos los enlaces de seguridad anteriores de la cuenta, descarta configuraciones incompletas y libera las reservas de correo que ya no correspondan.
- Desactivar la cuenta de personal cierra sus sesiones e invalida sus enlaces pendientes inmediatamente.
- Ningún enlace, código de recuperación o segundo factor perteneciente a una cuenta de personal desactivada puede volver a utilizarse; una autorización posterior requiere una cuenta nueva.
- Un enlace de invitación deja de funcionar al usarse, expirar, cancelarse o ser reemplazado.
- El fallo de entrega de una invitación invalida el enlace fallido, conserva la cuenta pendiente e inactiva y permite al propietario reenviarla o cancelarla.
- Un enlace de recuperación deja de funcionar al usarse, expirar o ser reemplazado.
- Un restablecimiento forzado invalida inmediatamente la contraseña anterior; si su enlace vence o es sustituido, la cuenta de personal continúa sin acceso hasta completar uno nuevo y válido.
- Un enlace emitido a las 10:00 con duración de 30 minutos funciona antes de las 10:30 y está vencido a las 10:30 exactas; una invitación de 24 horas sigue la misma regla al cumplirse exactamente ese plazo.
- Dos intentos simultáneos de consumir el mismo enlace o código permiten un solo éxito.
- Introducir un código de recuperación incorrecto cuenta como fallo, pero no consume ni invalida ningún código válido.
- Una solicitud que contiene un código temporal o de recuperación correcto y otra credencial incorrecta cuenta como un fallo, pero no consume el código correcto ni revela cuál credencial falló.
- Ningún identificador de enlace temporal contiene datos personales o menos de 128 bits de aleatoriedad criptográfica.
- Los diez códigos de recuperación solo se muestran al generarse; después no pueden volver a consultarse.
- El código QR o la clave secreta de la aplicación de autenticación solo se muestra durante la configuración no confirmada; una vez activada no puede volver a consultarse.
- Un código de recuperación contiene 16 caracteres útiles y puede introducirse con letras mayúsculas o minúsculas, con o sin los guiones visuales y con espacios exteriores; cualquier otro carácter o espacio interno se rechaza, y `I`, `O`, `0` y `1` nunca aparecen en códigos generados.
- Regenerar códigos de recuperación exige la contraseña actual y un código temporal válido; no puede autorizarse con otro código de recuperación.
- Regenerarlos correctamente invalida todos los anteriores, muestra una sola vez los diez nuevos, cierra la sesión y envía un aviso sin secretos; un intento fallido conserva todos los códigos anteriores.
- Un código temporal del periodo actual o del inmediatamente anterior o posterior puede aceptarse; uno fuera de esa tolerancia debe rechazarse.
- Dos intentos de utilizar para la misma cuenta un código temporal ya aceptado permiten un solo uso exitoso.
- Emitir un nuevo enlace de activación inicial invalida inmediatamente el anterior.
- Dos intentos concurrentes de activar al propietario permiten una sola cuenta activa y ninguna configuración parcial.
- Después de activar al propietario, el proceso inicial no puede volver a utilizarse.
- Un correo que solo difiere por mayúsculas, minúsculas o espacios externos se considera el mismo correo.
- Un correo con espacios internos, más de un signo `@`, una parte vacía, puntos consecutivos antes de `@`, caracteres no permitidos, un dominio sin punto o una extensión que no contenga al menos dos letras debe rechazarse.
- Un correo utilizado por una cuenta pendiente o activa, o reservado por otro cambio pendiente, no puede reservarse para una invitación, activación o cambio de correo diferente.
- Si dos operaciones intentan reservar simultáneamente el mismo correo normalizado, solamente una puede continuar; al confirmar cualquier enlace se comprueba nuevamente la disponibilidad antes de modificar la cuenta.
- Solicitar un segundo cambio de correo invalida el enlace anterior; dos solicitudes concurrentes dejan como máximo un enlace vigente.
- Un cambio de correo confirmado envía un aviso al correo anterior y uno al nuevo; no envía un tercer aviso ni duplica el mensaje al correo nuevo.
- Perder el segundo factor y todos los códigos de recuperación permite reemplazarlo únicamente con la contraseña actual y un enlace enviado al correo registrado.
- Solicitar el reemplazo con un correo inexistente, una cuenta no disponible o una contraseña incorrecta produce la misma respuesta genérica y no envía ningún enlace.
- Perder simultáneamente la contraseña, el segundo factor y todos los códigos de recuperación no permite usar el correo como único medio de recuperación automática.
- Una contraseña recién establecida por recuperación no permite solicitar el reemplazo del segundo factor hasta completar un inicio de sesión con el factor anterior o un código de recuperación.
- Emitir un nuevo enlace para reemplazar el segundo factor invalida inmediatamente el anterior.
- Abrir un enlace de reemplazo no invalida el factor anterior; la sustitución, los códigos de recuperación nuevos y el cierre de sesiones ocurren atómicamente solo después de confirmar que el factor nuevo funciona.
- Si la configuración nueva se interrumpe, falla o vence, se descarta y el factor anterior, sus códigos de recuperación y las sesiones existentes permanecen sin cambios.
- El fallo de un aviso por correo no revierte una acción de seguridad ya confirmada.
- El fallo al enviar un enlace lo invalida inmediatamente, no completa la acción pendiente y conserva el estado anterior, salvo que un restablecimiento forzado ya haya invalidado la contraseña de la cuenta de personal.
- El personal puede operar todas las citas de ambas sucursales, incluido reintentar notificaciones fallidas únicamente a los contactos registrados y sin ver el código privado, pero no puede gestionar servicios, precios, cuentas ni historial.
- Las operaciones administrativas que cambian citas, servicios, bloqueos, cuentas o seguridad se registran; las consultas, búsquedas, filtros y cambios de pantalla ordinarios no.
- Una referencia interna de una cita retirada no debe permitir recuperar sus datos personales desde el historial.
- Al vencer 12 meses, un evento deja de ser consultable y se eliminan sus asociaciones identificables innecesarias.

## Fuera de alcance

- Cuentas, inicio de sesión o recuperación de acceso para clientas.
- Más de una cuenta de propietario o más de una cuenta de personal pendiente o activa.
- Registro público de cuentas administrativas.
- Inicio de sesión mediante redes sociales, proveedores empresariales o identidad federada.
- Autenticación biométrica y dispositivos recordados como confiables.
- Passkeys y códigos de segundo factor enviados por correo, SMS o WhatsApp.
- Permisos personalizados distintos de los roles propietario y personal.
- Reactivación de cuentas de personal desactivadas.
- Recuperación automática cuando se pierden simultáneamente la contraseña, el segundo factor y todos los códigos de recuperación.
- Acceso a datos conservados de forma individual por obligaciones legales; cualquier permiso de esta naturaleza deberá definirse después de la revisión jurídica pendiente de la especificación 001 y no se concede a ningún rol mediante esta spec.
- Selección de proveedores, arquitectura, dependencias o mecanismos técnicos concretos.

## Criterios de finalización

- Todos los requisitos funcionales cuentan con criterios EARS verificables.
- Las pruebas automatizadas cubren autenticación, códigos temporales de 6 dígitos y periodos de 30 segundos, compatibilidad sin depender de una marca, la tolerancia máxima de un periodo, la imposibilidad de reutilizar códigos temporales, el consumo atómico de códigos temporales y de recuperación únicamente cuando toda la solicitud sea correcta, el contador compartido de solicitudes rechazadas por contraseña, código temporal o código de recuperación, el conteo único cuando fallen varias credenciales en una misma solicitud, su eliminación únicamente después de un inicio de sesión correcto, la conservación de códigos válidos ante un código de recuperación incorrecto, las operaciones permitidas y rechazadas durante el bloqueo, y la expiración e invalidación de sesiones.
- Las pruebas cubren la creación inicial protegida del propietario, la expiración y sustitución de su enlace, la activación concurrente y el cierre permanente del proceso inicial.
- Las pruebas cubren invitaciones y recuperaciones válidas, vencidas, reutilizadas y consumidas de forma concurrente, el fallo de entrega y posterior reenvío o cancelación de invitaciones, los límites exactos de expiración de todos los enlaces temporales, la invalidación de todos los enlaces de seguridad anteriores después de cualquier cambio de credenciales, el descarte de configuraciones incompletas y la liberación de reservas de correo, el restablecimiento de contraseña durante un bloqueo que permanece activo y el restablecimiento forzado de la cuenta de personal con enlaces sustituidos o vencidos.
- Las pruebas cubren límites de cuentas, validación exacta, unicidad y cambio de correo, reserva y revalidación del correo al confirmar enlaces, dos operaciones concurrentes que intentan ocupar el mismo correo, sustitución y concurrencia de enlaces pendientes, longitud y lista de bloqueo de contraseñas sin reglas artificiales de composición, pegado y autocompletado, la generación de diez códigos de recuperación de 16 caracteres mostrados una sola vez, su validación sin distinguir mayúsculas y minúsculas, con guiones opcionales y espacios exteriores, el rechazo de otros caracteres o espacios internos, su uso individual, la regeneración autorizada únicamente con contraseña y código temporal, la conservación de códigos anteriores ante un fallo, la invalidación de los anteriores, el cierre de sesión y el aviso tras una regeneración correcta, y la desactivación inmediata de sesiones, enlaces y factores de la cuenta de personal.
- Las pruebas de autorización demuestran que el personal puede operar citas, reintentar sus notificaciones fallidas bajo las restricciones de la spec 001 y gestionar bloqueos, pero no servicios, precios, cuentas o historial.
- Las pruebas demuestran que una persona no autenticada no puede acceder a ninguna operación administrativa ni dato privado.
- Las pruebas cubren la creación para cada tipo de evento incluido, la ausencia de eventos para consultas ordinarias, la consulta, inmutabilidad, minimización y eliminación a 12 meses del historial.
- Las pruebas cubren los destinatarios y cantidades exactas de los avisos de seguridad —incluidos los dos avisos sin duplicados al cambiar el correo— y comprueban que su fallo no revierte acciones confirmadas; también cubren fallos de entrega de cada tipo de enlace, su invalidación inmediata, respuestas públicas genéricas, estados conservados y reenvíos que generan enlaces distintos e invalidan cualquier enlace anterior.
- Las verificaciones de seguridad confirman que contraseñas, secretos, códigos, sesiones y enlaces no aparecen en respuestas no autorizadas, historial ni registros técnicos, que el código QR o clave del segundo factor no puede consultarse después de su activación y que todos los identificadores de enlaces temporales cumplen el mínimo de 128 bits sin incorporar datos personales.
- Las pruebas cubren el reemplazo atómico del segundo factor con una sesión o mediante contraseña y correo, la confirmación obligatoria del factor nuevo antes de invalidar el anterior, la conservación de factor, códigos y sesiones ante procesos interrumpidos o fallidos, la generación de códigos nuevos y el cierre de sesiones únicamente al completar el cambio, enlaces vencidos, sustituidos o reutilizados, correos inexistentes, cuentas pendientes, desactivadas o bloqueadas, contraseñas recién recuperadas y solicitudes sin contraseña válida, sin diferencias observables en sus respuestas de rechazo; también demuestran que una autenticación con el factor anterior o un código de recuperación elimina únicamente la restricción correspondiente.
- Las pruebas cubren los cuatro límites de volumen, sus ventanas móviles, sus valores exactos, el conteo de reintentos manuales de notificaciones de citas, el conteo único de operaciones con dos canales, la continuidad de avisos automáticos de seguridad y recordatorios automáticos de citas, y la aplicación del límite más restrictivo cuando coincidan.
- Las pruebas de interfaz cubren desde 320 píxeles CSS los flujos de autenticación y administración sin desplazamiento horizontal general, pérdida de contenido ni controles superpuestos; comprueban teclado, foco, etiquetas, errores asociados, zoom, significado independiente del color y ausencia de infracciones detectadas automáticamente en los recorridos principales.
- Antes de publicar, se documenta una comprobación manual satisfactoria de autenticación y administración en al menos un Android y un iPhone reales, además de la matriz de navegadores objetivo.
- Todas las verificaciones del proyecto y pruebas existentes pasan.
- El responsable del proyecto revisa, comprende y aprueba explícitamente esta spec antes de convertirla en activa.

## Dudas abiertas

- Ninguna duda funcional conocida dentro del alcance de esta especificación.
