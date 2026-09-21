# PostgreSQL integration tests

The integration suite uses a real PostgreSQL database named `beautyhub_test`.
Do not point it at a development or production database. Test data is created
inside a transaction and rolled back.

Create an empty local database named `beautyhub_test` in PostgreSQL. Then run
the local PowerShell helper from the repository root. It requests the password
without displaying or storing it, sets `BEAUTYHUB_TEST_DATABASE_URL` only for
the test process, and removes it on exit:

```powershell
.\backend\scripts\run_postgres_integration_tests.ps1
```

To run only one integration test, pass its path inside
`backend/tests/integration`:

```powershell
.\backend\scripts\run_postgres_integration_tests.ps1 -TestTarget backend/tests/integration/test_schedule_concurrency.py
```

The integration test refuses a missing URL, a non-PostgreSQL driver, or a
database name other than `beautyhub_test` before connecting.
