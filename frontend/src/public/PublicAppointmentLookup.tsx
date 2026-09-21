import { useState, type FormEvent } from "react";

import { PublicAppointmentModification } from "./PublicAppointmentModification";
import { PublicAppointmentCancellation } from "./PublicAppointmentCancellation";

type PublicAppointment = {
  serviceName: string;
  branch: string;
  scheduledStart: string;
  durationMinutes: number;
  price: string;
  status: string;
  contact: {
    phone: string;
    email: string;
  };
};

type LookupState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "success"; appointment: PublicAppointment; privateCode: string };

const genericCredentialError = "No fue posible validar las credenciales de la cita.";

export function PublicAppointmentLookup() {
  const [privateCode, setPrivateCode] = useState("");
  const [state, setState] = useState<LookupState>({ kind: "idle" });
  const [isModifying, setIsModifying] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);

  async function submitLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (privateCode.trim() === "") {
      setState({ kind: "error", message: genericCredentialError });
      return;
    }

    setState({ kind: "loading" });
    try {
      const response = await fetch("/api/public/appointments/lookup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ privateCode }),
      });
      if (!response.ok) {
        setState({
          kind: "error",
          message: response.status === 429 ? "Intenta nuevamente más tarde." : genericCredentialError,
        });
        return;
      }

      const payload: unknown = await response.json();
      if (!isPublicAppointment(payload)) {
        setState({ kind: "error", message: "No fue posible consultar la cita. Intenta nuevamente." });
        return;
      }

      setPrivateCode("");
      setState({ kind: "success", appointment: payload, privateCode });
    } catch {
      setState({ kind: "error", message: "No fue posible consultar la cita. Intenta nuevamente." });
    }
  }

  function resetLookup() {
    setPrivateCode("");
    setIsModifying(false);
    setIsCancelling(false);
    setState({ kind: "idle" });
  }

  if (state.kind === "success") {
    if (isModifying) return <PublicAppointmentModification appointment={state.appointment} onBack={() => setIsModifying(false)} onUpdated={(appointment) => { setState({ ...state, appointment: { ...state.appointment, ...appointment } }); setIsModifying(false); }} privateCode={state.privateCode} />;
    if (isCancelling) return <PublicAppointmentCancellation appointment={state.appointment} onBack={() => setIsCancelling(false)} onCancelled={(appointment) => { setState({ ...state, appointment: { ...state.appointment, ...appointment } }); setIsCancelling(false); }} privateCode={state.privateCode} />;
    return <AppointmentResult appointment={state.appointment} onCancel={() => setIsCancelling(true)} onModify={() => setIsModifying(true)} onReset={resetLookup} />;
  }

  return (
    <div className="lookup-page">
      <section className="lookup-hero" aria-labelledby="lookup-title">
        <div className="lookup-hero__content">
          <p className="lookup-eyebrow">Gestiona tu reservación</p>
          <h1 id="lookup-title">Consulta tu cita</h1>
          <p className="lookup-hero__lead">Tu cita siempre a un clic. Ingresa el código privado que recibiste al reservar.</p>
          <form className="lookup-form" onSubmit={(event) => void submitLookup(event)} noValidate>
            <label className="lookup-form__label" htmlFor="private-code">Código privado</label>
            <div className="lookup-form__controls">
              <input
                autoComplete="off"
                className="lookup-form__input"
                disabled={state.kind === "loading"}
                id="private-code"
                name="privateCode"
                onChange={(event) => {
                  setPrivateCode(event.target.value);
                  if (state.kind === "error") setState({ kind: "idle" });
                }}
                spellCheck={false}
                type="text"
                value={privateCode}
              />
              <button className="booking-button booking-button--primary lookup-form__submit" disabled={state.kind === "loading"} type="submit">
                {state.kind === "loading" ? "Consultando…" : "Consultar cita"}
              </button>
            </div>
            <p className="lookup-form__privacy">Tu código se utiliza únicamente para localizar tu cita.</p>
            {state.kind === "loading" ? <p className="lookup-state" role="status">Consultando tu cita…</p> : null}
            {state.kind === "error" ? <p className="lookup-state lookup-state--error" role="alert">{state.message}</p> : null}
          </form>
          <aside className="lookup-code-help" aria-labelledby="lookup-code-help-title">
            <span aria-hidden="true">⌕</span>
            <div><h2 id="lookup-code-help-title">¿Dónde encuentro mi código?</h2><p>Se mostró al confirmar tu reservación y se envió por los canales registrados.</p></div>
          </aside>
        </div>
        <div className="lookup-hero__visual">
          <img src="/assets/brand/uñas.png" alt="Diseño de uñas de Manita de Gato" />
          <div><strong>Tu tiempo es valioso</strong><span>Consulta los detalles de tu cita en un solo lugar.</span></div>
        </div>
      </section>
    </div>
  );
}

function AppointmentResult({ appointment, onCancel, onModify, onReset }: { appointment: PublicAppointment; onCancel: () => void; onModify: () => void; onReset: () => void }) {
  const managementAllowed = canManageAppointment(appointment);
  return (
    <div className="lookup-page">
      <section className="lookup-result" aria-labelledby="lookup-result-title">
        <div className="lookup-result__heading">
          <div><p className="lookup-eyebrow">Resultado de tu consulta</p><h1 id="lookup-result-title">Tu cita está aquí</h1></div>
          <span className="lookup-result__found"><span aria-hidden="true">✓</span> Cita encontrada</span>
        </div>

        <div className="lookup-result__service">
          <LookupServiceImage serviceName={appointment.serviceName} />
          <div><span>Servicio</span><h2>{appointment.serviceName}</h2><p>{formatDuration(appointment.durationMinutes)} · ${appointment.price} MXN</p></div>
        </div>

        <dl className="lookup-details">
          <div><dt>Fecha</dt><dd>{formatDate(appointment.scheduledStart)}</dd></div>
          <div><dt>Horario</dt><dd>{formatTime(appointment.scheduledStart)}</dd></div>
          <div><dt>Sucursal</dt><dd>{formatBranch(appointment.branch)}</dd></div>
          <div><dt>Duración</dt><dd>{formatDuration(appointment.durationMinutes)}</dd></div>
          <div><dt>Precio acordado</dt><dd>${appointment.price} MXN</dd></div>
          <div><dt>Estado</dt><dd><span className={`lookup-status lookup-status--${appointment.status}`}>{formatStatus(appointment.status)}</span></dd></div>
        </dl>

        <section className="lookup-contact" aria-labelledby="lookup-contact-title">
          <div><p className="lookup-eyebrow">Datos de contacto protegidos</p><h2 id="lookup-contact-title">Contacto registrado</h2></div>
          <dl><div><dt>Teléfono</dt><dd>{appointment.contact.phone}</dd></div><div><dt>Correo electrónico</dt><dd>{appointment.contact.email}</dd></div></dl>
        </section>

        <div className="lookup-result__actions">
          <button className="booking-button" onClick={onReset} type="button">Consultar otra cita</button>
          {managementAllowed ? <div className="lookup-management-actions" aria-label="Acciones disponibles"><button className="booking-button" onClick={onModify} type="button">Modificar cita</button><button className="booking-button lookup-button--danger" onClick={onCancel} type="button">Cancelar cita</button></div> : null}
        </div>
      </section>
    </div>
  );
}

function LookupServiceImage({ serviceName }: { serviceName: string }) {
  const normalized = serviceName.toLocaleLowerCase("es-MX");
  const source = normalized.includes("uña") || normalized.includes("manicure") || normalized.includes("gel")
    ? "/assets/brand/uñas.png"
    : normalized.includes("pestaña")
      ? "/assets/brand/pestañas.png"
      : normalized.includes("cabello") || normalized.includes("corte") || normalized.includes("tinte") || normalized.includes("peinado")
        ? "/assets/brand/cabello.png"
        : null;
  return source ? <img src={source} alt="" aria-hidden="true" /> : <span className="lookup-result__image-fallback" aria-hidden="true">✦</span>;
}

function canManageAppointment(appointment: PublicAppointment): boolean {
  const start = new Date(appointment.scheduledStart).getTime();
  return appointment.status === "scheduled" && Number.isFinite(start) && start - Date.now() >= 60 * 60 * 1000;
}

function isPublicAppointment(value: unknown): value is PublicAppointment {
  if (typeof value !== "object" || value === null) return false;
  const appointment = value as Record<string, unknown>;
  const contact = appointment.contact;
  return typeof appointment.serviceName === "string"
    && typeof appointment.branch === "string"
    && typeof appointment.scheduledStart === "string"
    && typeof appointment.durationMinutes === "number"
    && typeof appointment.price === "string"
    && typeof appointment.status === "string"
    && typeof contact === "object"
    && contact !== null
    && typeof (contact as Record<string, unknown>).phone === "string"
    && typeof (contact as Record<string, unknown>).email === "string";
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Fecha no disponible" : new Intl.DateTimeFormat("es-MX", { dateStyle: "long", timeZone: "America/Mexico_City" }).format(date);
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Horario no disponible" : new Intl.DateTimeFormat("es-MX", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "America/Mexico_City" }).format(date);
}

function formatDuration(minutes: number): string {
  if (minutes === 60) return "1 hora";
  if (minutes > 0 && minutes % 60 === 0) return `${minutes / 60} horas`;
  return `${minutes} minutos`;
}

function formatBranch(branch: string): string {
  return branch === "texcoco" ? "Texcoco" : branch === "chiconcuac" ? "Chiconcuac" : branch;
}

function formatStatus(status: string): string {
  const statuses: Record<string, string> = {
    scheduled: "Programada",
    cancelled: "Cancelada",
    completed: "Completada",
    no_show: "No asistió",
    outcome_not_recorded: "Resultado no registrado",
  };
  return statuses[status] ?? status;
}
