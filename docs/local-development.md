# Configuración local de BeautyHub

La configuración local usa el archivo .env, que está ignorado por Git. No copies sus valores a documentación, commits ni mensajes.

## Configurar una sola vez

Desde la raíz del repositorio, ejecuta:

    .\backend\scripts\configure_dev_environment.ps1

El script usa postgres en 127.0.0.1:5432, crea URLs para beautyhub_dev y beautyhub_test, solicita la contraseña como entrada segura y genera una master key aleatoria de 256 bits. La contraseña y la master key nunca se imprimen.

## Iniciar una nueva terminal

En cada nueva sesión de PowerShell, carga las variables sin reconstruirlas:

    . .\backend\scripts\load_dev_environment.ps1

Después puedes iniciar el backend con:

    .\.venv\Scripts\python.exe -m uvicorn backend.app.web.app:app --reload

El harness de integración carga automáticamente .env si existe. Por ejemplo:

    .\backend\scripts\run_postgres_integration_tests.ps1 -TestTarget "backend/tests/integration/test_public_appointment_reschedule.py"

Si .env falta, el harness conserva su comportamiento anterior y solicita la contraseña de forma segura. Producción no usa este archivo ni cambia sus reglas de configuración.
