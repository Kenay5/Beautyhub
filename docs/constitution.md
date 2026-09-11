# BeautyHub — Constitución

1. **Simplicidad:** usar el stack y la arquitectura más simples que satisfagan la spec; toda complejidad o dependencia nueva debe justificarse.
2. **Spec-Anchored:** la spec vigente es el contrato del comportamiento esperado; todo cambio funcional importante comienza actualizando y aprobando la spec.
3. **Sin requisitos inventados:** ante una ambigüedad que afecte comportamiento, datos, seguridad o arquitectura, detenerse y pedir aclaración.
4. **Separación de responsabilidades:** la lógica de negocio no debe depender de la interfaz, permitiendo cambiar web/API sin reescribir las reglas del dominio.
5. **Tests:** toda regla de negocio crítica y todo bug corregido deben tener una prueba automatizada; los tests existentes deben pasar antes de aceptar cambios.
6. **Persistencia:** los datos persistentes del negocio deben almacenarse en PostgreSQL; no usar almacenamiento temporal como sustituto en producción.
7. **Integridad de datos:** las restricciones importantes deben protegerse en la capa apropiada y no depender únicamente de validaciones del frontend.
8. **Seguridad por defecto:** validar toda entrada externa, aplicar autenticación, autorización y mínimo privilegio cuando corresponda, y no exponer secretos, credenciales, datos sensibles ni detalles internos.
9. **Sitio público:** ninguna operación administrativa ni dato privado debe quedar accesible públicamente sin autorización explícita.
10. **Secretos:** `.env`, claves, tokens y credenciales nunca se versionan ni se escriben directamente en el código.
11. **Código comprensible:** ningún cambio generado por IA se acepta sin revisión humana; el responsable debe poder explicar su propósito y funcionamiento.
12. **Cambios pequeños:** implementar una tarea verificable a la vez y evitar refactors o funcionalidades fuera del alcance aprobado.
13. **Idioma:** código, identificadores, commits, logs y mensajes técnicos en inglés; contenido visible para usuarios de BeautyHub en español.
14. **Verificación:** una tarea no está terminada hasta cumplir su spec, criterios de aceptación y verificaciones correspondientes.
15. **Interfaz inclusiva y adaptable:** toda interfaz pública y administrativa debe conservar su contenido y funciones en pantallas desde 320 píxeles CSS, permitir el uso con teclado, zoom y tecnologías de asistencia básicas, no comunicar significado únicamente mediante color y verificarse en los navegadores y dispositivos representativos definidos por las specs vigentes.
