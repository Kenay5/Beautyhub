import { FormEvent, useEffect, useRef, useState } from "react";

type AuditAction =
  | "login"
  | "account_locked"
  | "logout"
  | "account_activation"
  | "staff_invitation"
  | "staff_deactivation"
  | "password_change"
  | "password_recovery"
  | "email_change"
  | "totp_replacement"
  | "recovery_code_regeneration"
  | "appointment_created"
  | "appointment_modified"
  | "appointment_cancelled"
  | "appointment_result_recorded"
  | "appointment_private_code_resent"
  | "availability_block_created"
  | "availability_block_modified"
  | "availability_block_deleted"
  | "service_created"
  | "service_modified"
  | "service_activated"
  | "service_deactivated"
  | "authorization_denied";

type HistoryEvent = {
  eventId: number;
  actorAccountId: number | null;
  action: AuditAction;
  result: "succeeded" | "failed" | "denied";
  occurredAt: string;
  targetReference: string | null;
};

type HistoryResponse = {
  events: HistoryEvent[];
  accountIds: number[];
};

type HistoryFilters = {
  accountId: string;
  action: string;
  fromDate: string;
  toDate: string;
};

const EMPTY_FILTERS: HistoryFilters = {
  accountId: "",
  action: "",
  fromDate: "",
  toDate: "",
};

const ACTIONS: readonly { value: AuditAction; label: string }[] = [
  { value: "login", label: "Inicio de sesión" },
  { value: "account_locked", label: "Cuenta bloqueada" },
  { value: "logout", label: "Cierre de sesión" },
  { value: "account_activation", label: "Activación de cuenta" },
  { value: "staff_invitation", label: "Invitación de personal" },
  { value: "staff_deactivation", label: "Desactivación de personal" },
  { value: "password_change", label: "Cambio de contraseña" },
  { value: "password_recovery", label: "Recuperación de contraseña" },
  { value: "email_change", label: "Cambio de correo" },
  { value: "totp_replacement", label: "Reemplazo de verificación" },
  { value: "recovery_code_regeneration", label: "Regeneración de códigos" },
  { value: "appointment_created", label: "Cita creada" },
  { value: "appointment_modified", label: "Cita modificada" },
  { value: "appointment_cancelled", label: "Cita cancelada" },
  { value: "appointment_result_recorded", label: "Resultado registrado" },
  { value: "appointment_private_code_resent", label: "Aviso de cita reenviado" },
  { value: "availability_block_created", label: "Bloqueo creado" },
  { value: "availability_block_modified", label: "Bloqueo modificado" },
  { value: "availability_block_deleted", label: "Bloqueo eliminado" },
  { value: "service_created", label: "Servicio creado" },
  { value: "service_modified", label: "Servicio modificado" },
  { value: "service_activated", label: "Servicio activado" },
  { value: "service_deactivated", label: "Servicio desactivado" },
  { value: "authorization_denied", label: "Operación no autorizada" },
];

export function AdministrativeHistoryPanel({
  onSessionUnavailable,
}: {
  onSessionUnavailable: () => void;
}) {
  const [filters, setFilters] = useState<HistoryFilters>(EMPTY_FILTERS);
  const [events, setEvents] = useState<readonly HistoryEvent[]>([]);
  const [accountIds, setAccountIds] = useState<readonly number[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<HistoryEvent | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const detailTriggerRef = useRef<HTMLButtonElement | null>(null);

  async function loadHistory(nextFilters: HistoryFilters, signal?: AbortSignal) {
    setLoading(true);
    setError(null);
    try {
      const query = new URLSearchParams();
      if (nextFilters.accountId) query.set("accountId", nextFilters.accountId);
      if (nextFilters.action) query.set("action", nextFilters.action);
      if (nextFilters.fromDate) query.set("fromDate", nextFilters.fromDate);
      if (nextFilters.toDate) query.set("toDate", nextFilters.toDate);
      const suffix = query.size ? `?${query.toString()}` : "";
      const response = await fetch(`/api/admin/history${suffix}`, {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
        signal,
      });
      if (response.status === 401) {
        onSessionUnavailable();
        return;
      }
      if (response.status === 403) {
        setError("No tienes permiso para consultar el historial administrativo.");
        return;
      }
      if (!response.ok) throw new Error("history query failed");
      const payload: unknown = await response.json();
      if (!isHistoryResponse(payload)) throw new Error("history response invalid");
      setEvents(payload.events);
      setAccountIds(payload.accountIds);
    } catch {
      if (!signal?.aborted) {
        setError("No fue posible consultar el historial. Inténtalo de nuevo.");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadHistory(EMPTY_FILTERS, controller.signal);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return;
    if (selectedEvent !== null && !dialog.open) dialog.showModal();
    if (selectedEvent === null && dialog.open) dialog.close();
  }, [selectedEvent]);

  async function submitFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (filters.fromDate && filters.toDate && filters.fromDate > filters.toDate) {
      setError("El periodo indicado no es válido.");
      return;
    }
    await loadHistory(filters);
  }

  async function showEvent(eventId: number, trigger: HTMLButtonElement) {
    detailTriggerRef.current = trigger;
    setDetailLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/admin/history/${eventId}`, {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
      });
      if (response.status === 401) {
        onSessionUnavailable();
        return;
      }
      if (response.status === 403) {
        setError("No tienes permiso para consultar el historial administrativo.");
        return;
      }
      if (!response.ok) throw new Error("history event query failed");
      const payload: unknown = await response.json();
      if (!isHistoryEvent(payload)) throw new Error("history event response invalid");
      setSelectedEvent(payload);
    } catch {
      setError("No fue posible abrir el evento. Inténtalo de nuevo.");
    } finally {
      setDetailLoading(false);
    }
  }

  function resetFilters() {
    setFilters(EMPTY_FILTERS);
    void loadHistory(EMPTY_FILTERS);
  }

  return (
    <main className="admin-history-page">
      <header className="admin-history-header">
        <p className="admin-history-eyebrow">Administración</p>
        <h1>Historial administrativo</h1>
        <p>Consulta acciones registradas y filtra por cuenta, tipo y periodo.</p>
      </header>

      <section className="admin-history-card" aria-labelledby="admin-history-title">
        <h2 id="admin-history-title" className="admin-history-visually-hidden">
          Filtros y resultados del historial
        </h2>
        <form className="admin-history-filters" onSubmit={(event) => void submitFilters(event)}>
          <div className="admin-history-field">
            <label htmlFor="history-from-date">Desde</label>
            <input
              id="history-from-date"
              type="date"
              value={filters.fromDate}
              onChange={(event) => setFilters({ ...filters, fromDate: event.target.value })}
            />
          </div>
          <div className="admin-history-field">
            <label htmlFor="history-to-date">Hasta</label>
            <input
              id="history-to-date"
              type="date"
              value={filters.toDate}
              onChange={(event) => setFilters({ ...filters, toDate: event.target.value })}
            />
          </div>
          <div className="admin-history-field">
            <label htmlFor="history-account">Cuenta</label>
            <select
              id="history-account"
              value={filters.accountId}
              onChange={(event) => setFilters({ ...filters, accountId: event.target.value })}
            >
              <option value="">Todas las cuentas</option>
              {accountIds.map((accountId) => (
                <option key={accountId} value={accountId}>
                  Cuenta {accountId}
                </option>
              ))}
            </select>
          </div>
          <div className="admin-history-field">
            <label htmlFor="history-action">Tipo de acción</label>
            <select
              id="history-action"
              value={filters.action}
              onChange={(event) => setFilters({ ...filters, action: event.target.value })}
            >
              <option value="">Todas las acciones</option>
              {ACTIONS.map((action) => (
                <option key={action.value} value={action.value}>
                  {action.label}
                </option>
              ))}
            </select>
          </div>
          <div className="admin-history-filter-actions">
            <button type="submit" disabled={loading}>
              {loading ? "Consultando…" : "Consultar"}
            </button>
            <button
              className="admin-history-secondary"
              type="button"
              onClick={resetFilters}
              disabled={loading}
            >
              Limpiar filtros
            </button>
          </div>
        </form>

        {error ? <p className="admin-history-message admin-history-message--error" role="alert">{error}</p> : null}
        {loading ? <p className="admin-history-message" role="status">Consultando el historial…</p> : null}
        {!loading && !error && events.length === 0 ? (
          <p className="admin-history-message" role="status">No hay eventos en el periodo seleccionado.</p>
        ) : null}

        {!loading && events.length > 0 ? (
          <>
          <p className="admin-history-scroll-hint">Desliza la tabla horizontalmente para consultar todas las columnas.</p>
          <div className="admin-history-table-scroll" role="region" aria-label="Resultados del historial" tabIndex={0}>
            <table className="admin-history-table">
              <caption className="admin-history-visually-hidden">Eventos administrativos encontrados</caption>
              <thead>
                <tr>
                  <th scope="col">Fecha y hora</th>
                  <th scope="col">Cuenta</th>
                  <th scope="col">Tipo de acción</th>
                  <th scope="col">Resultado</th>
                  <th scope="col">Referencia</th>
                  <th scope="col">Detalle</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.eventId}>
                    <td>{formatDateTime(event.occurredAt)}</td>
                    <td>{event.actorAccountId === null ? "Sin cuenta identificada" : `Cuenta ${event.actorAccountId}`}</td>
                    <td>{actionLabel(event.action)}</td>
                    <td><span className={`admin-history-result admin-history-result--${event.result}`}>{resultLabel(event.result)}</span></td>
                    <td>{event.targetReference ?? "—"}</td>
                    <td>
                      <button
                        className="admin-history-detail-button"
                        type="button"
                        aria-label={`Ver evento ${event.eventId}`}
                        disabled={detailLoading}
                        onClick={(clickEvent) => void showEvent(event.eventId, clickEvent.currentTarget)}
                      >
                        Ver
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        ) : null}

        <aside className="admin-history-retention" role="note">
          <span aria-hidden="true">i</span>
          <p>
            <strong>Solo consulta.</strong> Los eventos no pueden modificarse ni eliminarse desde esta pantalla.
            <br />El historial se conserva durante 12 meses.
          </p>
        </aside>
      </section>

      <dialog
        className="admin-history-dialog"
        ref={dialogRef}
        aria-labelledby="history-detail-title"
        onClose={() => {
          setSelectedEvent(null);
          detailTriggerRef.current?.focus();
        }}
      >
        {selectedEvent ? (
          <>
            <h2 id="history-detail-title">Detalle del evento</h2>
            <dl>
              <div><dt>Fecha y hora</dt><dd>{formatDateTime(selectedEvent.occurredAt)}</dd></div>
              <div><dt>Cuenta</dt><dd>{selectedEvent.actorAccountId === null ? "Sin cuenta identificada" : `Cuenta ${selectedEvent.actorAccountId}`}</dd></div>
              <div><dt>Tipo de acción</dt><dd>{actionLabel(selectedEvent.action)}</dd></div>
              <div><dt>Resultado</dt><dd>{resultLabel(selectedEvent.result)}</dd></div>
              <div><dt>Referencia</dt><dd>{selectedEvent.targetReference ?? "—"}</dd></div>
            </dl>
            <button type="button" onClick={() => setSelectedEvent(null)}>Cerrar</button>
          </>
        ) : null}
      </dialog>
    </main>
  );
}

function isHistoryResponse(value: unknown): value is HistoryResponse {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    Array.isArray(candidate.events) && candidate.events.every(isHistoryEvent) &&
    Array.isArray(candidate.accountIds) && candidate.accountIds.every((id) => Number.isSafeInteger(id) && id > 0)
  );
}

function isHistoryEvent(value: unknown): value is HistoryEvent {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    Number.isSafeInteger(candidate.eventId) && Number(candidate.eventId) > 0 &&
    (candidate.actorAccountId === null || (Number.isSafeInteger(candidate.actorAccountId) && Number(candidate.actorAccountId) > 0)) &&
    ACTIONS.some((action) => action.value === candidate.action) &&
    (candidate.result === "succeeded" || candidate.result === "failed" || candidate.result === "denied") &&
    typeof candidate.occurredAt === "string" && Number.isFinite(Date.parse(candidate.occurredAt)) &&
    (candidate.targetReference === null || typeof candidate.targetReference === "string")
  );
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("es-MX", {
    timeZone: "America/Mexico_City",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function actionLabel(action: AuditAction): string {
  return ACTIONS.find((item) => item.value === action)?.label ?? "Acción administrativa";
}

function resultLabel(result: HistoryEvent["result"]): string {
  if (result === "succeeded") return "Exitoso";
  if (result === "failed") return "Fallido";
  return "Rechazado";
}
