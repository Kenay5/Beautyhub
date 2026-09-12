# Guía de diseño de BeautyHub

**Estado:** aprobada explícitamente por el responsable del proyecto el 11 de septiembre de 2026, incluidas las referencias públicas y administrativas.

## 1. Propósito y autoridad

Esta guía convierte las referencias visuales de BeautyHub y Manita de Gato en un sistema coherente para las interfaces públicas y administrativas.

La jerarquía aplicable es:

1. docs/constitution.md.
2. Specs activas y aprobadas.
3. Planes aprobados.
4. Esta guía visual.
5. Mockups y demás referencias visuales.

La implementación y las pruebas deben obedecer esa jerarquía; su existencia no convierte un detalle del mockup en requisito. En forma resumida: **Constitution > Specs > Plans > Design Guide > visual mockups**.

Esta guía no puede introducir requisitos funcionales, campos, permisos, servicios ni dependencias.

### 1.1 Clasificación

- **[SPEC]** Obligatorio por la constitución o las specs.
- **[PLAN]** Decisión técnica ya aprobada.
- **[VISUAL]** Decisión visual derivada de las referencias y aprobada mediante esta guía.
- **[NO IMPLEMENTAR]** Elemento de las referencias que contradice o excede el alcance aprobado.
- **[PENDIENTE]** Requiere material o aprobación adicional.

## 2. Fuentes visuales revisadas

Mockups públicos:

- `docs/design/public/home.png`;
- `docs/design/public/servicios.png`;
- `docs/design/public/mobile.png`;
- `docs/design/public/reservar cita_cita.png`;
- `docs/design/public/reservar_cita_datos.png`;
- `docs/design/public/reservar_cita_confirmar.png`;
- `docs/design/public/confirmacion.png`;
- `docs/design/public/consultar_cita_cancelacion_y_modificar.png`.

Mockups administrativos:

| Referencia lógica | Archivo actual | Flujos representados |
|---|---|---|
| 01 — Login | `docs/design/admin/login.png` | Inicio con TOTP o recuperación, rechazo genérico, bloqueo y sesión expirada. |
| 02 — Activación | `docs/design/admin/activacion_administrativa.png` | Invitación, contraseña, TOTP, códigos de recuperación y finalización. |
| 03 — Agenda | `docs/design/admin/agenda_principal.png` | Agenda diaria, detalle y creación administrativa. |
| 04 — Bloqueos | `docs/design/admin/lista_bloqueos.png` | Lista, creación, conflicto, edición y retiro. |
| 05 — Servicios | `docs/design/admin/lista_servicios.png` | Lista, creación, edición y desactivación. |
| 06 — Personal y seguridad | `docs/design/admin/personal_y_seguridad.png` | Cuenta de personal, invitación, desactivación y seguridad propia. |
| 07 — Historial | `docs/design/admin/historial_administrativo.png` | Consulta, filtros y detalle permitido de eventos. |

Recursos de marca:

- logo de Manita de Gato;
- fotografía de uñas;
- composición fotográfica de corte en capas.

Los mockups son únicamente referencias visuales. No son fuentes de requisitos, datos de negocio, servicios, precios, direcciones, afirmaciones comerciales ni comportamiento del sistema. Ante cualquier diferencia, prevalecen la constitución, las specs y los planes aprobados.

**[VISUAL]** Los nombres reales de los archivos administrativos son descriptivos y no siguen la numeración de sus referencias lógicas. Esta diferencia no cambia su orden ni sus flujos.

**[NO IMPLEMENTAR]** Los nombres, correos, teléfonos, fechas, servicios, precios, cantidades, referencias internas y estados mostrados como ejemplo en los mockups no se copiarán a código, pruebas, fixtures o datos iniciales. Toda evidencia de implementación utilizará datos ficticios creados expresamente para pruebas.

**[NO IMPLEMENTAR]** Los mockups compuestos no acreditan por sí mismos responsive, accesibilidad, autorización o seguridad. Esas garantías provienen de las specs y planes y deberán comprobarse durante sus tareas.

## 3. Dirección visual

**[VISUAL]** La interfaz debe sentirse:

- cálida;
- femenina sin perder claridad;
- delicada;
- confiable;
- ordenada;
- profesional;
- sencilla de utilizar desde un celular.

La decoración debe acompañar la tarea, no competir con los formularios ni dificultar la lectura.

El magenta del negocio será el acento principal. Los fondos rosa pálido y blanco proporcionarán ligereza. El azul marino se utilizará para textos y estructura, aportando contraste y estabilidad.

**[VISUAL]** Manita de Gato será la marca visible para las clientas y Salón de belleza será su única frase descriptiva. BeautyHub permanecerá como nombre del proyecto y del sistema técnico, salvo aprobación posterior de otro tratamiento comercial. La versión web del logo no utilizará la frase tienda en línea.

## 4. Requisitos obligatorios de interfaz

### 4.1 Idioma

- **[SPEC]** Todo contenido visible para clientas y administradores debe estar en español.
- **[SPEC]** Código, identificadores, logs y mensajes técnicos deben permanecer en inglés.
- **[SPEC]** Los errores públicos no deben mostrar términos técnicos, nombres de proveedores ni detalles internos.

### 4.2 Funciones públicas

- **[SPEC]** La clienta puede reservar una cita sin crear una cuenta.
- **[VISUAL]** Reservar cita y Consultar mi cita deben tener acceso claro y prominente según el contexto de la pantalla.
- **[VISUAL]** Consultar mi cita es la sección para acceder a una cita existente.
- **[SPEC]** La consulta inicial solicita únicamente el código privado.
- **[SPEC]** Después de una consulta correcta pueden aparecer Modificar cita y Cancelar cita, únicamente cuando la operación esté permitida.
- **[SPEC]** Modificar o cancelar exige el teléfono registrado además del código privado.
- **[VISUAL]** El teléfono se solicita después de elegir Modificar cita o Cancelar cita desde la consulta.
- **[VISUAL]** Modificar cita y Cancelar cita no forman parte de la navegación principal.
- **[SPEC]** La clienta solo puede ver la cita asociada con su código.
- **[SPEC]** Los servicios públicos deben elegirse de una lista de servicios activos de la sucursal; no pueden escribirse libremente.
- **[SPEC]** Cuando un horario válido esté ocupado pueden mostrarse hasta tres alternativas.
- **[SPEC]** Una fecha u horario inválido debe mostrar la regla que debe corregirse y no ofrecer alternativas.

### 4.3 Administración

- **[SPEC]** Ninguna pantalla administrativa puede mostrar información privada sin una sesión válida.
- **[SPEC]** Propietario y personal pueden gestionar citas y bloqueos.
- **[SPEC]** Solo el propietario puede gestionar servicios y precios.
- **[SPEC]** Solo el propietario puede gestionar al personal y consultar el historial.
- **[SPEC]** Ocultar una opción por rol es una ayuda visual; la autorización real siempre corresponde al backend.
- **[SPEC]** La interfaz administrativa no debe mostrar códigos privados, salvo la confirmación inmediata de una cita que acaba de crear esa misma persona.
- **[SPEC]** Los nombres de rol visibles son Propietaria o Propietario y Personal; Administrador es un término colectivo, no un tercer rol.
- **[PLAN]** Contraseñas, TOTP, códigos de recuperación, tokens, QR, claves manuales y CSRF permanecen fuera de URLs, almacenamiento persistente y registros del navegador.
- **[VISUAL]** La agenda funciona como destino operativo principal después de iniciar sesión; esto no modifica la expiración ni crea una sesión durante la activación.
- **[NO IMPLEMENTAR]** La campana de notificaciones de los mockups no representa una bandeja ni avisos dentro de la aplicación. La spec solo aprueba los avisos por correo definidos.

## 5. Paleta de colores

Los colores se derivan del logo y de los mockups. Durante la implementación deberán verificarse en los estados y combinaciones reales.

| Token técnico | Color | Uso |
|---|---:|---|
| brand-primary | #D80682 | Acciones principales, selección y acentos |
| brand-primary-strong | #B00064 | Hover, presión y texto magenta de mayor contraste |
| brand-accent | #7A1FA2 | Acento morado limitado, foco y detalles de marca |
| ink-primary | #0B153D | Títulos, texto principal e iconos |
| ink-secondary | #5F5360 | Texto secundario |
| canvas | #FFF7FA | Fondo general |
| surface | #FFFFFF | Cards, formularios y paneles |
| surface-brand | #FCE8F2 | Secciones destacadas y selección suave |
| border-default | #E5D5DF | Bordes y divisores |
| success | #1F7A45 | Confirmaciones correctas |
| success-surface | #EAF8EF | Fondo de confirmación |
| error | #B42318 | Errores y acciones destructivas |
| error-surface | #FDECEC | Fondo de error |
| warning | #8A6100 | Advertencias y límites próximos |
| warning-surface | #FFF5D6 | Fondo de advertencia |

Reglas:

- **[SPEC]** Ningún significado debe depender únicamente del color.
- **[VISUAL]** Todo estado utilizará color, texto e icono.
- **[VISUAL]** El magenta se reserva para acciones principales y selección; no debe colorear grandes bloques de texto.
- **[VISUAL]** Las acciones destructivas usarán rojo, no magenta.
- **[VISUAL]** El cuerpo del texto utilizará azul marino o gris oscuro, nunca rosa claro.

## 6. Tipografía

### 6.1 Familias

**[VISUAL] Encabezados editoriales:**

- Georgia, Times New Roman, serif.

**[VISUAL] Interfaz y texto general:**

- system-ui, Segoe UI, Roboto, Helvetica, Arial, sans-serif.

Estas familias no necesitan descargas, servicios externos ni dependencias nuevas.

**[NO IMPLEMENTAR]** No utilizar tipografía manuscrita para instrucciones, formularios, botones o datos. El estilo manuscrito se reserva al logo y, si se aprueba, a detalles decorativos no esenciales.

### 6.2 Escala

| Uso | Móvil | Escritorio |
|---|---:|---:|
| Título principal | 32/40 px | 48/56 px |
| Título de sección | 26/32 px | 34/42 px |
| Subtítulo | 20/28 px | 22/30 px |
| Texto normal | 16/24 px | 16/24 px |
| Texto auxiliar | 14/20 px | 14/20 px |
| Botón | 16/24 px | 16/24 px |

No se utilizará texto funcional menor de 14 px.

## 7. Espaciado y estructura

**[VISUAL]** Escala base:

- 4 px;
- 8 px;
- 12 px;
- 16 px;
- 24 px;
- 32 px;
- 48 px;
- 64 px.

Aplicación:

- margen lateral móvil: 16 px;
- margen lateral de tableta: 24 px;
- margen lateral de escritorio: 32 px;
- ancho máximo de contenido: 1,200 px;
- separación entre campos relacionados: 16 px;
- separación entre grupos: 24–32 px;
- separación entre secciones: 48 px en móvil y 64–72 px en escritorio;
- padding de cards: 16 px en móvil y 24 px en escritorio.

**[SPEC]** La composición debe conservar todas las funciones desde 320 px.

## 8. Botones

### 8.1 Primario

- Fondo brand-primary.
- Texto blanco.
- Forma redondeada tipo píldora.
- Altura mínima y área táctil objetivo de 44 px.
- Utilizado para la acción principal del contexto actual.

Reservar cita y Consultar mi cita pueden adoptar este tratamiento según la tarea que la persona esté realizando; ninguna se establece como CTA principal global para todo el sitio.

### 8.2 Secundario

- Fondo blanco.
- Borde brand-primary.
- Texto brand-primary-strong.

### 8.3 Terciario

- Sin contenedor dominante.
- Texto oscuro o magenta fuerte.
- Utilizado para volver, editar una selección o acciones de baja prioridad.

### 8.4 Destructivo

- Fondo o borde rojo.
- Etiqueta explícita, por ejemplo: Sí, cancelar cita.
- Nunca identificado solo mediante color o una X.

### 8.5 Estados

- Focus: contorno visible y separado del borde.
- Loading: conservar el ancho y mostrar una indicación textual como Procesando….
- Disabled: cambiar estilo y estado semántico; no depender solo de bajar la opacidad.
- Evitar envíos dobles desde la interfaz, manteniendo la autoridad de idempotencia en el backend.

## 9. Cards

**[VISUAL]**

- Fondo blanco.
- Radio de 16 px.
- Borde ligero.
- Sombra tenue, sin elevaciones excesivas.
- Títulos oscuros y jerarquía clara.
- Una card seleccionada usa borde magenta, fondo suave e icono de confirmación.
- Las cards de servicio pueden mostrar fotografía, nombre, duración y precio.
- Las cards de resumen muestran los datos en filas con etiquetas y valores.
- Las cards administrativas deben ser más compactas y utilizar menos decoración.

**[SPEC]** El precio, duración y nombre mostrados en una cita deben corresponder con el acuerdo conservado en esa cita.

**[NO IMPLEMENTAR]** No agregar categorías de servicios, búsqueda del catálogo ni conteos como 12 servicios encontrados; esos conceptos no existen en las specs.

## 10. Formularios

- Etiquetas persistentes y visibles.
- El placeholder nunca sustituye a la etiqueta.
- Indicación textual de campos obligatorios.
- Errores junto al campo y asociados programáticamente.
- Instrucciones antes del campo cuando el formato pueda resultar confuso.
- Conservar información no secreta después de un error recuperable.
- Limpiar contraseñas, TOTP, códigos, tokens y otros secretos cuando termine su periodo permitido.
- Una columna desde 320 px.
- Dos columnas solo en escritorio cuando los campos sean independientes y conserven un orden lógico.

### 10.1 Reservación

Los campos aprobados son:

- nombre;
- apellido;
- teléfono;
- correo electrónico;
- sucursal;
- servicio;
- fecha;
- horario;
- aceptación del aviso de privacidad;
- autorización de contacto;
- declaración de persona adulta responsable.

**[NO IMPLEMENTAR]** No incluir ¿Cómo te enteraste de nosotros?. No forma parte de la spec y supondría recopilar información adicional.

### 10.2 Autenticación

- Permitir pegar contraseñas y usar autocompletado.
- Permitir administradores de contraseñas.
- No imponer reglas visuales de mayúsculas, números o símbolos.
- No revelar qué credencial falló.
- Mostrar el QR o la clave TOTP solo mientras la configuración permanezca sin confirmar.
- Mostrar los diez códigos de recuperación una sola vez.

## 11. Navegación

### 11.1 Navegación pública de escritorio

Contenido mínimo:

1. Logo de Manita de Gato.
2. Servicios.
3. Reservar cita.
4. Consultar mi cita.

Reservar cita y Consultar mi cita deben ser fáciles de localizar. El peso visual de cada acción dependerá del contexto, sin declarar una de ellas como CTA principal global.

**[NO IMPLEMENTAR]**

- Modificar cita en el navbar.
- Cancelar cita en el navbar.
- Galería.
- Contacto por WhatsApp.
- Redes sociales.
- Tienda en línea.
- Direcciones o mapas no aprobados.

### 11.2 Navegación pública móvil

**[VISUAL]** La barra inferior con tres destinos es el patrón preferido:

- Servicios.
- Reservar.
- Consultar mi cita.

Cada destino debe conservar un nombre accesible completo y un área táctil cómoda. El estado activo se comunica mediante texto, icono y estilo, no solo mediante color.

Este patrón no es un requisito rígido. Durante la implementación y las pruebas podrá sustituirse por una solución responsive y accesible mejor si:

- conserva las mismas funciones;
- mantiene acceso claro a Reservar cita y Consultar mi cita;
- funciona desde 320 px;
- evita navegación duplicada;
- cumple teclado, foco, zoom y tecnologías de asistencia;
- no introduce una dependencia ni un requisito nuevo.

### 11.3 Navegación administrativa

Escritorio:

- Agenda.
- Bloqueos.
- Servicios, solo propietario.
- Personal, solo propietario.
- Historial, solo propietario.
- Mi seguridad.
- Cerrar sesión.

Móvil:

- encabezado compacto;
- un único menú desplegable o lateral con las mismas opciones;
- ninguna función autorizada puede desaparecer por falta de espacio.

## 12. Estados de interfaz

### 12.1 Loading

- Mantener visible el contexto de la tarea.
- Indicar qué operación está en proceso.
- Desactivar únicamente el control que produciría un envío duplicado.
- No extender la sesión mediante solicitudes automáticas.
- No mostrar esqueletos que simulen datos privados.

### 12.2 Vacío

- Título breve.
- Explicación concreta.
- Solo una acción ya aprobada cuando corresponda.
- No agregar funciones nuevas para llenar la pantalla.

Ejemplos válidos:

- no existen horarios disponibles ese día;
- no existen resultados para los filtros administrativos;
- no existe historial dentro del periodo seleccionado.

### 12.3 Error

- Error de campo junto al control correspondiente.
- Error general al inicio del bloque afectado.
- Los errores de código privado, credenciales, cuentas y enlaces deben conservar el mensaje genérico exigido.
- Los errores de disponibilidad deben distinguir formato inválido de horario válido ocupado.
- Los errores nunca incluyen trazas, SQL, proveedores ni identificadores internos.

### 12.4 Éxito

- Icono, título y texto; no depender únicamente del verde.
- Mostrar el resumen de la operación.
- Distinguir el éxito principal del resultado de las notificaciones.
- Un fallo de WhatsApp o correo no debe convertir una cita correctamente guardada en una cita fallida.

### 12.5 Notificaciones

Cada canal podrá representarse como:

- pendiente;
- aceptado por el proveedor;
- entregado;
- fallido.

Aceptado no debe etiquetarse como Entregado o Enviado correctamente.

## 13. Tratamiento del logo

El recurso actual es una imagen JPEG horizontal, sin transparencia y con texto adicional.

**[VISUAL]**

- Conservar proporciones.
- No estirar, inclinar ni aplicar sombras intensas.
- Mostrarlo sobre superficies claras.
- Texto alternativo: Manita de Gato.
- Conservar únicamente Manita de Gato y Salón de belleza como textos de marca.
- Omitir tienda en línea y el texto exterior Texcoco en la versión general para la web.
- Altura aproximada máxima: 64 px en escritorio y 52 px en móvil.
- Mantener espacio libre alrededor del óvalo.
- No repetir el logo varias veces en la misma vista.

**[PENDIENTE]**

- Conseguir o preparar una versión limpia con fondo transparente.
- Crear una variante simplificada para tamaños pequeños únicamente después de aprobarla.

El JPEG actual servirá como referencia y no como recurso final de producción.

## 14. Tratamiento de fotografías

### 14.1 Fotografía de uñas

Puede utilizarse como imagen principal de la reservación o como fotografía de un servicio, después de disponer de una versión limpia.

No debe publicarse con fecha, hora o texto superpuesto.

### 14.2 Fotografía de corte en capas

No se utilizará directamente porque contiene:

- texto incrustado;
- nombre de usuario;
- marca de cámara;
- otras marcas visibles;
- composición prediseñada;
- una persona fotografiada.

Solo podrá aprovecharse si existe una versión original limpia y se confirma la autorización para publicarla.

### 14.3 Reglas generales

- Utilizar fotografías reales autorizadas, no las imágenes de stock insertadas en los mockups.
- Confirmar derechos y consentimiento cuando aparezca una persona.
- Eliminar metadatos innecesarios antes de publicar.
- Evitar texto esencial dentro de imágenes.
- Usar una fotografía principal por pantalla como máximo.
- Usar relación 4:3 para cards y una composición horizontal adaptable para encabezados.
- Conservar el punto de interés al recortar.
- Fotografía informativa: texto alternativo descriptivo.
- Fotografía decorativa: alternativa vacía para evitar ruido al lector de pantalla.
- Las pantallas administrativas no utilizarán fotografías grandes.

## 15. Responsive

**[SPEC]**

- Toda función pública y administrativa debe funcionar desde 320 px.
- No debe existir desplazamiento horizontal general.
- No puede perderse contenido ni haber controles superpuestos.
- El zoom debe permanecer habilitado.
- Las tablas pueden desplazarse dentro de su contenedor solo cuando resulte indispensable.
- Todos los controles deben seguir disponibles en móvil.

**[PLAN]**

- Verificación en 320, 390, 768 y 1280 px.
- Diseño orientado primero a pantallas pequeñas.
- Área táctil objetivo de 44 × 44 px.
- Pruebas en Chromium, Firefox y WebKit.
- Revisión manual en Android y iPhone antes de publicar.

**[VISUAL]**

- 320–767 px: una columna.
- 768–1023 px: una o dos columnas según el contenido.
- 1024 px en adelante: formulario y resumen pueden compartir la vista.
- Calendario y horarios se apilan en móvil.
- Los horarios utilizan una cuadrícula fluida.
- Las cards de servicios pasan de varias columnas a lista o dos columnas en móvil.
- Las fotografías se recortan; nunca fuerzan el ancho de la página.

## 16. Accesibilidad

- Utilizar elementos nativos antes que ARIA.
- Todas las acciones deben funcionar con teclado.
- El foco debe ser visible.
- Las etiquetas deben permanecer visibles.
- Los errores deben estar asociados con sus campos.
- Los cambios importantes deben anunciarse a tecnologías de asistencia.
- Ningún significado dependerá solo del color.
- Los iconos deben acompañarse de texto cuando representen una acción.
- Respetar el zoom y la ampliación de texto.
- Mantener orden lógico de títulos y controles.
- Los modales, si se utilizan, deben administrar correctamente foco y cierre.
- Axe forma parte de la verificación, pero no sustituye la prueba manual.
- No se declarará conformidad completa con WCAG basándose únicamente en Axe.

## 17. Comportamiento visual de las citas

### 17.1 Reservar cita

**[VISUAL]** Flujo de tres pasos:

1. **Tu cita**
   - Sucursal.
   - Servicio activo.
   - Fecha.
   - Horario.
2. **Tus datos**
   - Nombre.
   - Apellido.
   - Teléfono.
   - Correo.
   - Tres consentimientos aprobados.
3. **Confirmar**
   - Resumen completo.
   - Posibilidad de volver a corregir una selección.
   - Acción explícita Confirmar mi cita.

Después se presenta el estado de éxito:

- código privado;
- resumen de la cita;
- estado individual de WhatsApp y correo;
- advertencia de conservar el código;
- acceso claro a Consultar mi cita.

**[NO IMPLEMENTAR]** La confirmación no mostrará accesos principales para modificar o cancelar. Esas acciones se ofrecen después de consultar la cita.

Los horarios mostrados deben provenir del sistema. Las imágenes de referencia que omiten 13:00–14:00 o 19:00 no deben copiarse: esos horarios son válidos cuando la agenda los permite.

### 17.2 Consultar mi cita

1. Mostrar un formulario dedicado.
2. Solicitar únicamente el código privado.
3. Ante un rechazo, mostrar el mensaje genérico aprobado.
4. Ante un código válido, mostrar:
   - servicio;
   - fecha;
   - horario;
   - sucursal;
   - duración;
   - precio;
   - estado;
   - teléfono y correo enmascarados.
5. Mientras la cita pueda modificarse o cancelarse, mostrar ambas acciones dentro del resultado.

No mostrar resultados de otras citas ni ofrecer búsquedas por nombre, teléfono o correo.

### 17.3 Modificar cita

1. Comenzar desde el resultado de Consultar mi cita.
2. Solicitar el teléfono registrado.
3. Después de verificarlo, permitir cambiar exclusivamente:
   - fecha;
   - horario;
   - sucursal;
   - servicio.
4. Conservar un resumen visible de la cita actual.
5. Mostrar alternativas únicamente cuando la solicitud era válida pero estaba ocupada.
6. Mostrar una revisión de los cambios antes de confirmar.
7. Mostrar el resultado actualizado y los estados de notificación.
8. No volver a mostrar el código privado.

### 17.4 Cancelar cita

1. Comenzar desde el resultado de Consultar mi cita.
2. Solicitar el teléfono registrado.
3. Mostrar el resumen de la cita.
4. Permitir un motivo opcional de hasta 250 caracteres.
5. Utilizar una acción destructiva explícita: Sí, cancelar cita.
6. Mostrar el resultado con estado cancelada.
7. Mostrar los resultados de WhatsApp y correo.
8. No mostrar el código privado.
9. El motivo no aparece en la consulta pública posterior.

## 18. Interfaz administrativa

### 18.1 Lenguaje visual compartido

- **[VISUAL]** Mantener la paleta, tipografía, espaciado y componentes del área pública.
- **[VISUAL]** Reducir fotografías y decoración para priorizar información y acciones del negocio.
- **[VISUAL]** Agenda, formularios y detalles utilizan superficies blancas y jerarquía compacta.
- **[SPEC]** Los permisos determinan qué navegación puede utilizar cada rol, sin sustituir la autorización del backend.
- **[VISUAL]** Los estados usan texto, icono y color; búsquedas y filtros aprobados aparecen antes de sus resultados.
- **[SPEC]** En móvil no desaparece ninguna acción autorizada. Los detalles pasan a filas apiladas y una tabla solo desplaza su propio contenedor cuando sea indispensable.
- **[SPEC]** Una sesión expirada conduce al acceso administrativo sin mantener información privada visible.

### 18.2 Acceso y activación

- **[SPEC]** El inicio de sesión solicita correo, contraseña y un TOTP válido o un código de recuperación válido. El cambio entre ambos códigos no omite ninguna otra credencial.
- **[SPEC]** Los rechazos de autenticación son genéricos; el estado bloqueado tampoco identifica qué credencial o cuenta falló.
- **[SPEC]** Recuperar la contraseña durante un bloqueo está permitido, pero no elimina, acorta ni prolonga el bloqueo original.
- **[SPEC]** La activación exige una contraseña de 12 a 128 caracteres que no aparezca en la lista bloqueada, sin imponer combinaciones de símbolos, números o mayúsculas.
- **[SPEC]** TOTP usa seis dígitos y periodos de 30 segundos mediante una aplicación compatible con el estándar, sin exigir una marca.
- **[SPEC]** Se muestran exactamente diez códigos de recuperación de 16 caracteres útiles en cuatro grupos de cuatro, una sola vez.
- **[PLAN]** El QR o la clave manual solo aparecen mientras la configuración no está confirmada; completar la activación no crea una sesión y conduce después al inicio de sesión.

### 18.3 Agenda y citas administrativas

- **[SPEC]** La agenda permite filtrar por fecha, sucursal y estado, y buscar por código privado, teléfono, nombre, apellido o fecha con las coincidencias aprobadas.
- **[SPEC]** El detalle muestra nombre, apellido, contacto, servicio, sucursal, fecha, horario, duración, precio y estado, pero nunca el código privado.
- **[SPEC]** Propietaria y Personal pueden crear, modificar y cancelar citas, registrar resultados, reenviar el código y reintentar notificaciones elegibles bajo las reglas de las specs.
- **[SPEC]** Crear una cita administrativa reúne los datos completos de la persona adulta responsable y su confirmación de privacidad; servicio, duración y precio proceden del catálogo vigente.
- **[SPEC]** Completar, marcar inasistencia, modificar, cancelar, reenviar o reintentar solo aparece o se habilita cuando el estado, el tiempo, el canal y el rol lo permiten.
- **[VISUAL]** El panel lateral de detalle y los diálogos de confirmación son patrones preferidos, no contratos sobre rutas o componentes.

### 18.4 Bloqueos de disponibilidad

- **[SPEC]** Propietaria y Personal pueden crear, editar y retirar bloqueos únicos, globales o de una sucursal, indicando inicio y fin alineados a 15 minutos.
- **[SPEC]** Los bloqueos pueden atravesar medianoche o varios días y deben rechazar conflictos con citas y redundancias entre bloqueos.
- **[VISUAL]** Lista, diálogo de edición, confirmación destructiva y presentación del conflicto son patrones de interacción.

### 18.5 Servicios

- **[SPEC]** Solo la Propietaria o el Propietario puede crear, editar, activar o desactivar servicios con nombre, descripción opcional, duración, precio y al menos una sucursal.
- **[SPEC]** Los cambios no alteran la instantánea de nombre, duración, precio y sucursal conservada en citas existentes.
- **[VISUAL]** La tabla compacta y la separación visual entre activos e inactivos pueden utilizarse como presentación; sus cantidades de ejemplo no son datos ni requisitos.

### 18.6 Personal y seguridad propia

- **[SPEC]** Solo la Propietaria o el Propietario invita, reenvía o cancela la invitación, fuerza el restablecimiento y desactiva al Personal.
- **[SPEC]** Solo puede existir una cuenta de Personal pendiente o activa; una cuenta desactivada no se reactiva y un acceso posterior requiere una invitación y cuenta nuevas.
- **[SPEC]** Cada cuenta gestiona únicamente su propia contraseña, correo, TOTP y códigos de recuperación mediante las credenciales exigidas.
- **[SPEC]** El Personal no administra servicios, precios, cuentas ajenas ni historial.

### 18.7 Historial administrativo

- **[SPEC]** Solo la Propietaria o el Propietario consulta el historial y filtra por cuenta, tipo de acción y periodo.
- **[SPEC]** Cada evento muestra únicamente cuenta responsable cuando esté identificada, acción, resultado, fecha, hora y referencia interna cuando corresponda.
- **[SPEC]** Los eventos no pueden editarse ni eliminarse individualmente y dejan de ser consultables al cumplir 12 meses.
- **[SPEC]** El historial no copia datos personales de clientas ni secretos, y una referencia de una cita retirada no permite recuperar sus datos.
- **[VISUAL]** Paginación, chips y panel de detalle son recursos de presentación y no cambian el contenido mínimo autorizado.

## 19. Elementos de las imágenes que no deben implementarse

### 19.1 Contradicen las specs o decisiones aprobadas

1. Modificar cita o Cancelar cita en el navbar.
2. Esas acciones directamente en la confirmación inicial.
3. Códigos privados cortos como MG7K3P; el código real debe cumplir al menos 128 bits de aleatoriedad.
4. Mostrar una notificación como entregada cuando el proveedor únicamente la aceptó.
5. El campo ¿Cómo te enteraste de nosotros?.
6. Ocultar el horario de 13:00 a 14:00 como si fuera comida.
7. Omitir las 19:00 como inicio válido cuando exista disponibilidad.
8. Descargar comprobantes; están fuera del MVP.
9. Hablar de varios profesionales; existe un solo profesional para las dos sucursales.
10. Presentar una tienda en línea como funcionalidad del sitio.
11. Bloquear de 13:00 a 14:00 como horario de comida; ese periodo permanece disponible si no existe otro conflicto.
12. Mostrar Resultado no registrado antes del retiro operativo; una cita pasada conserva Programada hasta que se registre un resultado o llegue su retiro.
13. Seleccionar o crear una ficha de Cliente en la cita administrativa; no existe un padrón de clientes y deben capturarse los datos aprobados de la persona adulta responsable.
14. Añadir Notas a una cita administrativa; ese campo no existe en la spec.
15. Elegir manualmente una duración de cita; la duración procede del servicio seleccionado.
16. Reintentar una notificación ya aceptada o entregada; solo un canal fallido y todavía elegible admite reintento.
17. Ofrecer un buscador, filtros, motivo limitado a 100 caracteres o una acción Todo el día para bloqueos; no están definidos en la spec.
18. Tratar la desactivación de un servicio como eliminación física o representarla únicamente mediante un icono de papelera.
19. Recomendar al menos 8 caracteres para la contraseña; el mínimo obligatorio es 12 y el máximo 128.
20. Mostrar códigos de recuperación de ocho caracteres o dos grupos; cada código requiere 16 caracteres útiles y cuatro grupos de cuatro.
21. Presentar Google Authenticator, Microsoft Authenticator u otra marca como obligatoria o preferida; la aplicación debe ser compatible con el estándar y no depender de una marca.
22. Reutilizar el QR estático del mockup; cada configuración pendiente genera su propio secreto y lo muestra solo dentro de ese flujo.
23. Sugerir que restablecer la contraseña permite entrar inmediatamente durante un bloqueo; el bloqueo conserva su vencimiento original.
24. Crear una bandeja mediante la campana de notificaciones; solo están aprobados los avisos por correo y las notificaciones de citas por sus canales definidos.
25. Describir a la cuenta propietaria como Acceso total al sistema; su autoridad se limita a las operaciones administrativas aprobadas y conserva las prohibiciones expresas de la spec.
26. Mostrar en el historial campos modificados, descripciones libres u otros detalles que excedan actor, acción, resultado, fecha, hora y referencia interna permitida.

### 19.2 Exceden la documentación aprobada

1. Categorías de servicios.
2. Buscador público de servicios.
3. Filtros por categoría.
4. Página detallada y galería individual por servicio.
5. Galería pública general.
6. Redes sociales.
7. Botones de contacto por WhatsApp.
8. Mapas y direcciones.
9. Fotografías de fachadas no proporcionadas.
10. Servicios, precios y duraciones inventados.
11. Recomendaciones de servicios después de reservar.
12. Contadores como 12 servicios encontrados.
13. Secciones de productos.
14. Funciones de comercio electrónico.
15. Perfil editable, fotografía de cuenta o personalización de avatares administrativos.
16. Directorio o expediente independiente de clientes.
17. Comentarios o notas internas sobre clientas o citas.
18. Filtros, búsquedas, contadores y atajos administrativos que las specs no exigen, salvo los filtros y búsquedas expresamente aprobados para agenda e historial.
19. Historial reciente separado dentro de la cuenta de Personal; cualquier acceso de este tipo tendría que ser solo de la Propietaria o el Propietario y usar exclusivamente el historial autorizado.

### 19.3 Mensajes o afirmaciones que necesitan aprobación comercial

No utilizar como hechos sin confirmación:

- Profesionales capacitados.
- Productos de calidad.
- Ambiente seguro y confiable.
- Resultados duraderos.
- Higiene y seguridad.
- Atención personalizada.
- Trato amable y cercano.
- Cualquier dirección, red social o dato de contacto mostrado en los mockups.
- Belleza que te hace sentir bien.
- Cuidado en cada detalle.
- Tu belleza, nuestra pasión.
- Cuidado, confianza y resultados.
- Transparencia para proteger lo que importa.

## 20. Puertas de recursos y contenido todavía pendientes

- Obtención o preparación de un logo limpio que conserve Manita de Gato y Salón de belleza y omita tienda en línea y el texto exterior Texcoco.
- Confirmación de derechos y consentimiento sobre las fotografías.
- Obtención de las fotografías originales sin fecha, texto, marcas ni composición incrustada.
- Aprobación de cualquier contenido comercial que se desee añadir fuera de las specs.
- No instalar tipografías, iconos, librerías visuales ni otras dependencias sin aprobación independiente.
- **[PENDIENTE]** Decidir si se renombran las siete imágenes administrativas con el prefijo `01`–`07`; es orden documental opcional y no bloquea implementación.
- **[PENDIENTE]** Las referencias administrativas son composiciones principalmente de escritorio. No se necesitan nuevos requisitos: su adaptación móvil debe derivarse de RNF-05/RNF-06 y de los planes, y validarse a 320, 390, 768 y 1280 píxeles CSS.
