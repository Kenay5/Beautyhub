import { useEffect, useState, type FormEvent } from "react";

type Branch = "chiconcuac" | "texcoco";

type PublicService = {
  name: string;
  duration_minutes: number;
  price: string;
};

type PublicAppointment = {
  serviceName: string;
  branch: string;
  scheduledStart: string;
  durationMinutes: number;
  price: string;
  status: string;
};
type NotificationStatus = { channel: string; status: string };

type RequestState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string; alternatives: string[]; requiresDifferentDate: boolean }
  | { kind: "success"; appointment: PublicAppointment; notifications: NotificationStatus[] };

const branches: Array<{ id: Branch; name: string }> = [
  { id: "texcoco", name: "Texcoco" },
  { id: "chiconcuac", name: "Chiconcuac" },
];

const genericCredentialError = "No fue posible validar las credenciales de la cita.";

export function PublicAppointmentModification({ appointment, privateCode, onBack, onUpdated }: {
  appointment: PublicAppointment;
  privateCode: string;
  onBack: () => void;
  onUpdated: (appointment: PublicAppointment) => void;
}) {
  const initialBranch = isBranch(appointment.branch) ? appointment.branch : "texcoco";
  const [phone, setPhone] = useState("");
  const [branch, setBranch] = useState<Branch>(initialBranch);
  const [serviceName, setServiceName] = useState(appointment.serviceName);
  const [date, setDate] = useState(dateFromStart(appointment.scheduledStart));
  const [scheduledStart, setScheduledStart] = useState(appointment.scheduledStart);
  const [services, setServices] = useState<PublicService[]>([]);
  const [starts, setStarts] = useState<string[]>([]);
  const [servicesState, setServicesState] = useState<"idle" | "loading" | "error">("idle");
  const [availabilityState, setAvailabilityState] = useState<"idle" | "loading" | "error">("idle");
  const [requestState, setRequestState] = useState<RequestState>({ kind: "idle" });

  useEffect(() => {
    const controller = new AbortController();
    setServicesState("loading");
    void loadServices(branch, controller.signal)
      .then((nextServices) => {
        setServices(nextServices);
        setServicesState("idle");
        if (!nextServices.some((service) => service.name === serviceName)) {
          setServiceName("");
          setScheduledStart("");
        }
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setServicesState("error");
      });
    return () => controller.abort();
  }, [branch]);

  useEffect(() => {
    if (serviceName === "" || date === "") {
      setStarts([]);
      setAvailabilityState("idle");
      return;
    }
    const controller = new AbortController();
    setAvailabilityState("loading");
    void loadAvailability(branch, serviceName, date, controller.signal)
      .then((nextStarts) => {
        setStarts(nextStarts);
        setAvailabilityState("idle");
        setScheduledStart((current) => nextStarts.includes(current) ? current : "");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setAvailabilityState("error");
        setStarts([]);
      });
    return () => controller.abort();
  }, [branch, serviceName, date]);

  async function submitModification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (phone.trim() === "" || serviceName === "" || scheduledStart === "") {
      setRequestState({ kind: "error", message: "Completa el teléfono, servicio, fecha y horario para continuar.", alternatives: [], requiresDifferentDate: false });
      return;
    }

    setRequestState({ kind: "loading" });
    try {
      const response = await fetch("/api/public/appointments/reschedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ privateCode, phone, serviceName, branch, scheduledStart }),
      });
      if (response.status === 404) {
        setRequestState({ kind: "error", message: genericCredentialError, alternatives: [], requiresDifferentDate: false });
        return;
      }
      if (response.status === 409) {
        setRequestState({ kind: "error", ...await readConflict(response) });
        return;
      }
      if (!response.ok) {
        setRequestState({ kind: "error", message: await readSafeError(response), alternatives: [], requiresDifferentDate: false });
        return;
      }
      const updated = await readUpdatedAppointment(response);
      setRequestState({ kind: "success", appointment: updated.appointment, notifications: updated.notifications });
    } catch {
      setRequestState({ kind: "error", message: "No fue posible actualizar la cita. Intenta nuevamente.", alternatives: [], requiresDifferentDate: false });
    }
  }

  function selectAlternative(start: string) {
    setDate(dateFromStart(start));
    setScheduledStart(start);
    setRequestState({ kind: "idle" });
  }

  if (requestState.kind === "success") {
    return (
      <div className="lookup-page">
        <section className="lookup-modification lookup-modification--success" aria-labelledby="modification-success-title">
          <p className="lookup-eyebrow">Cambios confirmados</p>
          <h1 id="modification-success-title">Tu cita se actualizó</h1>
          <p className="lookup-modification__lead">Los cambios se guardaron correctamente. Recibirás la información correspondiente en los canales registrados.</p>
          <AppointmentSummary appointment={requestState.appointment} />
          <NotificationStatuses notifications={requestState.notifications} />
          <button className="booking-button booking-button--primary" onClick={() => onUpdated(requestState.appointment)} type="button">Volver a mi cita</button>
        </section>
      </div>
    );
  }

  return (
    <div className="lookup-page">
      <section className="lookup-modification" aria-labelledby="modification-title">
        <div className="lookup-modification__heading">
          <div><p className="lookup-eyebrow">Modifica tu cita</p><h1 id="modification-title">Elige los nuevos datos</h1><p className="lookup-modification__lead">Puedes actualizar fecha, horario, sucursal o servicio. Verificaremos tu teléfono antes de guardar.</p></div>
          <AppointmentSummary appointment={appointment} compact />
        </div>

        <form className="modification-form" onSubmit={(event) => void submitModification(event)} noValidate>
          <fieldset disabled={requestState.kind === "loading"}>
            <legend>Verifiquemos tu identidad</legend>
            <label className="booking-label" htmlFor="modification-phone">Número telefónico</label>
            <input autoComplete="tel" className="booking-input" id="modification-phone" inputMode="tel" name="phone" onChange={(event) => setPhone(event.target.value)} type="tel" value={phone} />
            <p className="modification-form__hint">Usa el mismo número con el que registraste tu cita.</p>
          </fieldset>

          <fieldset disabled={requestState.kind === "loading"}>
            <legend>Selecciona los nuevos datos</legend>
            <div className="modification-form__grid">
              <label className="booking-label" htmlFor="modification-branch">Sucursal
                <select className="booking-input" id="modification-branch" name="branch" onChange={(event) => { setBranch(event.target.value as Branch); setRequestState({ kind: "idle" }); }} value={branch}>
                  {branches.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </label>
              <label className="booking-label" htmlFor="modification-service">Servicio
                <select className="booking-input" disabled={servicesState === "loading" || servicesState === "error"} id="modification-service" name="serviceName" onChange={(event) => { setServiceName(event.target.value); setRequestState({ kind: "idle" }); }} value={serviceName}>
                  <option value="">Selecciona un servicio</option>
                  {services.map((service) => <option key={service.name} value={service.name}>{service.name} · {formatDuration(service.duration_minutes)} · ${service.price} MXN</option>)}
                </select>
              </label>
              <label className="booking-label" htmlFor="modification-date">Nueva fecha
                <input className="booking-input" id="modification-date" name="date" onChange={(event) => { setDate(event.target.value); setRequestState({ kind: "idle" }); }} required type="date" value={date} />
              </label>
            </div>
            {servicesState === "loading" ? <p className="lookup-state" role="status">Cargando servicios disponibles…</p> : null}
            {servicesState === "error" ? <p className="lookup-state lookup-state--error" role="alert">No fue posible cargar los servicios disponibles. Intenta nuevamente.</p> : null}

            <div className="modification-times" aria-labelledby="modification-times-title">
              <h2 id="modification-times-title">Horarios disponibles</h2>
              {availabilityState === "loading" ? <p className="lookup-state" role="status">Cargando horarios disponibles…</p> : null}
              {availabilityState === "error" ? <p className="lookup-state lookup-state--error" role="alert">No fue posible consultar los horarios disponibles. Intenta otra fecha.</p> : null}
              {availabilityState === "idle" && serviceName !== "" && date !== "" ? <p className="modification-form__hint">Selecciona un horario disponible.</p> : null}
              {availabilityState === "idle" && starts.length === 0 && serviceName !== "" && date !== "" ? <p className="modification-form__hint">No hay horarios disponibles para esta fecha. Elige otra fecha.</p> : null}
              {starts.length > 0 ? <div className="modification-time-grid" role="radiogroup" aria-label="Horarios disponibles para la modificación">
                {starts.map((start) => <label className={`modification-time ${scheduledStart === start ? "modification-time--selected" : ""}`} key={start}><input checked={scheduledStart === start} name="scheduledStart" onChange={() => { setScheduledStart(start); setRequestState({ kind: "idle" }); }} type="radio" value={start} /><span>{formatTime(start)}</span></label>)}
              </div> : null}
            </div>
          </fieldset>

          {requestState.kind === "error" ? <div className="lookup-state lookup-state--error" role="alert"><p>{requestState.message}</p>{requestState.alternatives.length > 0 ? <div className="modification-alternatives"><strong>Horarios cercanos disponibles</strong><div>{requestState.alternatives.map((start) => <button className="booking-button" key={start} onClick={() => selectAlternative(start)} type="button">{formatAlternative(start)}</button>)}</div></div> : null}{requestState.requiresDifferentDate ? <p>Elige otra fecha para consultar nuevos horarios.</p> : null}</div> : null}

          <div className="lookup-result__actions"><button className="booking-button" onClick={onBack} type="button">Volver</button><button className="booking-button booking-button--primary" disabled={requestState.kind === "loading"} type="submit">{requestState.kind === "loading" ? "Guardando cambios…" : "Confirmar cambios"}</button></div>
        </form>
      </section>
    </div>
  );
}

function AppointmentSummary({ appointment, compact = false }: { appointment: PublicAppointment; compact?: boolean }) {
  return <dl className={`modification-summary ${compact ? "modification-summary--compact" : ""}`}><div><dt>Servicio</dt><dd>{appointment.serviceName}</dd></div><div><dt>Sucursal</dt><dd>{formatBranch(appointment.branch)}</dd></div><div><dt>Fecha y horario</dt><dd>{formatAlternative(appointment.scheduledStart)}</dd></div><div><dt>Duración y precio</dt><dd>{formatDuration(appointment.durationMinutes)} · ${appointment.price} MXN</dd></div></dl>;
}

async function loadServices(branch: Branch, signal: AbortSignal): Promise<PublicService[]> {
  const response = await fetch(`/api/public/services?branch=${branch}`, { signal });
  if (!response.ok) throw new Error("Unable to load public services.");
  const payload: unknown = await response.json();
  if (!Array.isArray(payload) || !payload.every(isPublicService)) throw new Error("Invalid public services response.");
  return payload;
}

async function loadAvailability(branch: Branch, service: string, date: string, signal: AbortSignal): Promise<string[]> {
  const params = new URLSearchParams({ branch, service, date });
  const response = await fetch(`/api/public/availability?${params.toString()}`, { signal });
  if (!response.ok) throw new Error("Unable to load public availability.");
  const payload: unknown = await response.json();
  if (typeof payload !== "object" || payload === null) throw new Error("Invalid public availability response.");
  const starts = (payload as Record<string, unknown>).starts;
  if (!Array.isArray(starts) || !starts.every((value: unknown) => typeof value === "string")) throw new Error("Invalid public availability response.");
  return starts;
}

async function readUpdatedAppointment(response: Response): Promise<{ appointment: PublicAppointment; notifications: NotificationStatus[] }> {
  const payload: unknown = await response.json();
  if (typeof payload !== "object" || payload === null || !isPublicAppointment((payload as Record<string, unknown>).appointment) || !isNotificationStatuses((payload as Record<string, unknown>).notifications)) throw new Error("Invalid public appointment response.");
  return payload as { appointment: PublicAppointment; notifications: NotificationStatus[] };
}

async function readConflict(response: Response): Promise<{ message: string; alternatives: string[]; requiresDifferentDate: boolean }> {
  const payload: unknown = await response.json();
  if (typeof payload !== "object" || payload === null) return { message: "El horario seleccionado ya no está disponible.", alternatives: [], requiresDifferentDate: false };
  const value = payload as Record<string, unknown>;
  return { message: typeof value.detail === "string" ? value.detail : "El horario seleccionado ya no está disponible.", alternatives: Array.isArray(value.alternatives) && value.alternatives.every((item) => typeof item === "string") ? value.alternatives : [], requiresDifferentDate: value.requiresDifferentDate === true };
}

async function readSafeError(response: Response): Promise<string> {
  const payload: unknown = await response.json().catch(() => null);
  return typeof payload === "object" && payload !== null && typeof (payload as Record<string, unknown>).detail === "string" ? (payload as Record<string, unknown>).detail as string : "No fue posible actualizar la cita. Intenta nuevamente.";
}

function isPublicService(value: unknown): value is PublicService { return typeof value === "object" && value !== null && typeof (value as Record<string, unknown>).name === "string" && typeof (value as Record<string, unknown>).duration_minutes === "number" && typeof (value as Record<string, unknown>).price === "string"; }
function isPublicAppointment(value: unknown): value is PublicAppointment { return typeof value === "object" && value !== null && typeof (value as Record<string, unknown>).serviceName === "string" && typeof (value as Record<string, unknown>).branch === "string" && typeof (value as Record<string, unknown>).scheduledStart === "string" && typeof (value as Record<string, unknown>).durationMinutes === "number" && typeof (value as Record<string, unknown>).price === "string" && typeof (value as Record<string, unknown>).status === "string"; }
function isNotificationStatuses(value: unknown): value is NotificationStatus[] { return Array.isArray(value) && value.every((item) => typeof item === "object" && item !== null && (((item as Record<string, unknown>).channel === "email") || (item as Record<string, unknown>).channel === "whatsapp") && ["pending", "accepted", "delivered", "failed"].includes((item as Record<string, unknown>).status as string)); }
function NotificationStatuses({ notifications }: { notifications: NotificationStatus[] }) { return <section className="cancellation-channels" aria-labelledby="modification-channels-title"><h2 id="modification-channels-title">Estado de tus avisos</h2><ul>{notifications.map((notification) => <li key={notification.channel}>{formatChannel(notification.channel)}: {formatNotificationStatus(notification.status)}</li>)}</ul></section>; }
function formatChannel(value: string): string { return value === "whatsapp" ? "WhatsApp" : "Correo electrónico"; }
function formatNotificationStatus(value: string): string { return value === "failed" ? "No se pudo enviar" : value === "delivered" ? "Entregado" : value === "accepted" ? "Aceptado por el canal" : "Pendiente"; }
function isBranch(value: string): value is Branch { return value === "texcoco" || value === "chiconcuac"; }
function dateFromStart(value: string): string { const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Mexico_City", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(value)); const byType = Object.fromEntries(parts.map((part) => [part.type, part.value])); return `${byType.year}-${byType.month}-${byType.day}`; }
function formatTime(value: string): string { return new Intl.DateTimeFormat("es-MX", { timeZone: "America/Mexico_City", hour: "numeric", minute: "2-digit", hour12: true }).format(new Date(value)); }
function formatAlternative(value: string): string { return new Intl.DateTimeFormat("es-MX", { timeZone: "America/Mexico_City", dateStyle: "long", timeStyle: "short" }).format(new Date(value)); }
function formatDuration(minutes: number): string { return minutes === 60 ? "1 hora" : minutes > 0 && minutes % 60 === 0 ? `${minutes / 60} horas` : `${minutes} minutos`; }
function formatBranch(branch: string): string { return branch === "texcoco" ? "Texcoco" : branch === "chiconcuac" ? "Chiconcuac" : branch; }
