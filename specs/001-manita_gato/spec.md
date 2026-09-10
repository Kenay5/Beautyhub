# Especificación 001 — Gestión inicial de citas y servicios

**Estado:** Activa; aprobada explícitamente por el responsable del proyecto el 9 de septiembre de 2026.

## Contexto y objetivo

BeautyHub necesita una primera funcionalidad que permita a las clientas reservar y gestionar citas sin crear una cuenta. El acceso de la clienta se basa en un código privado asociado con cada cita.

El negocio trabaja con un solo profesional en dos sucursales, Chiconcuac y Texcoco. La agenda debe considerar la duración de los servicios, los traslados entre sucursales y los periodos de indisponibilidad, evitando cualquier conflicto.

El objetivo es permitir la creación, consulta, modificación y cancelación de citas, así como proporcionar al propietario y al personal autenticados las operaciones autorizadas para gestionar citas, servicios y disponibilidad.

La autenticación administrativa es una dependencia definida fuera de esta spec; las operaciones administrativas de este alcance solo pueden ejecutarse después de una autenticación y autorización válidas.

## Usuarios

### Clienta

- No tiene una cuenta ni inicia sesión.
- Puede reservar una o varias citas futuras.
- Consulta su cita mediante un código privado.
- Modifica o cancela su cita mediante el código privado y el número telefónico registrado.

### Propietario y personal

- Cada persona debe autenticarse y estar autorizada conforme a la especificación 002.
- Ambos roles consultan y gestionan todas las citas de ambas sucursales sin utilizar códigos privados.
- Ambos roles gestionan periodos de indisponibilidad y marcan el resultado final de las citas atendidas.
- Únicamente el propietario crea, edita, activa o desactiva servicios y precios.
- Cuando esta especificación utiliza el término administrador, sus permisos deben interpretarse conforme al rol definido en la especificación 002.

## Historias de usuario

### HU-01 — Reservar una cita

Como clienta, quiero elegir un servicio, una sucursal, una fecha y un horario disponible para reservar una cita con el profesional.

### HU-02 — Consultar una cita

Como clienta, quiero consultar de forma privada los datos y el estado de mi cita para verificar mi reservación.

### HU-03 — Gestionar una cita

Como clienta, quiero modificar o cancelar mi cita con anticipación para ajustar mi reservación sin contactar al administrador.

### HU-04 — Gestionar la agenda

Como administrador, quiero consultar, crear, modificar y cancelar citas para mantener actualizada la agenda de ambas sucursales.

### HU-05 — Gestionar servicios

Como propietario, quiero mantener el catálogo de servicios y su disponibilidad por sucursal para ofrecer únicamente opciones vigentes.

### HU-06 — Gestionar disponibilidad y resultados

Como administrador, quiero bloquear periodos no disponibles y registrar si una cita fue completada o si la clienta no asistió.

### HU-07 — Recibir un recordatorio

Como clienta, quiero recibir un recordatorio antes de mi cita para reducir el riesgo de olvidarla.

## Reglas generales

- La zona horaria oficial es `America/Mexico_City`.
- Las sucursales disponibles son Chiconcuac y Texcoco.
- Existe un solo profesional para ambas sucursales.
- El horario permitido para iniciar citas es de lunes a domingo, de 09:00 a 19:00, inclusive.
- Los horarios de inicio se ofrecen en intervalos de 15 minutos.
- Una cita puede terminar después de las 19:00.
- No existe una hora máxima de finalización, pero ningún servicio puede durar más de 10 horas.
- El periodo de 13:00 a 14:00 no bloquea la agenda; una cita puede comenzar o continuar durante ese horario.
- Deben existir 5 minutos de separación entre citas consecutivas en la misma sucursal.
- Deben existir 25 minutos de separación entre citas consecutivas en sucursales diferentes: 20 minutos de traslado y 5 minutos de tolerancia.
- La agenda es única: una cita en cualquier sucursal ocupa al único profesional e impide atender otra cita simultánea en cualquiera de las dos sucursales.
- La agenda se evalúa como una línea de tiempo continua, incluso cuando una cita atraviesa medianoche.
- Cada cita contiene un solo servicio.
- Una clienta puede tener varias citas futuras con el mismo número telefónico, siempre que la agenda permita cada reservación.
- Toda reservación debe ser realizada por una persona adulta. Una persona adulta puede reservar un servicio destinado a una persona menor de edad, pero la cita debe registrarse con el nombre y los datos de contacto de la persona adulta responsable; el MVP no recaba datos personales de la persona menor.
- Los estados de una cita son programada, cancelada, completada, no asistió y resultado no registrado.
- Los estados cancelada, completada, no asistió y resultado no registrado son finales.

## Requisitos funcionales

### RF-01 — Catálogo de servicios

Cada servicio debe contener nombre, descripción opcional, duración, precio, sucursales disponibles y estado activo o inactivo.

**Criterios de aceptación EARS:**

- **RF-01-CA-01:** Cuando el propietario autenticado y autorizado cree o edite un servicio, el sistema deberá exigir un nombre de 1 a 100 caracteres, una descripción opcional de hasta 250 caracteres, una duración mayor que cero y no mayor que 10 horas, un precio mayor que cero y al menos una sucursal.
- **RF-01-CA-02:** Cuando se proporcione el nombre o la descripción de un servicio, el sistema deberá retirar espacios externos, aceptar caracteres Unicode visibles —incluidos letras, números, espacios y puntuación— y rechazar caracteres de control; el nombre deberá conservar al menos un carácter.
- **RF-01-CA-03:** Cuando se cree o renombre un servicio, el sistema deberá rechazar nombres duplicados después de ignorar diferencias entre mayúsculas, minúsculas y espacios externos.
- **RF-01-CA-04:** Cuando se registre la duración, el sistema deberá aceptar únicamente múltiplos de 5 minutos.
- **RF-01-CA-05:** Cuando se registre el precio, el sistema deberá expresarlo en MXN, aceptar hasta dos decimales y rechazar valores iguales o menores que cero o mayores que $20,000.00 MXN.
- **RF-01-CA-06:** Mientras un servicio esté inactivo, el sistema deberá impedir que se seleccione para una cita nueva.
- **RF-01-CA-07:** Cuando un servicio se edite o desactive, el sistema deberá conservar en las citas existentes el nombre, duración, precio y sucursal acordados al reservar.
- **RF-01-CA-08:** Si una cita conserva un servicio posteriormente inactivo, el sistema deberá respetar la reservación original mientras no se cambie la fecha, el horario, la sucursal o el servicio.
- **RF-01-CA-09:** Cuando una cita con un servicio inactivo cambie la fecha, el horario, la sucursal o el servicio, el sistema deberá exigir la selección de un servicio activo y disponible en la sucursal elegida.

### RF-02 — Disponibilidad de la agenda

La disponibilidad debe considerar la jornada, el servicio, la sucursal, la agenda única del profesional, los tiempos de separación y los bloqueos administrativos.

**Criterios de aceptación EARS:**

- **RF-02-CA-01:** Cuando se consulten horarios de cualquier día de lunes a domingo, el sistema deberá ofrecer únicamente inicios en intervalos de 15 minutos entre las 09:00 y las 19:00, inclusive.
- **RF-02-CA-02:** Cuando se evalúe una reservación, el sistema deberá considerar la duración completa del servicio aunque termine después de las 19:00.
- **RF-02-CA-03:** Cuando una cita comience o continúe entre las 13:00 y las 14:00, el sistema deberá tratar ese periodo como disponible si no existe otro conflicto.
- **RF-02-CA-04:** Cuando dos citas consecutivas pertenezcan a la misma sucursal, el sistema deberá reservar al menos 5 minutos entre el final de una y el inicio de la siguiente.
- **RF-02-CA-05:** Cuando dos citas consecutivas pertenezcan a sucursales diferentes, el sistema deberá reservar al menos 25 minutos entre el final de una y el inicio de la siguiente.
- **RF-02-CA-06:** Si una cita solicitada se superpone con otra cita programada o incumple el tiempo de separación, el sistema deberá rechazarla.
- **RF-02-CA-07:** Mientras exista un bloqueo aplicable, el sistema deberá excluir el periodo bloqueado de la disponibilidad.
- **RF-02-CA-08:** Mientras una cita esté cancelada, completada, marcada como no asistió o como resultado no registrado, el sistema no deberá tratarla como una cita futura que ocupa disponibilidad.
- **RF-02-CA-09:** Cuando una cita atraviese medianoche, el sistema deberá impedir cualquier cita posterior hasta que termine y se cumpla la separación de 5 o 25 minutos correspondiente.
- **RF-02-CA-10:** Cuando se confirme cualquier operación que cambie disponibilidad, el sistema deberá volver a validar la agenda, bloqueos y vigencia del servicio con el estado más reciente.
- **RF-02-CA-11:** Si dos o más operaciones concurrentes intentan producir estados incompatibles en la agenda, el sistema deberá aceptar únicamente una combinación válida y rechazar las demás sin cambios parciales.
- **RF-02-CA-12:** Cuando se evalúe una cita o un bloqueo, el sistema deberá considerar ocupado su instante de inicio y libre su instante exacto de finalización; por lo tanto, una cita podrá comenzar exactamente cuando termine un bloqueo aplicable y un bloqueo podrá comenzar exactamente cuando termine una cita, siempre que no exista otro conflicto.
- **RF-02-CA-13:** Cuando se calcule el inicio más temprano entre dos citas, el sistema deberá sumar al final exacto de la primera los 5 minutos para la misma sucursal o los 25 minutos para sucursales diferentes y elegir el primer horario de inicio de 15 minutos que sea igual o posterior al resultado.

### RF-03 — Crear una cita

La clienta y el administrador pueden crear citas sujetas a las mismas reglas de disponibilidad. La anticipación mínima de 60 minutos se aplica únicamente a las reservaciones públicas; el administrador puede registrar una cita inmediata o una clienta que llegue sin cita.

Los datos obligatorios son nombre, apellido, número telefónico mexicano de 10 dígitos, correo electrónico, un servicio, sucursal, fecha y horario.

**Criterios de aceptación EARS:**

- **RF-03-CA-01:** Cuando se solicite una cita, el sistema deberá exigir nombre y apellido de 1 a 100 caracteres cada uno después de retirar espacios externos, aceptando letras Unicode, espacios internos, apóstrofos y guiones.
- **RF-03-CA-02:** Cuando se proporcione un teléfono, el sistema deberá retirar los espacios exteriores y permitir una parte nacional escrita con dígitos ASCII, espacios, guiones o paréntesis, precedida opcionalmente por el prefijo explícito `+52`. Después de retirar el prefijo permitido y los separadores, el sistema deberá aceptar únicamente un resultado de exactamente 10 dígitos ASCII y almacenarlo en ese formato; deberá rechazar cualquier otro prefijo internacional, letra, extensión, carácter o cantidad de dígitos.
- **RF-03-CA-03:** Cuando se solicite una cita, el sistema deberá retirar los espacios externos del correo y exigir, después de ese ajuste, entre 1 y 254 caracteres y exactamente un signo `@`. La parte anterior a `@` deberá contener únicamente letras ASCII, números o `.`, `_`, `%`, `+` y `-`; no podrá comenzar o terminar con punto ni contener dos puntos consecutivos. El dominio deberá contener al menos un punto y componerse de segmentos no vacíos con letras ASCII, números o guiones; cada segmento deberá comenzar y terminar con letra o número, y el segmento final deberá contener al menos dos letras. La validación no deberá distinguir mayúsculas de minúsculas.
- **RF-03-CA-04:** Cuando una clienta solicite una cita, el sistema deberá exigir la aceptación del aviso de privacidad, la autorización para usar sus datos de contacto en la gestión y notificación de la cita, y la declaración de que es una persona adulta y responsable de la reservación.
- **RF-03-CA-05:** Cuando un administrador solicite una cita para una clienta, el sistema deberá exigirle confirmar que los datos pertenecen a una persona adulta responsable, que le informó sobre el aviso de privacidad y que obtuvo su autorización.
- **RF-03-CA-06:** Cuando se solicite una cita, el sistema deberá aceptar exactamente un servicio activo disponible en la sucursal seleccionada.
- **RF-03-CA-07:** Cuando una clienta elija un servicio, el sistema deberá presentarle la lista de servicios activos de la sucursal y no permitir nombres escritos libremente.
- **RF-03-CA-08:** Cuando una clienta solicite públicamente una cita, el sistema deberá exigir un mínimo exacto de 60 minutos de anticipación y un máximo exacto de 90 periodos de 24 horas hacia el futuro, permitiendo ambos límites.
- **RF-03-CA-09:** Cuando una clienta utilice un número ya registrado en otras citas, el sistema deberá permitir una nueva cita si cumple las reglas de disponibilidad.
- **RF-03-CA-10:** Cuando la cita cumpla todas las reglas, el sistema deberá crearla con estado programada y conservar el nombre, duración y precio vigente del servicio.
- **RF-03-CA-11:** Cuando se confirme una cita, el sistema deberá generar automáticamente un código privado opaco, único, inmutable, sin datos personales y con al menos 128 bits de aleatoriedad criptográfica.
- **RF-03-CA-12:** Si la cita no cumple una regla de disponibilidad o validación, el sistema deberá rechazarla sin ocupar tiempo en la agenda.
- **RF-03-CA-13:** Cuando se cree una cita, el sistema deberá conservar como evidencia la versión del aviso de privacidad aceptado, la fecha y hora de aceptación, el origen público o administrativo de la reservación y la declaración de que quien reserva es una persona adulta responsable; si la reservación es administrativa, deberá asociar también la cuenta que confirmó la autorización.
- **RF-03-CA-14:** Cuando se publique una nueva versión del aviso de privacidad, el sistema deberá conservar identificable e inalterada cada versión anterior mientras exista evidencia de una aceptación asociada con ella.
- **RF-03-CA-15:** Cuando un administrador cree una cita, el sistema deberá permitir el primer inicio disponible que no sea anterior al momento de la solicitud, sin exigir 60 minutos de anticipación y manteniendo el máximo de 90 periodos de 24 horas, los intervalos de 15 minutos y todas las demás reglas de validación y disponibilidad.
- **RF-03-CA-16:** Antes de enviar una solicitud de confirmación, el sistema deberá asociarla con una referencia secreta generada automáticamente con al menos 128 bits de aleatoriedad criptográfica, sin incorporar nombre, teléfono, correo ni otros datos personales, y registrar el instante de su generación para que sea válida durante 24 horas.
- **RF-03-CA-17:** Si una solicitud presenta una referencia secreta vigente que ya confirmó una cita, el sistema deberá devolver el resultado original y el mismo código privado sin crear otra cita ni iniciar nuevos envíos de WhatsApp o correo.
- **RF-03-CA-18:** Si dos solicitudes con la misma referencia secreta se procesan simultáneamente, el sistema deberá crear como máximo una cita y devolver a ambas el mismo resultado confirmado.
- **RF-03-CA-19:** Si una solicitud no presenta la referencia secreta correspondiente, el sistema no deberá recuperar una confirmación mediante la coincidencia de nombre, teléfono, correo, fecha, horario u otros datos de la cita.
- **RF-03-CA-20:** Al cumplirse exactamente 24 horas desde la generación de una referencia secreta, el sistema deberá rechazar cualquier uso posterior de esa referencia sin crear una cita nueva ni recuperar una confirmación anterior; un nuevo intento de reservación deberá utilizar una referencia nueva.

### RF-04 — Confirmaciones y notificaciones

Las notificaciones de esta spec son exclusivamente transaccionales: creación, modificación, cancelación, un recordatorio previo y recuperación del código privado. Los datos de contacto no pueden utilizarse para publicidad, promociones, encuestas, perfiles comerciales ni otras finalidades secundarias durante este MVP.

**Criterios de aceptación EARS:**

- **RF-04-CA-01:** Cuando se cree una cita, el sistema deberá mostrar en la confirmación el código privado y el resumen de la cita.
- **RF-04-CA-02:** Cuando se cree, modifique o cancele una cita, el sistema deberá enviar la confirmación por WhatsApp al número registrado.
- **RF-04-CA-03:** Cuando se cree, modifique o cancele una cita, el sistema deberá enviar también la confirmación al correo registrado.
- **RF-04-CA-04:** Cuando se envíe una confirmación, el sistema deberá incluir servicio, fecha, horario, sucursal, duración, estado y precio acordado en MXN.
- **RF-04-CA-05:** Cuando se notifique la creación de una cita, el sistema deberá incluir el código privado en los mensajes de WhatsApp y correo.
- **RF-04-CA-06:** Cuando se cree una cita o se recupere la misma confirmación mediante el reintento permitido por RF-03-CA-17, el sistema deberá mostrar el código privado únicamente en la pantalla correspondiente a esa confirmación y no en ninguna otra respuesta pública.
- **RF-04-CA-07:** Cuando se modifique o cancele una cita, el sistema deberá mostrar el resultado confirmado sin volver a revelar el código privado.
- **RF-04-CA-08:** Si WhatsApp, correo o ambos canales fallan después de completar una operación, el sistema deberá conservar la operación y mostrar al usuario que realizó la operación qué canales fallaron, sin revelar detalles internos.
- **RF-04-CA-09:** Si el teléfono no tiene WhatsApp o el mensaje no puede entregarse, el sistema deberá tratarlo como un fallo de notificación y mantener el envío obligatorio por correo.
- **RF-04-CA-10:** Cuando se recupere en pantalla una confirmación ya creada mediante RF-03-CA-17, el sistema deberá conservar el resultado de los intentos de entrega originales y no deberá reenviar automáticamente ninguna notificación; cualquier reenvío posterior del código deberá realizarse mediante la operación administrativa de RF-12.
- **RF-04-CA-11:** Cuando un proveedor acepte una solicitud de envío, el sistema deberá registrar el canal como aceptado por el proveedor y no como entregado; solo deberá registrarlo como entregado cuando el proveedor confirme la entrega.
- **RF-04-CA-12:** Si un proveedor informa un fallo después de haber aceptado el envío, el sistema deberá actualizar el canal a fallido, conservar sin cambios la operación principal y permitir que un administrador autenticado y autorizado reintente manualmente esa notificación al contacto actualmente registrado.
- **RF-04-CA-13:** Cuando un administrador reintente una notificación fallida, el sistema deberá conservar el contenido y las reglas de revelación del evento original, no generar un código nuevo, no mostrar el código al administrador y registrar el nuevo intento de forma auditable. Una notificación ordinaria de modificación o cancelación no deberá incluir el código; el reenvío exigido al corregir teléfono o correo deberá usar el mismo código conforme a RF-06-CA-09.
- **RF-04-CA-14:** Cuando se confirme una cita pública o administrativa y falten más de 24 horas para su inicio, el sistema deberá programar exactamente un recordatorio para el instante que corresponda a 24 horas antes de ese inicio.
- **RF-04-CA-15:** Cuando se confirme una modificación que cambie la fecha o el horario de una cita programada, el sistema deberá invalidar cualquier recordatorio pendiente del horario anterior y, si faltan más de 24 horas para el nuevo inicio, programar exactamente un recordatorio nuevo para el instante correspondiente.
- **RF-04-CA-16:** Si al confirmar la creación o el cambio de fecha u horario faltan exactamente 24 horas o menos para el inicio, el sistema no deberá programar ni enviar un recordatorio adicional para ese horario.
- **RF-04-CA-17:** Cuando llegue el instante programado del recordatorio, el sistema deberá comprobar nuevamente que la cita continúa programada, conserva la misma fecha y horario y tiene más de 60 minutos restantes; si cumple esas condiciones, deberá iniciar un intento independiente por WhatsApp y otro por correo dirigidos a los contactos vigentes de la cita.
- **RF-04-CA-18:** Cuando se prepare un recordatorio, el sistema deberá incluir servicio, fecha, horario, sucursal, duración y precio acordado en MXN, y no deberá incluir el código privado ni un enlace o dato que permita recuperarlo.
- **RF-04-CA-19:** Si el sistema no estaba disponible en el instante programado, al recuperarse deberá intentar el recordatorio únicamente si todavía faltan más de 60 minutos para la cita; si faltan exactamente 60 minutos o menos, deberá marcarlo como omitido de forma definitiva y no enviarlo posteriormente.
- **RF-04-CA-20:** Cuando una cancelación o una modificación de fecha u horario se confirme antes de que el sistema registre atómicamente el inicio del envío del recordatorio, el sistema deberá impedir el envío del recordatorio cancelado o correspondiente al horario anterior mediante una comprobación final protegida contra concurrencia.
- **RF-04-CA-21:** Si el sistema ya registró atómicamente el inicio del envío antes de confirmarse una modificación o cancelación concurrente, el recordatorio podrá ser aceptado o entregado por el proveedor y el sistema no deberá intentar retirarlo ni revertir ninguna operación; deberá enviar después la notificación ordinaria de la modificación o cancelación confirmada.
- **RF-04-CA-22:** Cuando falle un canal del recordatorio, el sistema deberá conservar por separado el resultado de ambos canales y no deberá reintentarlo automáticamente; un canal aceptado o entregado no deberá volver a enviarse como parte del recordatorio.
- **RF-04-CA-23:** Mientras falten más de 60 minutos para la cita, el propietario o el personal autenticado y autorizado podrán reintentar manualmente únicamente un canal fallido del recordatorio al contacto vigente, con un máximo de tres reintentos por canal y recordatorio y al menos cinco minutos entre reintentos; cada reintento deberá contar para el límite administrativo de notificaciones de citas definido en la spec 002.
- **RF-04-CA-24:** Si dos procesos intentan enviar simultáneamente el mismo recordatorio inicial o efectuar el mismo reintento permitido, el sistema deberá aceptar como máximo uno por cita, horario y canal, sin crear entregas duplicadas ni superar el máximo aprobado.
- **RF-04-CA-25:** Si un recordatorio se omite, falla o agota sus reintentos, el sistema deberá conservar sin cambios la cita y su estado y registrar únicamente resultados sanitizados y auditables.

### RF-05 — Consultar una cita como clienta

La consulta pública requiere únicamente el código privado.

**Criterios de aceptación EARS:**

- **RF-05-CA-01:** Cuando una clienta proporcione un código privado válido y vigente, el sistema deberá mostrar servicio, fecha, horario, sucursal, duración, precio acordado, estado y datos de contacto ocultos conforme a RF-05-CA-03.
- **RF-05-CA-02:** Cuando se consulte con un código válido, el sistema deberá devolver únicamente la cita asociada con ese código y ninguna otra.
- **RF-05-CA-03:** Cuando se muestre el teléfono, el sistema deberá ocultar los primeros 6 dígitos y mostrar únicamente los últimos 4. Cuando se muestre el correo, el sistema deberá conservar únicamente la primera letra de la parte anterior a `@`, la primera letra del dominio y la extensión posterior al último punto, colocando siempre tres asteriscos después de cada letra conservada; por ejemplo, `ana@gmail.com` deberá mostrarse como `a***@g***.com` y `a@b.co` como `a***@b***.co`.
- **RF-05-CA-04:** Mientras la modificación o cancelación esté permitida, el sistema deberá mostrar las acciones correspondientes.
- **RF-05-CA-05:** Si el código es inválido o expiró, el sistema deberá negar la consulta mediante un mensaje genérico que no revele la existencia de una cita ni detalles internos.
- **RF-05-CA-06:** Hasta las 23:59:59 de `America/Mexico_City` del día que resulte de sumar 30 días naturales a la última fecha programada vigente, el sistema deberá permitir consultar la cita mediante su código, incluso si está cancelada, completada, marcada como no asistió o como resultado no registrado.
- **RF-05-CA-07:** Cuando una misma dirección IP acumule 5 validaciones fallidas de credenciales públicas —código solo o combinación de código y teléfono— dentro de cualquier ventana móvil de 15 minutos, el sistema deberá bloquear durante 15 minutos desde el quinto intento sus accesos públicos para consultar, modificar y cancelar citas.
- **RF-05-CA-08:** Mientras una dirección IP esté bloqueada por intentos fallidos, el sistema deberá mantener disponibles los accesos desde otras direcciones IP y el acceso administrativo.
- **RF-05-CA-09:** Para calcular RF-05-CA-07, el sistema deberá contar como fallo un código mal formado, inexistente o expirado y cualquier combinación incorrecta de código y teléfono.
- **RF-05-CA-10:** Cuando una validación pública sea correcta, el sistema no deberá borrar los fallos anteriores de la dirección IP; cada fallo deberá dejar de contar al salir de la ventana móvil de 15 minutos.
- **RF-05-CA-11:** Mientras una dirección IP esté bloqueada, las solicitudes adicionales deberán rechazarse sin prolongar los 15 minutos de bloqueo ni contarse como nuevas validaciones fallidas.

### RF-06 — Modificar una cita

La clienta puede modificar únicamente la fecha, el horario, la sucursal o el servicio. Un administrador autenticado puede modificar además el nombre, apellido, teléfono o correo sin conocer el código privado.

**Criterios de aceptación EARS:**

- **RF-06-CA-01:** Cuando una clienta solicite una modificación, el sistema deberá exigir el código privado y el número telefónico registrado.
- **RF-06-CA-02:** Cuando un administrador solicite una modificación, el sistema deberá exigir que esté autenticado y autorizado.
- **RF-06-CA-03:** Cuando una clienta solicite una modificación, el sistema deberá permitirla únicamente si la cita está programada y faltan al menos 60 minutos para su inicio.
- **RF-06-CA-04:** Cuando un administrador solicite una modificación, el sistema deberá permitirla únicamente si la cita está programada y todavía no ha alcanzado su hora de inicio.
- **RF-06-CA-05:** Cuando un administrador cambie nombre, apellido, teléfono o correo, el sistema deberá aplicar nuevamente las validaciones de RF-03-CA-01, RF-03-CA-02 y RF-03-CA-03, manteniendo el correo como obligatorio.
- **RF-06-CA-06:** Cuando se modifique una cita, el sistema deberá conservar el mismo código privado.
- **RF-06-CA-07:** Cuando solo cambien fecha, horario, sucursal o datos de contacto, el sistema deberá conservar el precio acordado originalmente.
- **RF-06-CA-08:** Cuando cambie el servicio, el sistema deberá sustituir la duración y el precio acordado por los valores vigentes del nuevo servicio.
- **RF-06-CA-09:** Cuando un administrador cambie el teléfono o correo, el sistema deberá reenviar el mismo código privado a los datos de contacto actualizados.
- **RF-06-CA-10:** Si la clienta solicita el cambio con menos de 60 minutos de anticipación, el administrador lo solicita desde la hora de inicio, o la nueva selección no está disponible, el sistema deberá rechazar la modificación y conservar la cita sin cambios.
- **RF-06-CA-11:** Mientras una cita tenga un estado final, el sistema deberá impedir cualquier modificación de sus datos.
- **RF-06-CA-12:** Si la combinación pública de código y teléfono es inválida, el sistema deberá rechazar la modificación mediante un mensaje genérico sin revelar qué dato falló ni la existencia de la cita.
- **RF-06-CA-13:** Cuando cambien la fecha, horario, sucursal o servicio, el sistema deberá comprobar de nuevo el límite de 90 días, la actividad y disponibilidad del servicio y la disponibilidad de la agenda; para una modificación pública deberá aplicar los 60 minutos de anticipación y para una modificación administrativa deberá exigir que el nuevo inicio no sea anterior al momento de la solicitud.
- **RF-06-CA-14:** Cuando una clienta solicite públicamente una modificación, el sistema deberá permitir cambiar únicamente la fecha, el horario, la sucursal o el servicio y deberá rechazar cualquier intento de cambiar el nombre, apellido, teléfono o correo.
- **RF-06-CA-15:** Cuando un administrador autenticado y autorizado solicite una modificación, el sistema deberá permitir cambiar la fecha, el horario, la sucursal, el servicio, el nombre, el apellido, el teléfono o el correo conforme a las demás reglas de este requisito.

### RF-07 — Cancelar una cita

La cancelación sustituye a la eliminación de citas dentro de este MVP.

**Criterios de aceptación EARS:**

- **RF-07-CA-01:** Cuando una clienta solicite cancelar, el sistema deberá exigir el código privado y el número telefónico registrado.
- **RF-07-CA-02:** Cuando un administrador solicite cancelar, el sistema deberá exigir que esté autenticado y autorizado.
- **RF-07-CA-03:** Cuando una clienta solicite cancelar, el sistema deberá permitirlo únicamente si la cita está programada y faltan al menos 60 minutos para su inicio.
- **RF-07-CA-04:** Cuando se confirme una cancelación, el sistema deberá permitir registrar un motivo opcional, cambiar el estado a cancelada, conservar la cita y liberar su periodo.
- **RF-07-CA-05:** Cuando se proporcione un motivo, el sistema deberá retirar espacios externos, aceptar hasta 250 caracteres Unicode visibles, rechazar caracteres de control y tratar un valor vacío como motivo no proporcionado.
- **RF-07-CA-06:** Si la cita tiene un estado final, la clienta solicita cancelar con menos de 60 minutos de anticipación o el administrador lo solicita desde la hora de inicio, el sistema deberá rechazar la cancelación y conservar la cita sin cambios.
- **RF-07-CA-07:** Mientras exista un motivo de cancelación, el sistema deberá mostrarlo únicamente al administrador autenticado y nunca en la consulta pública.
- **RF-07-CA-08:** Si la combinación pública de código y teléfono es inválida, el sistema deberá rechazar la cancelación mediante un mensaje genérico sin revelar qué dato falló ni la existencia de la cita.
- **RF-07-CA-09:** Cuando un administrador solicite cancelar, el sistema deberá permitirlo únicamente si la cita está programada y todavía no ha alcanzado su hora de inicio.

### RF-08 — Consultar y gestionar la agenda como administrador

**Criterios de aceptación EARS:**

- **RF-08-CA-01:** Cuando un administrador autenticado consulte la agenda, el sistema deberá permitirle ver citas de ambas sucursales sin códigos privados.
- **RF-08-CA-02:** Cuando el administrador consulte la agenda, el sistema deberá permitir filtrar por fecha, sucursal y estado.
- **RF-08-CA-03:** Cuando el administrador busque una cita, el sistema deberá permitir buscar por código privado, número telefónico, nombre, apellido o fecha.
- **RF-08-CA-04:** Cuando el administrador consulte una cita, el sistema deberá mostrar nombre, apellido, teléfono, correo, servicio, sucursal, fecha, horario, duración, precio y estado, sin mostrar el código privado.
- **RF-08-CA-05:** Si una persona no autenticada o no autorizada intenta acceder a la agenda administrativa, el sistema deberá negar el acceso sin exponer datos privados.
- **RF-08-CA-06:** Cuando se ejecute una búsqueda administrativa, el sistema deberá exigir coincidencia exacta para el código privado, el teléfono normalizado de 10 dígitos o la fecha. Para nombre o apellido deberá retirar espacios exteriores y aceptar coincidencias parciales sin distinguir mayúsculas, minúsculas ni acentos.

### RF-09 — Completar una cita o registrar inasistencia

**Criterios de aceptación EARS:**

- **RF-09-CA-01:** Desde el instante exacto en que finalice el periodo reservado, el sistema deberá permitir que un administrador marque una cita programada como completada.
- **RF-09-CA-02:** Desde el instante exacto en que transcurran 5 minutos a partir del inicio programado, el sistema deberá permitir que un administrador marque la cita como no asistió.
- **RF-09-CA-03:** Mientras una cita pasada no haya sido marcada por el administrador y no haya alcanzado su momento de retiro del sistema operativo, el sistema deberá conservar su estado programada.
- **RF-09-CA-04:** Cuando una cita programada alcance su momento de retiro del sistema operativo sin resultado administrativo, el sistema deberá cambiarla automáticamente a resultado no registrado antes de retirarla.
- **RF-09-CA-05:** Mientras una cita esté cancelada, completada, marcada como no asistió o como resultado no registrado, el sistema deberá impedir su reactivación o cambio a otro estado.
- **RF-09-CA-06:** Antes de finalizar el periodo reservado, el sistema deberá impedir que una cita se marque como completada.
- **RF-09-CA-07:** Antes de que transcurran 5 minutos desde el inicio programado, el sistema deberá impedir que una cita se marque como no asistió.
- **RF-09-CA-08:** Si la clienta llega después de que su cita haya sido marcada como no asistió y el administrador decide atenderla, el sistema deberá conservar la cita original en su estado final y exigir la creación de una cita administrativa nueva en el siguiente inicio disponible conforme a RF-03.

### RF-10 — Bloquear disponibilidad

El administrador puede crear, editar y eliminar bloqueos únicos; los bloqueos recurrentes no forman parte de esta spec.

**Criterios de aceptación EARS:**

- **RF-10-CA-01:** Cuando un administrador cree un bloqueo, el sistema deberá permitir que afecte toda la agenda del profesional o una sola sucursal.
- **RF-10-CA-02:** Cuando se defina un bloqueo, el sistema deberá exigir un inicio y fin en `America/Mexico_City`, alineados a intervalos de 15 minutos y con el fin posterior al inicio.
- **RF-10-CA-03:** Cuando se defina un bloqueo, el sistema deberá permitir que atraviese medianoche y abarque varios días sin una duración máxima.
- **RF-10-CA-04:** Si el bloqueo entra en conflicto con una cita programada, el sistema deberá rechazarlo hasta que la cita sea modificada o cancelada.
- **RF-10-CA-05:** Mientras exista un bloqueo global, el sistema deberá considerar que el profesional no está disponible e impedir citas en ambas sucursales durante ese periodo.
- **RF-10-CA-06:** Mientras exista un bloqueo de sucursal, el sistema deberá considerar que esa ubicación no puede recibir citas y permitir que el profesional atienda en la otra sucursal si la agenda lo permite.
- **RF-10-CA-07:** Cuando se calcule un traslado, el sistema no deberá considerar un bloqueo de sucursal como una cita ni como evidencia de la ubicación física del profesional.
- **RF-10-CA-08:** Cuando un administrador edite un bloqueo, el sistema deberá aplicar las mismas validaciones exigidas para crearlo.
- **RF-10-CA-09:** Cuando un administrador elimine un bloqueo, el sistema deberá liberar su periodo sin modificar citas existentes.
- **RF-10-CA-10:** Si un bloqueo nuevo o editado se superpone con otro bloqueo del mismo alcance, el sistema deberá rechazar la operación como redundante.
- **RF-10-CA-11:** Si un bloqueo global nuevo o editado contiene o se superpone con un bloqueo de sucursal, el sistema deberá rechazar la operación como redundante.
- **RF-10-CA-12:** Si un bloqueo de sucursal nuevo o editado contiene o se superpone con un bloqueo global, el sistema deberá rechazar la operación como redundante.

### RF-11 — Proponer horarios alternativos

**Criterios de aceptación EARS:**

- **RF-11-CA-01:** Si la fecha y el horario solicitados cumplen el formato, la jornada, el intervalo, la anticipación y el horizonte aplicables, pero no están disponibles por la agenda, un bloqueo o el tiempo de separación, el sistema deberá mostrar hasta tres horarios válidos del mismo día, servicio y sucursal, ordenados por la menor diferencia absoluta respecto del horario solicitado.
- **RF-11-CA-02:** Cuando dos alternativas estén a la misma distancia del horario solicitado, el sistema deberá mostrar primero la alternativa posterior.
- **RF-11-CA-03:** Si no existen alternativas ese día, el sistema deberá indicar que se seleccione otra fecha.
- **RF-11-CA-04:** Si la fecha o el horario solicitados incumplen el formato, la jornada, el intervalo, la anticipación o el horizonte aplicables, el sistema deberá rechazar la solicitud, indicar qué regla debe corregirse y no proponer horarios alternativos.

### RF-12 — Recuperar el código privado

**Criterios de aceptación EARS:**

- **RF-12-CA-01:** Cuando una clienta pierda un código todavía vigente, el sistema deberá permitir que un administrador autenticado y autorizado lo reenvíe por WhatsApp y correo únicamente al número y correo ya registrados.
- **RF-12-CA-02:** Cuando se reenvíe el código, el sistema no deberá generar un código nuevo ni mostrarlo en un acceso público.
- **RF-12-CA-03:** Cuando el código haya expirado o la cita haya sido retirada del sistema operativo, el sistema deberá impedir su recuperación o reenvío.
- **RF-12-CA-04:** Si WhatsApp, correo o ambos canales fallan durante la recuperación, el sistema deberá conservar sin cambios el código y la cita, registrar qué canales fallaron e informar al administrador sin revelar detalles internos.

### RF-13 — Expirar y retirar las citas del sistema operativo

**Criterios de aceptación EARS:**

- **RF-13-CA-01:** Hasta las 23:59:59 de `America/Mexico_City` del día que resulte de sumar 30 días naturales a la última fecha programada vigente, el sistema deberá conservar el acceso mediante código y los datos personales de la cita.
- **RF-13-CA-02:** A partir de las 00:00:00 del día siguiente al límite de RF-13-CA-01, el sistema deberá expirar el código y retirar la cita de las consultas públicas, la agenda y las operaciones administrativas ordinarias.
- **RF-13-CA-03:** Cuando una cita programada alcance el momento definido en RF-13-CA-02 sin resultado administrativo, el sistema deberá cambiarla primero a resultado no registrado.
- **RF-13-CA-04:** Después de retirar la cita del sistema operativo, el sistema deberá conservar únicamente conteos estadísticos disociados por el mes de la última fecha programada vigente, servicio, sucursal y estado para fines ordinarios del negocio.
- **RF-13-CA-05:** Cuando una cita haya sido modificada, el sistema deberá calcular el límite desde la última fecha programada vigente.
- **RF-13-CA-06:** Cuando una cita haya sido cancelada, el sistema deberá calcular el límite desde la última fecha programada vigente y no desde el momento de la cancelación.
- **RF-13-CA-07:** Cuando cualquier operación pública o administrativa intente acceder a una cita que alcanzó el instante de retiro, el sistema deberá tratarla inmediatamente como retirada aunque el proceso físico de limpieza todavía no haya terminado.
- **RF-13-CA-08:** Al comenzar cada día a las 00:00:00 de `America/Mexico_City`, el sistema deberá ejecutar el retiro de las citas vencidas; si la aplicación inicia o se recupera después de ese instante, deberá completar primero cualquier retiro pendiente antes de admitir tráfico de usuarios.

## Requisitos no funcionales

### RNF-01 — Seguridad y privacidad

- Toda entrada externa debe tratarse como no confiable y validarse.
- Los códigos privados deben cumplir RF-03-CA-11 y tratarse como información sensible.
- Las referencias temporales de confirmación deben cumplir RF-03-CA-16, tratarse como secretos y no aparecer completas en registros, historiales ni respuestas distintas de su flujo de reservación.
- Los datos privados y las operaciones administrativas no deben quedar públicamente accesibles.
- Los errores no deben revelar credenciales, datos sensibles, existencia de otras citas ni detalles internos.
- El tratamiento y la conservación de datos personales deben limitarse a lo definido en esta spec.
- Los datos personales y de contacto no deben utilizarse para publicidad, promociones, encuestas, perfiles comerciales ni finalidades secundarias.
- El MVP solo puede utilizar cookies u otras tecnologías locales estrictamente necesarias para el funcionamiento y la seguridad del sistema; no debe incorporar analítica de visitantes, píxeles publicitarios ni rastreo no esencial.

### RNF-02 — Integridad

- Las restricciones de disponibilidad, anticipación, estados, servicios y permisos deben protegerse en la capa apropiada y no depender únicamente de la interfaz.
- Una operación rechazada no debe dejar cambios parciales ni ocupar disponibilidad.
- La concurrencia no debe permitir citas incompatibles para el único profesional.

### RNF-03 — Idioma y tiempo

- Todo contenido visible para clientas y administradores debe estar en español.
- Todas las fechas, horarios, límites y periodos deben evaluarse de forma consistente en `America/Mexico_City`.

### RNF-04 — Protección ante exceso de solicitudes

- Para consultar públicamente el catálogo de servicios o la disponibilidad, una misma dirección IP puede realizar como máximo 60 solicitudes dentro de cualquier ventana móvil de 60 segundos.
- Para crear una cita o consultar, modificar o cancelar una cita mediante acceso público, una misma dirección IP puede realizar como máximo 10 solicitudes dentro de cualquier ventana móvil de 15 minutos.
- Cuando una solicitud exceda el límite aplicable, el sistema debe rechazarla sin ejecutar la consulta u operación, sin modificar datos y sin revelar detalles internos.
- Las solicitudes rechazadas por exceso de volumen no deben ampliar por sí mismas las ventanas definidas.
- Los límites generales deben ser independientes del bloqueo específico por validaciones fallidas de código; cuando coincidan, deberá aplicarse la restricción que mantenga denegado el acceso durante más tiempo.
- La recuperación de códigos realizada por una cuenta administrativa y los demás límites administrativos se rigen por la especificación 002.

### RNF-05 — Continuidad y recuperación

- En producción deberán generarse respaldos cifrados de PostgreSQL al menos cada 6 horas y conservarse durante un máximo de 7 días con acceso restringido.
- Antes de aplicar un cambio al esquema de la base de datos de producción deberá generarse un respaldo adicional recuperable.
- Toda restauración deberá realizarse de forma aislada y ejecutar el retiro de RF-13 antes de admitir tráfico de usuarios.
- La aplicación deberá ofrecer una comprobación técnica de salud que confirme su funcionamiento y la disponibilidad de PostgreSQL sin revelar datos ni detalles internos; un fallo deberá generar una alerta operativa para el responsable del proyecto mediante un mecanismo incluido en el presupuesto aprobado.

## Casos límite

- Una cita solicitada públicamente exactamente una hora antes está permitida; un segundo después del límite debe rechazarse.
- Una cita administrativa no exige una hora de anticipación: si se solicita a las 10:05, su primer inicio posible es a las 10:15, siempre que cumpla todas las reglas de disponibilidad.
- Una cita solicitada exactamente 90 periodos de 24 horas hacia el futuro está permitida; un segundo después debe rechazarse.
- Una modificación o cancelación pública solicitada exactamente una hora antes está permitida; un segundo después del límite debe rechazarse.
- El administrador puede modificar o cancelar una cita programada hasta el instante anterior a su inicio; desde la hora exacta de inicio debe rechazarse.
- Un código mal formado, inexistente o expirado y una combinación incorrecta de código y teléfono cuentan como validaciones públicas fallidas.
- Una validación pública correcta no elimina los fallos de la misma dirección IP que todavía se encuentren dentro de la ventana de 15 minutos.
- Una solicitud realizada durante el bloqueo por credenciales fallidas no prolonga el bloqueo ni genera un nuevo fallo.
- Las 09:00 y las 19:00 son horas válidas de inicio.
- Una cita iniciada a las 19:00 puede terminar después de esa hora.
- Una cita que atraviesa medianoche continúa ocupando la agenda hasta su finalización y el cumplimiento del tiempo de separación.
- Una cita puede comenzar o continuar entre las 13:00 y las 14:00.
- Una nueva cita insertada entre otras dos debe respetar el tiempo de separación respecto de ambas.
- Si una cita termina a las 10:15 y la siguiente es en la misma sucursal, el mínimo de 5 minutos produce las 10:20 y el siguiente inicio válido es a las 10:30.
- Si una cita termina a las 10:00 y la siguiente es en la otra sucursal, el mínimo de 25 minutos produce las 10:25 y el siguiente inicio válido es a las 10:30.
- Una cita puede comenzar exactamente a las 11:00 cuando un bloqueo aplicable termina a las 11:00.
- Al cambiar de sucursal deben recalcularse los 25 minutos de separación.
- Al cambiar de servicio deben recalcularse duración, disponibilidad y precio.
- Una modificación pública que intente cambiar nombre, apellido, teléfono o correo debe rechazarse; esas correcciones requieren una cuenta administrativa autenticada y autorizada.
- Cuando un administrador cambie el teléfono o correo, el código privado se conserva y se envía a los contactos nuevos.
- Una búsqueda administrativa por código privado, teléfono normalizado o fecha solo devuelve coincidencias exactas; buscar `maria` por nombre o apellido también encuentra valores parciales como `María Fernanda` sin distinguir mayúsculas ni acentos.
- Una cita cancelada libera disponibilidad, pero permanece consultable hasta su expiración.
- Una cita con estado final no puede modificarse, cancelarse, reactivarse ni cambiar de estado.
- Una cita que inicia a las 10:00 puede marcarse como no asistió desde las 10:05 exactas, pero no antes; al hacerlo, deja de ocupar disponibilidad.
- Si la clienta llega después de que su cita se marcó como no asistió, la cita original no se reactiva; una nueva cita solo puede comenzar en un intervalo disponible y no puede superponerse con otra atención.
- Una cita que termina a las 11:00 puede marcarse como completada desde las 11:00 exactas, pero no antes.
- Un horario válido ocupado puede producir alternativas; un horario como 10:07, una fecha pasada, una hora fuera de la jornada o una reservación pública con menos de 60 minutos de anticipación debe rechazarse sin alternativas.
- Un fallo de WhatsApp o correo no revierte una creación, modificación o cancelación ya confirmada.
- Un teléfono sin cuenta de WhatsApp produce un fallo de notificación y no un fallo de la cita.
- `5512345678`, `55 1234 5678`, `(55) 1234-5678` y `+52 55 1234 5678` se normalizan como `5512345678`; un prefijo distinto de `+52`, una extensión, una letra o un resultado diferente de 10 dígitos se rechaza.
- Un correo con espacios externos se valida después de retirarlos; uno con espacios internos, más de un signo `@`, una parte vacía, puntos consecutivos antes de `@`, caracteres no permitidos, un dominio sin punto o una extensión que no contenga al menos dos letras debe rechazarse.
- Incluso un correo con una sola letra antes de `@` o en el dominio debe mostrar tres asteriscos después de cada letra visible en la consulta pública.
- Un servicio desactivado no altera citas existentes, pero no puede utilizarse en una reservación o reprogramación nueva.
- Un bloqueo no puede desplazar ni cancelar automáticamente una cita existente.
- Un bloqueo puede atravesar medianoche y abarcar varios días.
- Un bloqueo nuevo o editado no puede superponerse con otro bloqueo redundante.
- Operaciones concurrentes sobre citas, servicios o bloqueos no pueden dejar una combinación inválida ni cambios parciales.
- Si se interrumpe la respuesta después de crear una cita, repetir la misma confirmación antes de que transcurran 24 horas desde la generación de su referencia devuelve la cita y su mismo código privado; no crea una cita adicional ni reenvía WhatsApp o correo, aunque los envíos originales hayan fallado.
- Una referencia que nunca confirmó una cita también vence exactamente 24 horas después de generarse; usar cualquier referencia vencida se rechaza y nunca crea una cita nueva.
- Conocer o repetir los datos personales y el horario de una cita no permite recuperar su confirmación sin la referencia secreta del intento original.
- Dos solicitudes intencionalmente distintas deben tratarse como reservaciones diferentes aunque compartan datos de contacto.
- Una cita aún programada al alcanzar su momento de retiro operativo cambia primero a resultado no registrado.
- Una cita retirada deja de estar disponible en las funciones públicas y administrativas ordinarias y solo contribuye a conteos disociados.
- Una dirección IP puede realizar exactamente 60 consultas públicas de catálogo o disponibilidad en 60 segundos; la solicitud 61 dentro de la misma ventana debe rechazarse.
- Una dirección IP puede realizar exactamente 10 operaciones públicas de citas en 15 minutos; la solicitud 11 dentro de la misma ventana debe rechazarse.
- Un mensaje aceptado por un proveedor no debe mostrarse como entregado hasta recibir su confirmación; un fallo posterior no modifica la cita y queda disponible para reintento administrativo.
- Una cita creada o reprogramada cuando faltan exactamente 24 horas no genera un recordatorio adicional; con un segundo más de anticipación sí queda programado para el instante correspondiente.
- Una cita pública y una cita creada administrativamente reciben el mismo recordatorio cuando cumplen el umbral de más de 24 horas.
- Una reprogramación invalida el recordatorio pendiente del horario anterior y puede programar uno nuevo; una cancelación confirmada antes del inicio de envío registrado impide el recordatorio.
- Un recordatorio cuyo envío ya comenzó de forma registrada antes de una modificación o cancelación concurrente puede llegar aunque el proveedor responda después; no puede retirarse y no sustituye la notificación posterior del cambio confirmado.
- Al recuperarse de una interrupción, un recordatorio pendiente se intenta si faltan más de 60 minutos y se omite definitivamente si faltan exactamente 60 minutos o menos.
- Correo y WhatsApp fallan de manera independiente; no hay reintento automático y un canal ya aceptado o entregado no vuelve a enviarse.
- El tercer reintento manual fallido de un canal agota sus reintentos; ninguno puede ocurrir antes de cinco minutos desde el anterior ni cuando falten 60 minutos o menos.
- Dos procesos concurrentes no pueden producir dos envíos iniciales ni dos reintentos equivalentes del mismo recordatorio, horario y canal.
- Ningún recordatorio muestra, envía ni permite recuperar el código privado.
- Si el servidor no estaba disponible a las 00:00, ninguna cita vencida puede reaparecer al reiniciar: el retiro pendiente debe completarse antes de atender solicitudes.
- Un respaldo programado no puede tener más de 6 horas de separación respecto del respaldo programado anterior y ninguno puede conservarse durante más de 7 días.

## Fuera de alcance

- Cuentas o autenticación para clientas.
- Recopilación de nombres, edades u otros datos personales de personas menores de edad.
- Creación de cuentas, inicio y cierre de sesión, recuperación de acceso y ciclo de sesión del administrador; estos comportamientos pertenecen a la spec 002.
- Más de un profesional o agendas independientes por profesional.
- Más de un servicio dentro de la misma cita.
- Pagos, anticipos y comprobantes.
- Publicidad, promociones, encuestas, perfiles comerciales y cualquier uso secundario de los datos personales.
- Analítica de visitantes, píxeles publicitarios y tecnologías de rastreo no esenciales.
- Bloqueos recurrentes de disponibilidad.
- Eliminación administrativa de servicios; se utiliza su desactivación.
- Eliminación física inmediata de citas canceladas.
- Reactivación o cambio de citas con estado final.
- Bloqueo, acceso restringido y conservación individual de datos después del retiro operativo por obligaciones legales; estos comportamientos deberán definirse en una especificación posterior basada en una política de conservación jurídicamente revisada.
- Decisiones de interfaz, arquitectura, proveedores o implementación.

## Criterios de finalización

- Todos los requisitos funcionales cuentan con criterios EARS verificables.
- Las reglas críticas de disponibilidad, anticipación, permisos, estados, privacidad y retiro operativo cuentan con pruebas automatizadas.
- Las pruebas cubren los límites temporales exactos, las excepciones administrativas de anticipación para crear, modificar y cancelar citas, la tolerancia de 5 minutos antes de registrar una inasistencia, los límites inclusivos y exclusivos de citas y bloqueos, el ajuste de las separaciones de 5 o 25 minutos al siguiente inicio de 15 minutos, la distinción entre horarios inválidos y horarios válidos ocupados, las alternativas, superposiciones, traslados entre sucursales, bloqueos y solicitudes concurrentes.
- Las pruebas cubren aislamiento entre citas, fortaleza y expiración de códigos, ocultamiento de contactos, bloqueo por intentos fallidos, retiro operativo y estadísticas disociadas.
- Las pruebas cubren la validación exacta de servicios, teléfonos nacionales de 10 dígitos en todos los formatos permitidos y correos, el rechazo de prefijos, extensiones y caracteres telefónicos no permitidos, las coincidencias exactas y parciales de la búsqueda administrativa, incluida la equivalencia de mayúsculas y acentos en nombres, los campos modificables por una clienta y por un administrador, la conservación del código al corregir contactos, estados finales, llegada posterior a una inasistencia confirmada, fallos de notificación, recuperación del código por ambos canales y revalidación concurrente de disponibilidad.
- Las pruebas cubren el registro inmutable de la aceptación del aviso de privacidad y su asociación con la versión correspondiente.
- Las pruebas cubren el reintento de una confirmación cuya respuesta se interrumpe, la devolución del resultado original sin repetir notificaciones, la aleatoriedad y ausencia de datos personales en su referencia, su vencimiento exacto a las 24 horas desde la generación haya o no confirmado una cita, el rechazo de referencias vencidas sin crear duplicados, el rechazo de coincidencias sin referencia y dos reintentos concurrentes de la misma solicitud.
- Las operaciones administrativas requieren autenticación y autorización.
- La spec 002 de autenticación administrativa está aprobada antes de implementar operaciones administrativas.
- Las pruebas cubren los límites públicos exactos de volumen, sus ventanas móviles y su interacción con el bloqueo por credenciales fallidas.
- Las pruebas cubren los estados aceptado, entregado y fallido de cada canal, los fallos tardíos y el reintento administrativo sin generar ni revelar un código nuevo.
- Las pruebas cubren el umbral exacto de más de 24 horas, citas públicas y administrativas, reprogramaciones, cancelaciones, recuperación después de una interrupción, corte exacto de 60 minutos, contactos vigentes, contenido sin código privado, independencia de canales, ausencia de reintentos automáticos, máximo de tres reintentos con separación de cinco minutos y envíos concurrentes sin duplicados.
- Las pruebas cubren el retiro diario y al iniciar la aplicación, la denegación inmediata de acceso a citas vencidas, la frecuencia y conservación de respaldos y la comprobación de salud sin exposición de detalles internos.
- Ningún dato privado queda accesible públicamente fuera de las reglas del código privado.
- Todas las verificaciones del proyecto y pruebas existentes pasan.
- El responsable del proyecto revisa, comprende y aprueba explícitamente la spec antes de convertirla en activa.

## Decisión diferida que bloquea la publicación

- **[NECESITA ACLARACIÓN ANTES DE PUBLICAR]:** Una revisión jurídica deberá determinar y aprobar si existe obligación de conservar evidencia individual después del retiro operativo, qué campos serían estrictamente necesarios, quién podría acceder a ellos y durante cuánto tiempo permanecerían bloqueados. Esta decisión queda fuera de la implementación actual y no impide planificar ni desarrollar el MVP, pero BeautyHub no deberá publicarse hasta resolverla e incorporarla en una especificación aprobada.
