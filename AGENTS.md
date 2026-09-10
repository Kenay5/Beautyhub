# AGENTS.md — BeautyHub

## Proyecto

BeautyHub es una aplicación web pública para gestionar citas de un negocio de belleza.
El proyecto utiliza Spec-Driven Development (SDD) en modalidad Spec-Anchored.
Las especificaciones vigentes definen el comportamiento esperado del sistema.

## Fuente de verdad

- Lee `docs/constitution.md` antes de realizar cualquier cambio.
- Lee la spec activa en `specs/` antes de planificar o modificar código.
- Si todavía no existe una spec activa, limita el trabajo a preparar y aprobar la primera spec; no planifiques ni implementes código funcional.
- La constitución contiene principios innegociables; ninguna spec, plan o implementación puede contradecirla.
- La jerarquía de autoridad es: constitución, spec activa aprobada, plan aprobado, implementación y tests.
- Ante requisitos ambiguos que afecten comportamiento, datos, seguridad o arquitectura, detente y solicita aclaración.
- No inventes requisitos para completar información faltante.

## Arquitectura

- Mantén la lógica de negocio separada de la interfaz y de los detalles de infraestructura.
- Usa la solución más simple que satisfaga la spec.
- No añadas dependencias, patrones, abstracciones o infraestructura sin necesidad justificada.
- Los datos persistentes del negocio deben almacenarse en PostgreSQL.

## Código y estilo

- Código, identificadores, commits y mensajes técnicos en inglés.
- Contenido visible para usuarios de BeautyHub en español.
- Prioriza código legible y explícito sobre soluciones innecesariamente complejas.
- No realices refactors ni cambios fuera del alcance de la tarea activa.

## Seguridad

- Trata toda entrada externa como no confiable y valídala.
- Nunca expongas secretos, credenciales, tokens, datos sensibles ni detalles internos.
- Nunca versiones archivos `.env` ni escribas secretos directamente en el código.
- Ninguna operación administrativa o dato privado puede quedar públicamente accesible sin autorización explícita.
- No uses datos personales reales de clientas en código, tests, fixtures, documentación o prompts.

## Specs

- No modifiques `docs/constitution.md` ni archivos dentro de `specs/` salvo petición explícita.
- Todo cambio funcional importante debe comenzar actualizando y aprobando la spec correspondiente.
- Una spec se considera activa únicamente después de la aprobación explícita del responsable del proyecto.
- Un plan describe cómo implementar la spec; no puede introducir, ampliar ni modificar sus requisitos.
- Implementa únicamente el alcance definido por la spec y la tarea activa.

## Flujo de trabajo

- Trabaja una tarea verificable a la vez.
- Antes de una tarea no trivial, presenta un plan breve y espera aprobación antes de modificar código.
- Si una decisión no está respaldada por la constitución y la spec activa, solicita aclaración; la aprobación de un plan no sustituye la aprobación de requisitos.
- No instales ni elimines dependencias sin aprobación explícita.

## Tests y verificación

- Toda regla de negocio crítica debe tener pruebas automatizadas.
- Todo bug corregido debe incorporar una prueba automatizada que reproduzca el fallo.
- Los tests existentes deben pasar antes de aceptar cambios.
- Ejecuta las verificaciones definidas por el proyecto antes de considerar terminada una tarea.
- Una tarea solo está terminada cuando cumple su spec, sus criterios de aceptación y las verificaciones correspondientes.

## Al terminar cualquier tarea

- Resume qué cambiaste y por qué.
- Indica los archivos modificados.
- Reporta las pruebas o verificaciones ejecutadas y su resultado.
- Señala cualquier riesgo, supuesto, deuda o decisión pendiente.
- No declares una tarea completada si alguna verificación requerida falla.
