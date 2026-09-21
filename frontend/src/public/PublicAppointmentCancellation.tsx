import { useState, type FormEvent } from "react";

type PublicAppointment = {
  serviceName: string;
  branch: string;
  scheduledStart: string;
  durationMinutes: number;
  price: string;
  status: string;
};
type NotificationStatus = { channel: string; status: string };

type CancellationState =
  | { kind: "verification" }
  | { kind: "confirmation" }
  | { kind: "submitting" }
  | { kind: "error"; step: "verification" | "confirmation"; message: string }
  | { kind: "success"; appointment: PublicAppointment; notifications: NotificationStatus[] };

const genericCredentialError = "No fue posible validar las credenciales de la cita.";

export function PublicAppointmentCancellation({ appointment, privateCode, onBack, onCancelled }: {
  appointment: PublicAppointment;
  privateCode: string;
  onBack: () => void;
  onCancelled: (appointment: PublicAppointment) => void;
}) {
  const [phone, setPhone] = useState("");
  const [reason, setReason] = useState("");
  const [state, setState] = useState<CancellationState>({ kind: "verification" });

  function continueToConfirmation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (phone.trim() === "") {
      setState({ kind: "error", step: "verification", message: "Ingresa el número telefónico con el que registraste tu cita." });
      return;
    }
    setState({ kind: "confirmation" });
  }

  async function submitCancellation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setState({ kind: "submitting" });
    try {
      const response = await fetch("/api/public/appointments/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ privateCode, phone, reason }),
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        setState({ kind: "error", step: "confirmation", message: response.status === 404 ? genericCredentialError : errorMessage(payload) });
        return;
      }
      if (!isCancellationResponse(payload)) {
        setState({ kind: "error", step: "confirmation", message: "No fue posible cancelar la cita. Intenta nuevamente." });
        return;
      }
      setState({ kind: "success", appointment: payload.appointment, notifications: payload.notifications });
    } catch {
      setState({ kind: "error", step: "confirmation", message: "No fue posible cancelar la cita. Intenta nuevamente." });
    }
  }

  if (state.kind === "success") {
    return (
      <div className="lookup-page">
        <section className="lookup-cancellation lookup-cancellation--success" aria-labelledby="cancellation-success-title">
          <div className="cancellation-success-icon" aria-hidden="true">✓</div>
          <p className="lookup-eyebrow">Cancelación confirmada</p>
          <h1 id="cancellation-success-title">Tu cita ha sido cancelada</h1>
          <p className="lookup-cancellation__lead">Tu horario quedó liberado. Conservamos el registro de la cita conforme a nuestro servicio.</p>
          <AppointmentSummary appointment={state.appointment} />
          <section className="cancellation-channels" aria-labelledby="cancellation-channels-title">
            <h2 id="cancellation-channels-title">Confirmación por tus canales registrados</h2>
            <p>La confirmación de cancelación corresponde a tus canales registrados.</p>
            <ul>{state.notifications.map((notification) => <li key={notification.channel}>{formatChannel(notification.channel)}: {formatNotificationStatus(notification.status)}</li>)}</ul>
          </section>
          <button className="booking-button booking-button--primary" onClick={() => onCancelled(state.appointment)} type="button">Volver a mi cita</button>
        </section>
      </div>
    );
  }

  if (state.kind === "confirmation" || state.kind === "submitting" || (state.kind === "error" && state.step === "confirmation")) {
    const isSubmitting = state.kind === "submitting";
    return (
      <div className="lookup-page">
        <section className="lookup-cancellation" aria-labelledby="cancellation-confirmation-title">
          <p className="lookup-eyebrow">Cancelar cita</p>
          <h1 id="cancellation-confirmation-title">¿Deseas cancelar tu cita?</h1>
          <p className="lookup-cancellation__lead">Esta acción liberará el horario. Revisa los datos antes de continuar.</p>
          <AppointmentSummary appointment={appointment} />
          <form className="cancellation-form" onSubmit={(event) => void submitCancellation(event)} noValidate>
            <label className="booking-label" htmlFor="cancellation-reason">Motivo de cancelación <span>(opcional)</span></label>
            <textarea className="booking-input cancellation-form__reason" disabled={isSubmitting} id="cancellation-reason" maxLength={250} name="reason" onChange={(event) => setReason(event.target.value)} value={reason} aria-describedby="cancellation-reason-help" />
            <p className="cancellation-form__hint" id="cancellation-reason-help">Si lo deseas, comparte un motivo de hasta 250 caracteres.</p>
            {state.kind === "error" ? <p className="lookup-state lookup-state--error" role="alert">{state.message}</p> : null}
            <div className="cancellation-actions">
              <button className="booking-button" disabled={isSubmitting} onClick={onBack} type="button">Regresar</button>
              <button className="booking-button lookup-button--danger" disabled={isSubmitting} type="submit">{isSubmitting ? "Cancelando…" : "Sí, cancelar cita"}</button>
            </div>
          </form>
        </section>
      </div>
    );
  }

  return (
    <div className="lookup-page">
      <section className="lookup-cancellation" aria-labelledby="cancellation-identity-title">
        <p className="lookup-eyebrow">Cancelar cita</p>
        <h1 id="cancellation-identity-title">Verifiquemos tu identidad</h1>
        <p className="lookup-cancellation__lead">Para proteger tu cita, ingresa el número telefónico que registraste al reservar.</p>
        <form className="cancellation-form" onSubmit={continueToConfirmation} noValidate>
          <label className="booking-label" htmlFor="cancellation-phone">Número telefónico</label>
          <input autoComplete="tel" className="booking-input" id="cancellation-phone" inputMode="tel" name="phone" onChange={(event) => setPhone(event.target.value)} type="tel" value={phone} />
          {state.kind === "error" ? <p className="lookup-state lookup-state--error" role="alert">{state.message}</p> : null}
          <div className="cancellation-actions">
            <button className="booking-button" onClick={onBack} type="button">Regresar</button>
            <button className="booking-button booking-button--primary" type="submit">Continuar a la cancelación</button>
          </div>
        </form>
      </section>
    </div>
  );
}

function AppointmentSummary({ appointment }: { appointment: PublicAppointment }) {
  return (
    <dl className="cancellation-summary">
      <div><dt>Servicio</dt><dd>{appointment.serviceName}</dd></div>
      <div><dt>Sucursal</dt><dd>{formatBranch(appointment.branch)}</dd></div>
      <div><dt>Fecha</dt><dd>{formatDate(appointment.scheduledStart)}</dd></div>
      <div><dt>Horario</dt><dd>{formatTime(appointment.scheduledStart)}</dd></div>
      <div><dt>Duración y precio</dt><dd>{formatDuration(appointment.durationMinutes)} · ${appointment.price} MXN</dd></div>
      <div><dt>Estado</dt><dd><span className="lookup-status lookup-status--cancelled">{formatStatus(appointment.status)}</span></dd></div>
    </dl>
  );
}

function isCancellationResponse(value: unknown): value is { appointment: PublicAppointment; notifications: NotificationStatus[] } {
  if (typeof value !== "object" || value === null || !("appointment" in value) || !("notifications" in value)) return false;
  const appointment = (value as { appointment: unknown }).appointment;
  if (typeof appointment !== "object" || appointment === null) return false;
  const candidate = appointment as Record<string, unknown>;
  return typeof candidate.serviceName === "string" && typeof candidate.branch === "string" && typeof candidate.scheduledStart === "string" && typeof candidate.durationMinutes === "number" && typeof candidate.price === "string" && typeof candidate.status === "string" && isNotificationStatuses((value as Record<string, unknown>).notifications);
}
function isNotificationStatuses(value: unknown): value is NotificationStatus[] { return Array.isArray(value) && value.every((item) => typeof item === "object" && item !== null && (((item as Record<string, unknown>).channel === "email") || (item as Record<string, unknown>).channel === "whatsapp") && ["pending", "accepted", "delivered", "failed"].includes((item as Record<string, unknown>).status as string)); }
function formatChannel(value: string): string { return value === "whatsapp" ? "WhatsApp" : "Correo electrónico"; }
function formatNotificationStatus(value: string): string { return value === "failed" ? "No se pudo enviar" : value === "delivered" ? "Entregado" : value === "accepted" ? "Aceptado por el canal" : "Pendiente"; }

function errorMessage(value: unknown): string {
  if (typeof value === "object" && value !== null && typeof (value as Record<string, unknown>).detail === "string") return (value as Record<string, string>).detail;
  return "No fue posible cancelar la cita. Intenta nuevamente.";
}

function formatDate(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? "Fecha no disponible" : new Intl.DateTimeFormat("es-MX", { dateStyle: "long", timeZone: "America/Mexico_City" }).format(date); }
function formatTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? "Horario no disponible" : new Intl.DateTimeFormat("es-MX", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "America/Mexico_City" }).format(date); }
function formatDuration(minutes: number): string { return minutes === 60 ? "1 hora" : minutes > 0 && minutes % 60 === 0 ? `${minutes / 60} horas` : `${minutes} minutos`; }
function formatBranch(branch: string): string { return branch === "texcoco" ? "Texcoco" : branch === "chiconcuac" ? "Chiconcuac" : branch; }
function formatStatus(status: string): string { return status === "cancelled" ? "Cancelada" : status; }
